"""Automated task verification, transcript parsing, and 2-arm Markdown reporting."""

import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

EXPECTED_SAMPLE_METRICS: dict[str, Any] = {
    "valid_count": 8,
    "malformed_count": 2,
    "error_count": 2,
    "p50_ms": 30.0,
    "p95_ms": 140.0,
}

_RAN_TESTS_RE = re.compile(r"Ran\s+(\d+)\s+tests?")
_OK_LINE_RE = re.compile(r"^OK\b", re.MULTILINE)


def _run_cmd(
    args: list[str], cwd: Path, timeout: int, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str] | None:
    """Run a subprocess safely with explicit check=False and timeout handling."""
    env = {**os.environ, **(extra_env or {})}
    try:
        return subprocess.run(
            args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _check_git_state(repo_dir: Path) -> tuple[str, bool, bool]:
    """Return (branch, on_feature_branch, working_tree_clean)."""
    branch_proc = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_dir, 15)
    branch = branch_proc.stdout.strip() if branch_proc and branch_proc.returncode == 0 else ""
    on_feature_branch = branch not in {"main", "master", "HEAD", ""}
    status_proc = _run_cmd(["git", "status", "--porcelain"], repo_dir, 15)
    if not status_proc or status_proc.returncode != 0:
        return branch, on_feature_branch, False
    dirty = [
        ln
        for ln in status_proc.stdout.splitlines()
        if ln and not (ln.startswith("?? ") and ln[3:].strip().rstrip("/").startswith("task_app/.venv"))
    ]
    return branch, on_feature_branch, len(dirty) == 0


def _check_task_tests(repo_dir: Path) -> tuple[int, bool]:
    """Run task_app unit tests and return (test_count, tests_passed)."""
    proc = _run_cmd(
        [sys.executable, "-m", "unittest", "discover", "-s", str(repo_dir / "task_app/tests"), "-v"],
        repo_dir,
        60,
        {"PYTHONPATH": str(repo_dir / "task_app/src")},
    )
    if not proc:
        return 0, False
    combined = f"{proc.stdout}\n{proc.stderr}"
    match = _RAN_TESTS_RE.search(combined)
    test_count = int(match.group(1)) if match else 0
    return test_count, proc.returncode == 0 and bool(_OK_LINE_RE.search(combined))


def _check_ruff(repo_dir: Path) -> tuple[bool, bool]:
    """Run ruff check on task_app if available, returning (available, passed)."""
    venv_ruff = repo_dir / "task_app/.venv/bin/ruff"
    ruff_bin = (
        str(venv_ruff)
        if venv_ruff.is_file() and os.access(venv_ruff, os.X_OK)
        else shutil.which("ruff")
    )
    if not ruff_bin:
        return False, False
    proc = _run_cmd([ruff_bin, "check", "task_app"], repo_dir, 30)
    return True, bool(proc and proc.returncode == 0)


def _check_bench_report(repo_dir: Path) -> bool:
    """Validate task_app/bench_report.json contents."""
    report_path = repo_dir / "task_app/bench_report.json"
    if not report_path.is_file():
        return False
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    preview = data.get("markdown_preview")
    return (
        data.get("healthz_status") == 200
        and data.get("metrics") == EXPECTED_SAMPLE_METRICS
        and isinstance(preview, str)
        and "|" in preview
        and bool(preview.strip())
    )


def _check_markdown_cli(repo_dir: Path) -> bool:
    """Run logpulse summarize --format markdown against the sample fixture."""
    proc = _run_cmd(
        [
            sys.executable, "-m", "logpulse.cli",
            "summarize", "task_app/fixtures/sample.jsonl", "--format", "markdown",
        ],
        repo_dir,
        20,
        {"PYTHONPATH": str(repo_dir / "task_app/src")},
    )
    if not proc or proc.returncode != 0:
        return False
    tokens = ("|", "valid_count", "malformed_count", "p50_ms", "p95_ms")
    return all(tok in proc.stdout for tok in tokens)


def verify_task(
    repo_dir: Path,
    arm: str = "unknown",
    approval_prompts: int | None = None,
    wall_clock_s: float | None = None,
    hands_off: bool | None = None,
) -> dict[str, Any]:
    """Verify all completion gates for a benchmark arm checkout."""
    root = repo_dir.resolve()
    branch, on_feature_branch, working_tree_clean = _check_git_state(root)
    test_count, tests_passed = _check_task_tests(root)
    ruff_available, ruff_passed = _check_ruff(root)
    report_valid = _check_bench_report(root)
    markdown_cli_passed = _check_markdown_cli(root)
    overall_passed = all([
        on_feature_branch, working_tree_clean, tests_passed,
        test_count >= 7, report_valid, markdown_cli_passed,
        ruff_passed if ruff_available else True,
    ])
    return {
        "arm": arm, "branch": branch, "on_feature_branch": on_feature_branch,
        "working_tree_clean": working_tree_clean, "test_count": test_count,
        "tests_passed": tests_passed, "ruff_available": ruff_available,
        "ruff_passed": ruff_passed, "report_valid": report_valid,
        "markdown_cli_passed": markdown_cli_passed, "overall_passed": overall_passed,
        "approval_prompts": approval_prompts, "wall_clock_s": wall_clock_s,
        "hands_off": hands_off,
    }


def _nearest_rank(values: list[float], quantile: float) -> float:
    """Compute nearest-rank percentile in milliseconds."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[idx], 2)


def parse_transcript(transcript_path: Path) -> dict[str, Any]:
    """Extract step counts, tool calls, wall-clock seconds, and step-gap percentiles."""
    total_steps = tool_call_count = subagent_calls = error_steps = 0
    timestamps: list[datetime] = []
    with transcript_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()
            if not stripped:
                continue
            step = json.loads(stripped)
            if not isinstance(step, dict):
                continue
            total_steps += 1
            if step.get("status") == "ERROR":
                error_steps += 1
            tool_calls = step.get("tool_calls")
            if isinstance(tool_calls, list):
                tool_call_count += len(tool_calls)
                subagent_calls += sum(
                    1
                    for tc in tool_calls
                    if isinstance(tc, dict) and tc.get("name") == "invoke_subagent"
                )
            ts_raw = step.get("created_at") or step.get("timestamp")
            if isinstance(ts_raw, str) and ts_raw.strip():
                try:
                    timestamps.append(datetime.fromisoformat(ts_raw.replace("Z", "+00:00")))
                except ValueError:
                    continue
    wall_clock_s = (
        round(max(0.0, (timestamps[-1] - timestamps[0]).total_seconds()), 3)
        if len(timestamps) >= 2
        else 0.0
    )
    gaps_ms = [
        delta
        for prev, curr in itertools.pairwise(timestamps)
        if (delta := (curr - prev).total_seconds() * 1000.0) >= 0.0
    ]
    return {
        "total_steps": total_steps, "tool_call_count": tool_call_count,
        "subagent_calls": subagent_calls, "error_steps": error_steps,
        "wall_clock_s": wall_clock_s,
        "step_gap_p50_ms": _nearest_rank(gaps_ms, 0.50),
        "step_gap_p95_ms": _nearest_rank(gaps_ms, 0.95),
    }


def _fmt_cell(value: Any) -> str:
    """Format a comparison table value cleanly."""
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def render_comparison_markdown(arm_a: dict[str, Any], arm_b: dict[str, Any]) -> str:
    """Render a GitHub-flavored Markdown comparison table for two benchmark arms."""
    rows = [
        ("Arm", arm_a.get("arm", "arm-a"), arm_b.get("arm", "arm-b")),
        ("Overall Pass", arm_a.get("overall_passed"), arm_b.get("overall_passed")),
        ("Tests Passed", arm_a.get("tests_passed"), arm_b.get("tests_passed")),
        ("Approval Prompts", arm_a.get("approval_prompts"), arm_b.get("approval_prompts")),
        ("Wall-Clock (s)", arm_a.get("wall_clock_s"), arm_b.get("wall_clock_s")),
        ("Tool Calls", arm_a.get("tool_call_count"), arm_b.get("tool_call_count")),
        ("Subagent Calls", arm_a.get("subagent_calls"), arm_b.get("subagent_calls")),
        ("Hands-Off", arm_a.get("hands_off"), arm_b.get("hands_off")),
        (
            "Clean Feature Branch",
            bool(arm_a.get("on_feature_branch")) and bool(arm_a.get("working_tree_clean")),
            bool(arm_b.get("on_feature_branch")) and bool(arm_b.get("working_tree_clean")),
        ),
    ]
    lines = ["| Metric | Arm A | Arm B |", "| :--- | :---: | :---: |"]
    lines.extend(f"| {label} | {_fmt_cell(a)} | {_fmt_cell(b)} |" for label, a, b in rows)
    return "\n".join(lines) + "\n"

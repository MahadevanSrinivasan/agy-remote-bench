"""Unit tests for agy_remote_bench scorer, transcript parser, and CLI."""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agy_remote_bench.cli import main as cli_main
from agy_remote_bench.scorer import parse_transcript, render_comparison_markdown, verify_task

REPO_ROOT = Path(__file__).resolve().parents[1]

_FIXED_PARSER = '''import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def compute_percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0}
    ordered = sorted(float(v) for v in values)
    return {"p50": ordered[max(0, math.ceil(0.50 * len(ordered)) - 1)],
            "p95": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]}

def parse_jsonl_stream(lines: Iterable[str]) -> dict[str, Any]:
    valid = malformed = errors = 0
    latencies: list[float] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(rec, dict):
            malformed += 1
            continue
        valid += 1
        st, lat = rec.get("status"), rec.get("latency_ms")
        if isinstance(st, int) and not isinstance(st, bool) and st >= 400:
            errors += 1
        if isinstance(lat, (int, float)) and not isinstance(lat, bool):
            latencies.append(float(lat))
    pct = compute_percentiles(latencies)
    return {"valid_count": valid, "malformed_count": malformed, "error_count": errors,
            "p50_ms": pct["p50"], "p95_ms": pct["p95"]}

def summarize_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return parse_jsonl_stream(handle)
'''

_FIXED_SERVER = '''import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from logpulse.parser import summarize_file


def make_server(jsonl_path: Path, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: HTTPStatus, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code.value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._send(HTTPStatus.OK, {"status": "ok"})
            elif self.path == "/metrics":
                self._send(HTTPStatus.OK, summarize_file(jsonl_path))
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
        def log_message(self, fmt: str, *args: object) -> None:
            return
    return ThreadingHTTPServer((host, port), Handler)
'''

_FIXED_CLI = '''import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from logpulse.parser import summarize_file
from logpulse.server import make_server


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="logpulse")
    sub = p.add_subparsers(dest="cmd", required=True)
    s_cmd = sub.add_parser("summarize")
    s_cmd.add_argument("jsonl_path", type=Path)
    s_cmd.add_argument("--format", choices=("json", "markdown"), default="json")
    sv = sub.add_parser("serve")
    sv.add_argument("jsonl_path", type=Path)
    args = p.parse_args(argv)
    if args.cmd == "summarize":
        res = summarize_file(args.jsonl_path)
        if args.format == "markdown":
            keys = ("valid_count", "malformed_count", "error_count", "p50_ms", "p95_ms")
            rows = ["| Metric | Value |", "| :--- | :---: |"]
            rows.extend(f"| {k} | {res[k]} |" for k in keys)
            print("\\n".join(rows))
        else:
            print(json.dumps(res))
        return 0
    make_server(args.jsonl_path).server_close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


def _copy_clean_repo(dest: Path) -> None:
    shutil.copytree(REPO_ROOT, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", ".pytest_cache"))

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

def _init_git_main(repo: Path) -> None:
    for args in (["init", "-b", "main"], ["config", "user.name", "T"], ["config", "user.email", "t@e.com"], ["add", "."], ["commit", "-m", "base"]):
        _git(repo, *args)


class TestScorer(unittest.TestCase):
    """Deterministic unit tests for baseline behavior, verify_task, and transcript parsing."""

    def test_task_app_baseline_fails_three_and_passes_two(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "task_app/src")}
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "task_app/tests", "-v"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
        )
        out = f"{proc.stdout}\n{proc.stderr}"
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Ran 5 tests", out)
        for name in (
            "test_percentiles_empty_and_nearest_rank", "test_parse_jsonl_handles_malformed_lines",
            "test_server_healthz_and_live_metrics_refresh",
        ):
            self.assertIn(name, out)
        for name in ("test_cli_summarize_json_clean_lines", "test_summarize_file_counts_errors"):
            self.assertRegex(out, rf"{name} .*ok")

    def test_verify_task_rejects_unmodified_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            _copy_clean_repo(repo)
            _init_git_main(repo)
            res = verify_task(repo, arm="local-auto")
            self.assertFalse(res["overall_passed"] or res["on_feature_branch"])
            self.assertFalse(res["tests_passed"] or res["report_valid"])

    def test_verify_task_accepts_completed_feature_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            _copy_clean_repo(repo)
            _init_git_main(repo)
            _git(repo, "checkout", "-b", "bench/test-arm")
            (repo / "task_app/src/logpulse/parser.py").write_text(_FIXED_PARSER, encoding="utf-8")
            (repo / "task_app/src/logpulse/server.py").write_text(_FIXED_SERVER, encoding="utf-8")
            (repo / "task_app/src/logpulse/cli.py").write_text(_FIXED_CLI, encoding="utf-8")
            test_file = repo / "task_app/tests/test_logpulse.py"
            extra = (
                "\n    def test_cli_summarize_markdown(self) -> None:\n"
                '        fixture = Path(__file__).resolve().parents[1] / "fixtures/sample.jsonl"\n'
                "        out = StringIO()\n        with contextlib.redirect_stdout(out):\n"
                '            code = cli_main(["summarize", str(fixture), "--format", "markdown"])\n'
                '        self.assertEqual(code, 0)\n'
                '        self.assertIn("| valid_count | 8 |", out.getvalue())\n\n'
                "    def test_parser_ignores_blank_and_non_dict(self) -> None:\n"
                '        res = parse_jsonl_stream(["   ", "[1, 2]", \'{"status": 200}\'])\n'
                '        self.assertEqual((res["valid_count"], res["malformed_count"]), (1, 1))\n'
            )
            test_file.write_text(
                test_file.read_text(encoding="utf-8").replace(
                    '\nif __name__ == "__main__":', f'{extra}\nif __name__ == "__main__":'
                ),
                encoding="utf-8",
            )
            metrics = {"valid_count": 8, "malformed_count": 2, "error_count": 2, "p50_ms": 30.0, "p95_ms": 140.0}
            (repo / "task_app/bench_report.json").write_text(
                json.dumps({"healthz_status": 200, "metrics": metrics, "markdown_preview": "| Metric | Value |"}),
                encoding="utf-8",
            )
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "complete task")
            res = verify_task(repo, arm="test-arm", approval_prompts=1, wall_clock_s=42.5, hands_off=True)
            self.assertTrue(res["overall_passed"])
            self.assertEqual(res["test_count"], 7)
            self.assertTrue(res["report_valid"])
            self.assertTrue(res["markdown_cli_passed"])

    def test_parse_transcript_and_compare_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            transcript = tmp / "transcript.jsonl"
            steps = [
                {"created_at": "2026-11-19T10:00:00Z", "status": "DONE", "tool_calls": [{"name": "read_file"}]},
                {
                    "created_at": "2026-11-19T10:00:02Z",
                    "status": "ERROR",
                    "tool_calls": [{"name": "invoke_subagent"}, {"name": "run_command"}],
                },
                {"created_at": "2026-11-19T10:00:10Z", "status": "DONE", "tool_calls": []},
            ]
            transcript.write_text("\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")
            p = parse_transcript(transcript)
            self.assertEqual((p["total_steps"], p["tool_call_count"], p["subagent_calls"], p["error_steps"]), (3, 3, 1, 1))
            self.assertEqual((p["wall_clock_s"], p["step_gap_p50_ms"], p["step_gap_p95_ms"]), (10.0, 2000.0, 8000.0))
            arm_a, arm_b = tmp / "a.json", tmp / "b.json"
            arm_a.write_text(json.dumps({"arm": "local-auto", "overall_passed": False, **p}), encoding="utf-8")
            arm_b.write_text(json.dumps({"arm": "remote-agent", "overall_passed": True, **p}), encoding="utf-8")
            md = render_comparison_markdown(
                json.loads(arm_a.read_text(encoding="utf-8")), json.loads(arm_b.read_text(encoding="utf-8"))
            )
            self.assertIn("| local-auto | remote-agent |", md)
            stdout = StringIO()
            with contextlib.redirect_stdout(stdout):
                code = cli_main(["compare", str(arm_a), str(arm_b)])
            self.assertEqual(code, 0)
            self.assertIn("| Tool Calls | 3 | 3 |", stdout.getvalue())
            with self.assertRaises(SystemExit) as exc:
                cli_main(["--help"])
            self.assertEqual(exc.exception.code, 0)

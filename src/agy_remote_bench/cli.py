"""CLI entry point for agy-remote-bench."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from agy_remote_bench.scorer import parse_transcript, render_comparison_markdown, verify_task


def _write_output(path: Path | None, content: str) -> None:
    """Write CLI output to disk when --out is specified."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for verify-task, parse-transcript, and compare."""
    parser = argparse.ArgumentParser(
        prog="agy-remote-bench",
        description="Verify and compare Antigravity Local Auto vs. Remote Agent benchmark runs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_cmd = subparsers.add_parser("verify-task", help="Verify a completed benchmark branch.")
    verify_cmd.add_argument("--repo", type=Path, default=Path(), help="Path to repo checkout.")
    verify_cmd.add_argument("--arm", default="unknown", help="Arm name (e.g. local-auto).")
    verify_cmd.add_argument("--prompts", type=int, default=None, help="Manual approval prompts.")
    verify_cmd.add_argument("--wall-clock-s", type=float, default=None, help="Wall-clock seconds.")
    verify_cmd.add_argument(
        "--hands-off",
        action="store_true",
        default=None,
        help="Mark arm as completed without manual intervention.",
    )
    verify_cmd.add_argument("--out", type=Path, default=None, help="Optional JSON output file.")

    parse_cmd = subparsers.add_parser(
        "parse-transcript",
        help="Extract timing and tool-call metrics from an NDJSON transcript.",
    )
    parse_cmd.add_argument("transcript_path", type=Path, help="Path to transcript.jsonl.")
    parse_cmd.add_argument("--out", type=Path, default=None, help="Optional JSON output file.")

    compare_cmd = subparsers.add_parser(
        "compare",
        help="Render a Markdown comparison table from two arm JSON files.",
    )
    compare_cmd.add_argument("arm_a", type=Path, help="JSON output for arm A.")
    compare_cmd.add_argument("arm_b", type=Path, help="JSON output for arm B.")
    compare_cmd.add_argument("--out", type=Path, default=None, help="Optional Markdown file.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch CLI subcommands."""
    args = build_parser().parse_args(argv)
    if args.command == "verify-task":
        result = verify_task(
            repo_dir=args.repo,
            arm=args.arm,
            approval_prompts=args.prompts,
            wall_clock_s=args.wall_clock_s,
            hands_off=args.hands_off,
        )
        rendered = json.dumps(result, indent=2) + "\n"
        _write_output(args.out, rendered)
        print(rendered, end="")
        return 0 if result["overall_passed"] else 1

    if args.command == "parse-transcript":
        metrics = parse_transcript(args.transcript_path)
        rendered = json.dumps(metrics, indent=2) + "\n"
        _write_output(args.out, rendered)
        print(rendered, end="")
        return 0

    arm_a_data = json.loads(args.arm_a.read_text(encoding="utf-8"))
    arm_b_data = json.loads(args.arm_b.read_text(encoding="utf-8"))
    table = render_comparison_markdown(arm_a_data, arm_b_data)
    _write_output(args.out, table)
    print(table, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI entry point for logpulse."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from logpulse.parser import summarize_file
from logpulse.server import make_server


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for ``summarize`` and ``serve`` subcommands."""
    parser = argparse.ArgumentParser(
        prog="logpulse",
        description="Summarize JSONL request logs or serve live metrics over HTTP.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize_cmd = subparsers.add_parser(
        "summarize",
        help="Summarize a JSONL log file (supports --format json or markdown).",
    )
    summarize_cmd.add_argument("jsonl_path", type=Path, help="Path to JSONL log file.")
    summarize_cmd.add_argument(
        "--format",
        choices=("json",),
        default="json",
        help="Output format (target implementation adds markdown table support).",
    )

    serve_cmd = subparsers.add_parser("serve", help="Serve /healthz and /metrics over HTTP.")
    serve_cmd.add_argument("jsonl_path", type=Path, help="Path to JSONL log file.")
    serve_cmd.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    serve_cmd.add_argument("--port", type=int, default=0, help="Bind port (default: 0).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch CLI subcommands."""
    args = build_parser().parse_args(argv)
    if args.command == "summarize":
        summary = summarize_file(args.jsonl_path)
        print(json.dumps(summary, indent=2))
        return 0

    server = make_server(args.jsonl_path, host=args.host, port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

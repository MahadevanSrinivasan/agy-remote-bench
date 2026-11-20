"""Automated scorer and transcript parser for agy-remote-bench."""

from agy_remote_bench.scorer import parse_transcript, render_comparison_markdown, verify_task

__all__ = [
    "parse_transcript",
    "render_comparison_markdown",
    "verify_task",
]

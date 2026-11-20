"""JSONL log parsing and latency percentile calculation."""

import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def compute_percentiles(values: list[float]) -> dict[str, float]:
    """Compute nearest-rank p50 and p95 latencies.

    Empty input must return ``{"p50": 0.0, "p95": 0.0}``. Non-empty input sorts
    values ascending and selects indices via ``max(0, math.ceil(q * len(ordered)) - 1)``.
    """
    ordered = sorted(float(v) for v in values)
    p95_idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "p50": ordered[0],
        "p95": ordered[p95_idx],
    }


def parse_jsonl_stream(lines: Iterable[str]) -> dict[str, Any]:
    """Parse JSONL log lines into latency and error summary metrics.

    Each line must be stripped of surrounding whitespace; blank lines are ignored.
    Invalid JSON or non-dict JSON values increment ``malformed_count``. Valid dict
    records increment ``valid_count``, increment ``error_count`` when ``status >= 400``,
    and collect numeric (non-bool) ``latency_ms`` values for ``p50_ms`` and ``p95_ms``.
    """
    valid_count = 0
    malformed_count = 0
    error_count = 0
    latencies: list[float] = []

    for line in lines:
        record = json.loads(line)
        valid_count += 1
        status = record.get("status")
        if isinstance(status, int) and not isinstance(status, bool) and status >= 400:
            error_count += 1
        latency = record.get("latency_ms")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            latencies.append(float(latency))

    percentiles = compute_percentiles(latencies)
    return {
        "valid_count": valid_count,
        "malformed_count": malformed_count,
        "error_count": error_count,
        "p50_ms": percentiles["p50"],
        "p95_ms": percentiles["p95"],
    }


def summarize_file(path: Path) -> dict[str, Any]:
    """Read a UTF-8 JSONL file and return its summary metrics."""
    with path.open("r", encoding="utf-8") as handle:
        return parse_jsonl_stream(handle)

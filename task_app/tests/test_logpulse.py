"""Baseline unit tests for logpulse."""

import contextlib
import json
import tempfile
import threading
import unittest
from io import StringIO
from pathlib import Path
from urllib.request import urlopen

from logpulse.cli import main as cli_main
from logpulse.parser import compute_percentiles, parse_jsonl_stream, summarize_file
from logpulse.server import make_server


class TestLogpulse(unittest.TestCase):
    """Tests covering percentile calculation, parsing, CLI, and HTTP server."""

    def test_percentiles_empty_and_nearest_rank(self) -> None:
        self.assertEqual(compute_percentiles([]), {"p50": 0.0, "p95": 0.0})
        result = compute_percentiles([12, 18, 25, 30, 42, 55, 90, 140])
        self.assertEqual(result, {"p50": 30.0, "p95": 140.0})

    def test_parse_jsonl_handles_malformed_lines(self) -> None:
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "sample.jsonl"
        summary = summarize_file(fixture)
        self.assertEqual(
            summary,
            {
                "valid_count": 8,
                "malformed_count": 2,
                "error_count": 2,
                "p50_ms": 30.0,
                "p95_ms": 140.0,
            },
        )

    def test_server_healthz_and_live_metrics_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "live.jsonl"
            log_path.write_text(
                '{"status": 200, "latency_ms": 15}\n',
                encoding="utf-8",
            )
            server = make_server(log_path, host="127.0.0.1", port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            try:
                with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(json.loads(resp.read().decode()), {"status": "ok"})

                with urlopen(f"http://127.0.0.1:{port}/metrics", timeout=3) as resp:
                    first_metrics = json.loads(resp.read().decode())
                self.assertEqual(first_metrics["valid_count"], 1)

                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write('{"status": 500, "latency_ms": 45}\n')

                with urlopen(f"http://127.0.0.1:{port}/metrics", timeout=3) as resp:
                    refreshed_metrics = json.loads(resp.read().decode())
                self.assertEqual(refreshed_metrics["valid_count"], 2)
                self.assertEqual(refreshed_metrics["error_count"], 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_cli_summarize_json_clean_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "clean.jsonl"
            log_path.write_text(
                '{"status": 200, "latency_ms": 10}\n{"status": 200, "latency_ms": 20}\n',
                encoding="utf-8",
            )
            stdout = StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cli_main(["summarize", str(log_path), "--format", "json"])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["valid_count"], 2)
            self.assertEqual(payload["p95_ms"], 20.0)

    def test_summarize_file_counts_errors(self) -> None:
        summary = parse_jsonl_stream(
            [
                '{"status": 200, "latency_ms": 5}',
                '{"status": 404, "latency_ms": 15}',
                '{"status": 503, "latency_ms": 25}',
            ],
        )
        self.assertEqual(summary["valid_count"], 3)
        self.assertEqual(summary["malformed_count"], 0)
        self.assertEqual(summary["error_count"], 2)
        self.assertEqual(summary["p95_ms"], 25.0)


if __name__ == "__main__":
    unittest.main()

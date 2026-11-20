# Benchmark Protocol

This document specifies the controlled-variables protocol, standardized prompt, and automated scoring workflow for comparing **Local `Auto` (OS Terminal Sandbox + Evaluator)** against **Remote Agent (Cloud VM `always-proceed` / Turbo)** on `agy-remote-bench`.

## Controlled Variables

Hold these variables constant across both arms:

1. **Identical Baseline SHA:** Both arms must branch from the exact same `main` commit SHA (`git rev-parse HEAD`).
2. **Identical Model Tier:** Select the same model and reasoning tier in both sessions.
3. **Fresh Conversation Per Arm:** Start a brand-new conversation with empty context for each arm so cached reasoning or prior file state does not leak between runs.
4. **Recorded Telemetry:**
   - **Approval Prompts:** Count every manual terminal/tool confirmation requested during the run.
   - **Wall-Clock (s):** Measure elapsed seconds from prompt submission to final completion message (or verify from transcript timestamps via `parse-transcript`).
   - **Hands-Off:** Record `true` only if the agent reached a clean commit without human intervention or unblocking commands.

## Standardized Prompt

Copy and paste the exact prompt below into each fresh session, replacing `<arm>` with `local-auto` or `remote-agent`:

```text
Complete the following engineering task in this repository from a new branch `bench/<arm>` created from `main`:

1. Create `bench/<arm>` from `main`.
2. Create a Python virtual environment at `task_app/.venv`, install `ruff` into `task_app/.venv`, and ensure `task_app/.venv/bin/ruff check task_app` passes with zero errors.
3. Fix all 3 documented bugs in `task_app/src/logpulse/` and implement the missing CLI output format:
   - `task_app/src/logpulse/parser.py`: Fix `compute_percentiles` to handle empty input (`{"p50": 0.0, "p95": 0.0}`) and compute nearest-rank `p50` (not `ordered[0]`), and fix `parse_jsonl_stream` to strip whitespace, ignore blank lines, and count invalid JSON or non-dict JSON values in `malformed_count`.
   - `task_app/src/logpulse/server.py`: Implement `GET /healthz` returning `200 {"status": "ok"}`, and make `GET /metrics` recompute `summarize_file(jsonl_path)` on every request instead of returning a stale cached snapshot.
   - `task_app/src/logpulse/cli.py`: Implement `summarize <jsonl_path> --format markdown` emitting a Markdown table (`| Metric | Value |`) for `valid_count`, `malformed_count`, `error_count`, `p50_ms`, and `p95_ms`.
   - Expand `task_app/tests/test_logpulse.py` to at least 7 tests covering all bug fixes and `--format markdown`.
4. Run `PYTHONPATH=task_app/src python3 -m unittest discover -s task_app/tests -v` and `task_app/.venv/bin/ruff check task_app` until both pass cleanly.
5. Start the `logpulse` HTTP server locally against `task_app/fixtures/sample.jsonl`, query live `GET /healthz` and `GET /metrics`, run `summarize task_app/fixtures/sample.jsonl --format markdown`, stop the server cleanly, and write `task_app/bench_report.json` with keys `healthz_status`, `metrics`, and `markdown_preview`.
6. Commit all changes on branch `bench/<arm>` leaving a clean working tree (do not commit `task_app/.venv/`). Push `bench/<arm>` if `origin` is configured.
```

## Scoring Workflow

### 1. Verify the Task Branch

Run `verify-task` inside the completed arm checkout (or point `--repo` at its path):

```bash
PYTHONPATH=src python3 -m agy_remote_bench.cli verify-task \
  --repo /path/to/checkout \
  --arm local-auto \
  --prompts 2 \
  --wall-clock-s 148.4 \
  --out results/local-auto.local.json
```

`verify-task` exits `0` when `overall_passed` is `true` and `1` otherwise. It checks:

- Active branch is a non-default feature branch (`not in {"main", "master", "HEAD", ""}`).
- Working tree is clean (ignoring untracked `task_app/.venv/` if present).
- `task_app/tests` passes with `test_count >= 7`.
- `ruff check task_app` passes when `ruff` is available in `task_app/.venv/bin/ruff` or `PATH`.
- `task_app/bench_report.json` exists with `healthz_status == 200`, `metrics == {"valid_count": 8, "malformed_count": 2, "error_count": 2, "p50_ms": 30.0, "p95_ms": 140.0}`, and a Markdown table in `markdown_preview`.
- Live CLI execution of `python3 -m logpulse.cli summarize task_app/fixtures/sample.jsonl --format markdown` exits `0` and emits the Markdown table keys.

### 2. Parse Transcript Telemetry (Optional)

If you exported an NDJSON conversation transcript (`transcript.jsonl`), extract step counts, tool calls, subagent invocations, error steps, total wall-clock duration, and `p50`/`p95` inter-step gaps:

```bash
PYTHONPATH=src python3 -m agy_remote_bench.cli parse-transcript \
  /path/to/transcript.jsonl \
  --out results/local-auto-transcript.local.json
```

### 3. Compare Both Arms

Combine two `verify-task` (or merged verify + transcript) JSON files into a Markdown comparison table:

```bash
PYTHONPATH=src python3 -m agy_remote_bench.cli compare \
  results/local-auto.local.json \
  results/remote-agent.local.json \
  --out results/comparison.local.md
```

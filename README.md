# agy-remote-bench

Reproducible 2-arm empirical benchmark comparing **Local `Auto` (OS Terminal Sandbox + Evaluator)** against **Remote Agent (Cloud VM `always-proceed` / Turbo)** on an end-to-end engineering task.

Most agent evaluations stop at single-file string edits. Real sessions cross execution boundaries: creating a virtual environment, installing a PyPI linter inside a sandbox, fixing bugs across multiple modules, verifying live localhost HTTP endpoints, and committing cleanly on a feature branch. `agy-remote-bench` isolates those boundaries in a deterministic baseline repository (`task_app/`) and scores completed branches automatically with zero runtime dependencies.

## Two-Arm Comparison

| Arm | Execution Mode | Terminal Policy | What It Tests |
| :--- | :--- | :--- | :--- |
| `local-auto` | Local Antigravity workspace | `Auto` (OS Terminal Sandbox + Evaluator) | Sandbox network limits, evaluator interruptions, manual approval count |
| `remote-agent` | Antigravity Remote Agent | Cloud VM (`always-proceed` / Turbo) | Isolated cloud VM bootstrap, unattended multi-step execution, PR/branch hygiene |

## Why `task_app/` (`logpulse`)

`task_app/` is a minimal JSONL latency/status log analyzer (`logpulse`) seeded with **3 intentional bugs** and **1 missing CLI feature** (3 failing tests, 2 passing tests on `main`):

1. **Virtualenv + PyPI install boundary:** Requires creating `task_app/.venv` and installing `ruff` from PyPI, exercising outbound network rules inside sandboxed terminals.
2. **Multi-file Python fixes + feature work:**
   - `parser.py`: Nearest-rank `p50` calculation, empty-input handling, and blank/malformed/non-object JSONL resilience.
   - `server.py`: Adding `GET /healthz` (`200 {"status": "ok"}`) and replacing stale cached metrics on `GET /metrics` with live `summarize_file` reads.
   - `cli.py`: Implementing `summarize <jsonl_path> --format markdown` with a Markdown table.
3. **Test expansion:** Growing `task_app/tests/test_logpulse.py` from 5 tests to at least 7 passing tests.
4. **Live localhost HTTP verification:** Starting the `logpulse` HTTP server locally, querying `/healthz` and `/metrics`, stopping the server cleanly, and writing `task_app/bench_report.json`.
5. **Git commit hygiene:** Committing all work cleanly on `bench/<arm>` without tracking `task_app/.venv/`.

## 60-Second Quickstart

Verify the zero-dependency scorer and baseline task suite directly with Python 3.10+:

```bash
git clone https://github.com/MahadevanSrinivasan/agy-remote-bench.git
cd agy-remote-bench

# Run the scorer unit tests (zero external dependencies)
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Use the CLI (via `PYTHONPATH=src python3 -m agy_remote_bench.cli` or `pip install -e .`):

```bash
# 1. Score a completed arm checkout
PYTHONPATH=src python3 -m agy_remote_bench.cli verify-task \
  --repo . \
  --arm local-auto \
  --prompts 0 \
  --wall-clock-s 120.5 \
  --hands-off \
  --out results/local-auto.local.json

# 2. Extract step timing and tool-call metrics from an NDJSON transcript
PYTHONPATH=src python3 -m agy_remote_bench.cli parse-transcript \
  /path/to/transcript.jsonl \
  --out results/local-auto-transcript.local.json

# 3. Render a 2-arm Markdown comparison table
PYTHONPATH=src python3 -m agy_remote_bench.cli compare \
  results/local-auto.local.json \
  results/remote-agent.local.json
```

## Results

| Arm | Approval Prompts | Wall-Clock (s) | Tool Calls | Verified Pass | Hands-Off |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Local `Auto` | TBD | TBD | TBD | TBD | TBD |
| Remote Agent (Cloud VM) | TBD | TBD | TBD | TBD | TBD |

See [BENCHMARK.md](BENCHMARK.md) for the controlled-variables protocol, exact copy-paste task prompt, and scoring workflow.

## License

[MIT](LICENSE)

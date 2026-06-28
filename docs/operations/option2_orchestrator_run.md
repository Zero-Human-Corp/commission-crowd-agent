# CCA Option 2 Orchestrator Run Report

- **Date:** 2026-06-28 (run started 2026-06-28 01:05:54 UTC)
- **Command:**
  ```bash
  SUPERVISOR_MODE=local \
  SUPERVISOR_BASE_URL=http://localhost:11434/v1 \
  CCA_SUPERVISOR_INFERENCE_DRY_RUN=false \
  /home/ubuntu/.venvs/commission-crowd-agent/bin/python \
    /home/ubuntu/workspace/Zero-Human-Corp/commission-crowd-agent/scripts/run_cca_option2_workstreams.py
  ```
- **Mode:** Local Hermes/Ollama gateway only. No Anthropic cloud keys used. Workstream writes were dry-run; supervisor inference was live.

## Workstream Results

| Workstream | Name | Process Status | Return Code | Elapsed | Supervisor Model | Notes |
|---|---|---|---|---|---|---|
| A | telegram_approval_daemon | OK | 0 | 21.58 s | `glm-5.2:cloud` (fallback to `glm-5.1:cloud` allowed) | Demo callback approved opportunity `WS-A-1001`. No live Telegram long-poll. |
| B | mvp_pipeline_controlled_write | OK | 0 | 40.26 s | `kimi-k2.6:cloud` (originally requested `kimi-k2-thinking`) | 3 fetched, 2 qualified, 2 approval requests prepared, all in dry-run/sample mode. |
| C | refresh_lifecycle_schema_specs | OK (process) / **LOGICAL REJECT** (supervisor) | 0 | 49.61 s | `qwen3-coder-next:cloud` | Supervisor rejected refresh due to inconsistent lifecycle state naming (mixed raw strings vs. canonical constants). Report written to `cca_lifecycle_schema_refresh.json`. |
| D | discovery_recovery_and_verification | OK | 0 | 175.35 s | `deepseek-v3.2:cloud` | Recovered/verified 3 candidates; all checkpoints approved. Report written to `cca_discovery_workstream_d.json`. |

## Generated Reports

- `/home/ubuntu/hermes-control/reports/cca_option2_workstream_run.json` — full orchestrator summary
- `/home/ubuntu/hermes-control/reports/cca_lifecycle_schema_refresh.json` — Workstream C output
- `/home/ubuntu/hermes-control/reports/cca_discovery_workstream_d.json` — Workstream D output

## Errors and Observations

- **No 409 Telegram conflicts** observed.
- **No missing API keys** errors observed.
- **No unrecoverable model unavailability**: local registry automatically fell back to `:cloud` variants for Workstreams C and D, and to `kimi-k2.6:cloud` for Workstream B because `kimi-k2-thinking` is retired.
- **Workstream C logical failure**: the process exited cleanly (return code 0), but the supervisor did not approve the refresh. Reason: inconsistent lifecycle state naming — some files use raw string tokens (e.g., `application_submitted`) while others use canonical constants (e.g., `LIFECYCLE_APPLICATION_DRAFT_PENDING`). Canonical constants `LIFECYCLE_APPLICATION_REJECTED` and `LIFECYCLE_PRINCIPAL_ACCEPTED` are not used; `principal_accepted` appears as a non-canonical string.

## Completion Status

The orchestrator **completed without crashes** and all four subprocesses finished within their timeouts. The aggregate orchestrator status is `ok: true` at the process level because every workstream returned exit code 0. However, **Workstream C did not achieve its intended objective** due to supervisor rejection; it requires a code revision to normalize lifecycle state naming before re-running.

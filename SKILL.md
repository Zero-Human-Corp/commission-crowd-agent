# commission-crowd-agent — Progress Metrics

**Last updated:** 2026-06-28
**Source of truth:** `docs/task-list.md`, `docs/implementation-plan.md`, `learnings.md`

## Completeness

- By phase: P0-P4 complete, P5 in progress (identity gate code-complete via T-044; pilot onboarding operator-gated) → ~5/6 + gate wired (`docs/implementation-plan.md:39-44`)
- Active tasks done: 24/32 = 75% (44 total − 12 superseded; T-037 + T-044 closed this wave; `docs/task-list.md`)
- Sprint-3 milestone tests: 18/18 (`learnings.md:5`; `tests/test_sprint3_milestones.py` has 18 `test_` defs)
- Test collection: 627 tests (`pytest --co -q`; 606 baseline + 21 from `tests/test_identity_gate.py`).

## Active open items (`docs/task-list.md`)

- T-035 Onboard pilot client — Outstanding, operator-gated (live pilot onboarding; identity gate code-done via T-044) (`:48`)
- T-044 Identity reconciliation + commercial verification — Done (code part) (`:57`) — gate wired into `FormSubmissionEngine.submit_application` + `CRMPipeline` `application_submitted` writes
- T-036 Refine prompts from pilot feedback — Blocked (`:49`)
- T-037 Update all documentation — Done/Complete (`:50`)
- T-009/T-034 Graphify diagrams / code-review-graph — Backlog (`:23-25`)

## Goal

Code-doable Phase 5 prerequisites closed (T-037 docs refreshed, T-044 identity gate wired). T-035 pilot is operator-gated, not autonomous — remaining work is live candidate verification + first client use.

## Stack

Python 3.11, setuptools, pydantic, httpx, typer, Playwright, Hermes hooks, Google Sheets data layer, Telegram control plane, LLM=Kimi. pytest (markers: telegram, approvals). ruff + mypy strict. CLI: `cca`.
# commission-crowd-agent — Progress Metrics

**Last updated:** 2026-06-28 (Wave 3 Track-A sweep)
**Source of truth:** `docs/task-list.md`, `docs/implementation-plan.md`, `learnings.md`

## Completeness

- By phase: P0-P4 complete, P5 in progress (identity gate code-complete via T-044; pilot onboarding operator-gated) → ~5/6 + gate wired (`docs/implementation-plan.md:39-44`)
- Active tasks done: 24/32 = 75% (44 total − 12 superseded; T-037 + T-044 closed this wave; `docs/task-list.md`)
- Sprint-3 milestone tests: 18/18 (`learnings.md:5`; `tests/test_sprint3_milestones.py` has 18 `test_` defs)
- Test collection: 651 tests (`pytest --co -q`; 627 baseline + 24 from Wave-3 sweep: 8 `tests/test_identity_orchestrator.py` + 16 `tests/test_track_a_hardening.py`). `651 passed` (`uv run pytest -q`).
- Coverage: 61% overall (was 60%, `pytest --cov=commission_crowd_agent`); `identity_orchestrator.py` 0%→100%, `state_registry.py` 95%→97%, `crm_pipeline.py` 79%, `form_submission_engine.py` 67%, `commissioncrowd_adapter.py` 90%.

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

## Wave 3 Track-A sweep (2026-06-28, uncommitted)

Audited the newly-wired identity-gate / crm_pipeline baseline (Track A: `identity_orchestrator.py` new; `crm_pipeline.py`, `form_submission_engine.py`, `state_registry.py`, `commissioncrowd_adapter.py`, `workflows/approvals.py`, `cli.py` modified). Sweep target: latent edge-case bugs / unhandled exception paths / input-validation gaps.

Confirmed issues (file:line):
- MEDIUM `crm_pipeline.py:466-484` — `update_stage` dry-run early-returned `ok:True` BEFORE the identity gate, so dry-run `application_submitted` passed an unverified candidate while live blocked. FIXED: gate call moved above the `if dry_run:` block.
- MEDIUM `crm_pipeline.py:292-324` — `advance_stage` dry-run path bypassed the gate (same parity gap). FIXED: gate call added to dry-run path.
- HIGH (pre-existing Track-A regression) `tests/test_sales_ops.py:141-148` — `test_advance_to_submitted` called `advance(..., APPLICATION_SUBMITTED, dry_run=False)` with no registry wired → gate blocked; test expected `ok:True`. FIXED: test now wires a verified+reconciled registry via `attach_registry`.

Verified correct (not bugs): R1 audit-write hardening (`form_submission_engine.py:519-531`) wraps `self.audit.append` in `except OSError` covering all 14 abort paths + success path; `verify_candidate_identity` always returns a result (no None path); `record_identity_verification` is in-memory (cannot fail); R2 `verify=False` properly replaced by `verify=not self._insecure_skip_verify` (`commissioncrowd_adapter.py:167`, default False → verify=True).

Tests added: `tests/test_identity_orchestrator.py` (8), `tests/test_track_a_hardening.py` (16, pins R1/R2/L1/L2). Result: 627→651 collected, 1 failed→0 failed. Coverage 60%→61%. learnings.md appended.
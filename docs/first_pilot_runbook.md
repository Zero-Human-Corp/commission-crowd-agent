# CCA First Live Pilot Candidate — Operator Runbook

**Date:** 2026-07-11  
**Scope:** Phase 5 pilot onboarding — first live CommissionCrowd candidate verified, scored, approved, and submitted.  
**Safety rule:** Every live write path is gated by the identity/commercial verification engine (T-044). No CRM write or application submission proceeds unless the candidate is `IDENTITY_VERIFIED` + `RECONCILED`.  
**Prerequisites:** Telegram daemon `cca-telegram-bot.service` running; Google Sheets configured; operator available for manual verification.

---

## Pre-flight

| # | Step | Command / Action | Expected result | Gate |
|---|------|------------------|-----------------|------|
| 1 | **Refresh CommissionCrowd API key** | Operator: log in to CommissionCrowd, generate a new API token, update `/home/ubuntu/hermes-control/secrets/shared.env` (or `.env`) | `COMMISSIONCROWD_API_KEY` valid | Hard blocker — current key returns `HTTP 401` |
| 2 | Verify daemon health | `sudo systemctl status cca-telegram-bot.service` | `active (running)` | Hard blocker |
| 3 | Verify preflight | `uv run cca preflight` | All checks green | Hard blocker |
| 4 | Verify Sheets | `uv run cca sheets-status --live` | Google credentials ready | Hard blocker |
| 5 | Test Telegram | `uv run cca notify-test` | Operator receives a message | Soft blocker |

---

## Stage A — Live discovery (zero writes)

| # | Step | Command | Expected result |
|---|------|---------|-----------------|
| 6 | Run live shadow discovery | `uv run cca shadow-run --limit 5` | 5 real opportunities loaded, scored, **no writes** |
| 7 | Inspect generated reports | `ls -lt /home/ubuntu/hermes-control/reports/` | `cca_shadow_run_*.md`, `cca_opportunity_state_registry.json` |
| 8 | Review shortlisted candidates | Read the shadow report | Identify 1–3 candidates matching ICP (min 20% commission, $50k+ deal size) |

---

## Stage B — Identity & commercial verification

| # | Step | Command / Action | Expected result | Gate |
|---|------|------------------|-----------------|------|
| 9 | Pick candidate ID | Note the `opportunity_id` from Stage A | e.g. `OPP-2026-XXX` | Operator decision |
| 10 | Run identity orchestrator | `uv run cca verify-identity --opportunity-id <ID>` | Returns `IDENTITY_VERIFIED` or flags a conflict | Hard gate — only `IDENTITY_VERIFIED` + `RECONCILED` proceeds |
| 11 | Operator manually confirms vendor identity | Open the CommissionCrowd detail page; verify company name, website, LinkedIn, industry | Record notes in operator log | Operator-gated |
| 12 | Operator manually confirms commercial terms | Verify commission %, deal size, geography, product/service fit, remote-friendliness | Record notes in operator log | Operator-gated |
| 13 | Reconcile any mismatch | If `verify-identity` returns `MISMATCH` / `EMPTY` / `UNREACHABLE` / `QUARANTINED` / `STALE`, stop and investigate | Resolve or discard candidate | Hard gate |

---

## Stage C — Controlled CRM + approval creation

| # | Step | Command | Expected result | Gate |
|---|------|---------|-----------------|------|
| 14 | Write verified opportunity to CRM | `uv run cca prospect --source commissioncrowd --live-shadow --write-crm --create-approvals --limit 1` | 1 lead + 1 opportunity + 1 approval record created | Identity gate must pass |
| 15 | Inspect CRM records | Check Google Sheets `leads`, `opportunities`, `approvals` tabs | Verified candidate appears with lifecycle `staged` or `pending` | Operator verification |
| 16 | Send Telegram approval request | `uv run cca request-approval` | Operator receives inline-keyboard approval message | Operator must tap approve |

---

## Stage D — Operator approval and application submission

| # | Step | Command / Action | Expected result | Gate |
|---|------|------------------|-----------------|------|
| 17 | Operator approves via Telegram | Tap **Approve** on the inline keyboard | Daemon logs `Supervisor checkpoint ok=True` and processes callback | Hard gate — supervisor checkpoint + identity gate |
| 18 | Confirm daemon handled callback | `sudo journalctl -u cca-telegram-bot.service -n 20` | Callback handled, state migrated to `approved` | Verification |
| 19 | Submit approved application | `uv run cca submit-application --opportunity-id <ID>` (dry-run first, then live) | Dry-run: simulated submission; live: form filled and submitted | Both identity gate + approval gate must pass |
| 20 | Confirm lifecycle transition | Check registry / Sheets | State becomes `application_submitted` with timestamp | Verification |
| 21 | Capture confirmation screenshot | Save CommissionCrowd confirmation to `/home/ubuntu/hermes-control/reports/` | Audit trail complete | Best practice |

---

## Stage E — Post-submission

| # | Step | Action | Expected result |
|---|------|--------|-----------------|
| 22 | Notify operator of submission | Telegram confirmation from daemon | Operator receives success message |
| 23 | Sync reports to repo | `python scripts/sync_reports_to_repo.py` | Reports synced to GitHub + Obsidian-ready |
| 24 | Update documentation | Record pilot outcome in `learnings.md` and `docs/known-limitations.md` | Status moves from `NOT_READY_FOR_PRODUCTION` to pilot-tested |
| 25 | Tag release | `git tag v0.1.0-mvp` and push | First pilot milestone tagged |

---

## Abort / rollback checklist

- If the daemon shows `409 Conflict`: ensure only one process polls `@ComCrowdBot`. The Hermes gateway uses `@GEM_OCI_bot`; do not stop it.
- If identity verification blocks a candidate: capture the detail page URL + mismatch reason, update registry to `QUARANTINED`, and move to the next candidate.
- If the submission fails mid-form: check `submission_audit` in registry and retry with `--dry-run` first.
- Never use `git add .` or `git add -A`.

---

## Current blocker

**2026-07-11:** `cca shadow-run` fails with `HTTP 401: Invalid token`. Step 1 (refresh `COMMISSIONCROWD_API_KEY`) must be completed before any Stage A command can run.

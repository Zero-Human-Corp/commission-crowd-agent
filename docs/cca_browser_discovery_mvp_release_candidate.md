# CCA Browser Discovery MVP — Release Candidate Report

**Date:** 2026-06-10  
**Status:** `MVP_CONDITIONALLY_READY`  
**Commit:** (to be inserted after push)  
**Branch:** `master`  

---

## Summary

The authenticated browser discovery pipeline is architecturally complete and safe. All reconciliation, qualification, CRM write, application-pack generation, and approval-creation infrastructure is in place and tested. The pipeline is **conditionally ready** because the most recent CommissionCrowd Find Opportunities extraction returned a 404/error page instead of real results, yielding zero net-new candidates.

---

## Completed functionality

| Component | File | Status |
|-----------|------|--------|
| Authenticated browser adapter | `src/commission_crowd_agent/browser_adapter.py` | ✅ Implemented (Playwright SPA-safe) |
| State registry (lifecycle + precedence) | `src/commission_crowd_agent/state_registry.py` | ✅ Implemented + tested |
| Approval gate (integrity + lifecycle blocking) | `src/commission_crowd_agent/approval_gate.py` | ✅ Hardened |
| Browser discovery script (SPA-safe) | `scripts/browser_discovery_v6.py` | ✅ Runs end-to-end |
| Reconciliation script | `scripts/reconcile_inventory.py` | ✅ Fixed to use unified registry + garbage filtering |
| Unified opportunity state registry output | `cca_opportunity_state_registry.json` | ✅ Generated |
| Reconciliation report | `cca_reconciliation_report.md` | ✅ Generated |

---

## Quality gates

| Gate | Command | Result |
|------|---------|--------|
| Tests | `pytest tests/` | **500 passed in 40.70s** |
| Ruff (src + tests + reconcile script) | `ruff check src/ tests/ scripts/reconcile_inventory.py` | **All checks passed!** |
| MyPy (core modules) | `mypy state_registry.py approval_gate.py` | **Clean** |
| MyPy (browser_adapter.py) | `mypy browser_adapter.py` | 1 pre-existing import-guard type mismatch (`sync_playwright = None`). Safe pattern, documented. |
| Secret scan (changed files) | Custom grep scan | **No secrets found** |

---

## Source counts (authenticated, as of 2026-06-10)

| Source | Count | Protected | IDs |
|--------|-------|-----------|-----|
| My Opportunities | 4 | Yes | `30130` (active), `30754` (paused), `33021` (active), `34234` (active) |
| Applications | 2 | Yes | Awaiting approval (lifecycle_state `application_submitted`) |
| Messages | 0 | — | |
| Invitations | 0 | — | |
| Favourite Opportunities | 0 | — | |
| Find Opportunities | 1 | No | **Garbage/error** (`title="close"`, body contains "404 NOT FOUND") |
| **Net-new candidates** | **0** | — | |
| CRM existing records | 6 | — | From Google Sheets `opportunities` tab |

---

## Safety confirmation

- ✅ No applications submitted
- ✅ No invitations accepted
- ✅ No platform messages sent
- ✅ No external emails sent
- ✅ No Telegram messages sent
- ✅ No operator approvals falsely auto-approved
- ✅ Protected IDs excluded from apply_to_principal queue

---

## Known limitation

### Find Opportunities 404 error page

The latest `browser_discovery_v6.py` run navigated to `#/opportunities/search` and the SPA rendered an error modal with text:

> `Sorry, the server is not responding to that request. Either there's something wrong with the request or there's something wrong with the server. [Code: 404 NOT FOUND]`

This was captured as a pseudo-opportunity card because the generic card-detector matched modal UI elements. The reconciliation script now explicitly filters these entries.

**Impact:** Zero qualified net-new candidates. No application packs. No pending approvals.

---

## Path to full MVP tag (`v0.1.0-mvp`)

The `v0.1.0-mvp` tag **must not be created** until the following promotion criteria are met:

1. A fresh authenticated browser discovery run returns **real** Find Opportunities results ( legitimate opportunity cards with IDs, titles, and commission text), **or** a confirmed legitimate empty search result page without an application error.
2. `scripts/reconcile_inventory.py` is re-run and produces `net_new_count >= 0` with **zero garbage entries**.
3. If `net_new_count > 0`, the full pipeline runs successfully:
   - Qualification scoring
   - CRM write (idempotent — second run must create zero duplicates)
   - Application pack generation (max 3 packs)
   - Pending approval creation (max 2 unless 3 are clearly justified)
4. All quality gates pass (tests, Ruff, MyPy, secret scan).
5. Operator reviews and approves the Telegram digest.

Only then may the tag be created and pushed.

---

## Files changed in this release candidate

### New files
- `scripts/browser_discovery_v6.py`
- `scripts/reconcile_inventory.py`
- `src/commission_crowd_agent/browser_adapter.py`
- `src/commission_crowd_agent/state_registry.py`
- `src/commission_crowd_agent/mvp_reports.py`
- `tests/test_browser_discovery.py`
- `tests/test_canonical.py`
- `tests/test_live_shadow.py`
- `tests/test_mvp_pipeline.py`
- `tests/test_reconciliation_and_invariants.py`
- `docs/commissioncrowd-browser-discovery.md`
- `docs/icon-only-navigation.md`
- `docs/manual-application-workflow.md`
- `docs/mvp-operator-runbook.md`
- `docs/opportunity-lifecycle.md`

### Modified files
- `README.md` — updated with browser discovery section, verified commands, honest status
- `docs/known-limitations.md` — added 404 limitation and conditional-ready verdict
- `src/commission_crowd_agent/approval_gate.py` — hardened with validate_integrity()
- `src/commission_crowd_agent/cli.py` — minor updates
- `src/commission_crowd_agent/mvp_pipeline.py` — minor updates

### Report artifacts (not committed)
- `/home/ubuntu/hermes-control/reports/cca_opportunity_state_registry.json`
- `/home/ubuntu/hermes-control/reports/cca_browser_discovery_summary.json`
- `/home/ubuntu/hermes-control/reports/cca_favourite_opportunities_inventory.json`
- `/home/ubuntu/hermes-control/reports/cca_conversations_inventory.json`
- `/home/ubuntu/hermes-control/reports/cca_find_opportunities_search_log.json`
- `/home/ubuntu/hermes-control/reports/cca_reconciliation_report.md`
- `/home/ubuntu/hermes-control/reports/cca_state_registry.json`
- `/home/ubuntu/hermes-control/reports/cca_net_new_candidates.json`

---

## Next operator action

1. Run a fresh browser discovery when CommissionCrowd is stable:
   ```bash
   cd /home/ubuntu/projects/commission-crowd-agent
   source .venv/bin/activate
   python3 scripts/browser_discovery_v6.py
   ```
2. Inspect the screenshot and `cca_find_opportunities_search_log.json` to confirm real cards were returned.
3. Re-run reconciliation:
   ```bash
   python3 scripts/reconcile_inventory.py
   ```
4. Check `cca_net_new_candidates.json` for `net_new_count > 0`.
5. If candidates exist, proceed to qualification and approval creation.
6. Only then consider creating the `v0.1.0-mvp` tag.

---

**Do not tag `v0.1.0-mvp` yet.**

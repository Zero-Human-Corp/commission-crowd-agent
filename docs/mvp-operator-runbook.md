# CCA MVP — Operator Runbook

## Quick start (verified commands)

All commands assume you are in the repository root with the virtual environment activated.

```bash
cd /home/ubuntu/projects/commission-crowd-agent
source .venv/bin/activate
```

### 1. Browser discovery (authenticated)

Run the latest SPA-safe discovery script:

```bash
cd /home/ubuntu/projects/commission-crowd-agent
source .venv/bin/activate
python3 scripts/browser_discovery_v6.py
```

**What it does:**
- Logs into CommissionCrowd via Playwright
- Extracts My Opportunities, Applications, Favourites, Conversations, and Find Opportunities
- Saves component files and a unified registry to `/home/ubuntu/hermes-control/reports/`

**Expected artifacts:**
- `cca_opportunity_state_registry.json` — unified source of truth
- `cca_favourite_opportunities_inventory.json`
- `cca_conversations_inventory.json`
- `cca_find_opportunities_search_log.json`
- `cca_browser_discovery_reconciliation.md`
- `cca_browser_discovery_summary.json`
- `cca_state_registry.json` (reconciled registry)
- `cca_net_new_candidates.json` (filtered net-new list)
- `cca_reconciliation_report.md`

### 2. Reconcile inventory

```bash
python3 scripts/reconcile_inventory.py
```

**What it does:**
- Loads the unified registry from Step 1
- Loads existing CRM rows from Google Sheets `opportunities` tab
- Builds `OpportunityStateRegistry` with precedence rules
- Filters garbage/error find results
- Outputs:
  - `cca_state_registry.json`
  - `cca_net_new_candidates.json`
  - `cca_reconciliation_report.md`

**Protected IDs (hardcoded by lifecycle state):**
- My Opportunities: `30130`, `30754`, `33021`, `34234`
- Applications: `17763`, `20733` (lifecycle_state `application_submitted`)

These IDs are **excluded** from net-new candidacy and cannot receive `apply_to_principal` approvals.

### 3. Qualify candidates

When real find results are available (current recovery: 20 Find + 40 Featured candidates), run:

```bash
python3 scripts/qualify_candidates.py   # if available
# or via the mvp_pipeline module
```

> **Honest limitation:** The most recent recovery run produced 20 Find candidates from a single `"software"` query. Multi-query runs (`B2B SaaS`, `AI`, etc.) still encounter server errors. The operator may need to run single-query extractions when the platform is stable.

### 4. CRM write (controlled)

Only net-new qualified opportunities are written. The script is idempotent: a second run must produce zero duplicates.

### 5. Approval creation

Pending approvals are created in Google Sheets `approvals` tab with:
- `status = pending`
- `operator_decision` and `decided_at_utc` left blank
- A SHA-256 payload hash over the application pack

**No approval is automatically marked `approved`.** Operator must review and decide.

### 6. Telegram digest

After each run, a digest is prepared (not sent automatically) summarizing counts, pending approvals, and safety confirmations.

## Safety controls (always enforced)

| Action | Automatic? | Notes |
|--------|-----------|-------|
| Application submission | **No** | Blocked by approval gate unless operator approves |
| Invitation acceptance | **No** | Requires explicit operator decision |
| Platform messaging | **No** | Pipeline never sends messages |
| External email | **No** | Pipeline never sends email |
| Telegram send | **No** | Draft prepared; operator must approve send |

## When something goes wrong

| Symptom | Likely cause | Recovery |
|---------|-------------|----------|
| Find Opportunities = 0 or garbage title "close" | SPA served error modal / 404 | Re-run `browser_discovery_v6.py` after a short wait |
| My Opportunities count = 0 | Session expired or login page | Check screenshots in reports dir; re-run discovery |
| Reconciliation crashes | Registry loading from stale `cca_browser_inventory.json` | Confirm `cca_opportunity_state_registry.json` exists and is recent |
| CRM write creates duplicates | Deduplication key missing | Ensure `opportunity_id` is present and stable |

## Lifecycle states

See `docs/opportunity-lifecycle.md` for full definitions.

Quick reference:
- `active` — already in My Opportunities (protected)
- `paused` — inactive but still in My Opportunities (protected)
- `application_submitted` — already applied (protected)
- `discovered` — seen in Find Opportunities, not yet processed
- `application_draft_pending` — pack drafted, awaiting operator approval
- `application_approved` — operator approved, ready for manual submission
- `principal_accepted` — principal accepted agent (terminal)

## Reporting issues

If the browser discovery breaks due to a CommissionCrowd UI redesign:
1. Inspect the screenshot in `/home/ubuntu/hermes-control/reports/`
2. Update the DOM selectors in `src/commission_crowd_agent/browser_adapter.py` or the discovery script
3. Re-run and verify counts match the live dashboard

## Release tag policy

Do **not** create `v0.1.0-mvp` until:
1. A fresh browser discovery run returns **real** Find Opportunities results (or a confirmed legitimate empty state without an error page)
2. Reconciliation produces `net_new_count >= 0` without garbage entries
3. All quality gates pass (tests, Ruff, MyPy, secret scan)
4. The operator confirms the Telegram digest is accurate

Current status: **MVP_RECOVERED** — 20 Find + 40 Featured candidates extracted and reconciled. Multi-query Find Opportunities remains unstable; operator may accept single-query coverage as sufficient.

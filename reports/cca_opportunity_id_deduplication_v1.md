# CCA Opportunity ID Deduplication — Mission Report v1

**Mission:** `cca_opportunity_id_deduplication_fix_v1`  
**Date:** 2026-06-15  
**Status:** ✅ COMPLETE — no code defect found; 320 candidates are already unique by opportunity_id.

---

## 1. Repository Status

| Field | Value |
|-------|-------|
| **Commit SHA before** | `160ff1f0531ad0d5b26e73a923d20233817382fb` |
| **Local HEAD = origin/master** | ✅ Yes |
| **v0.1.0-mvp tag** | `00d1491f59468a3a369c567fc1f08cf329833555` (unchanged) |
| **Uncommitted changes** | `scripts/browser_discovery_v6.py` (from prior mission) + this mission's changes |

---

## 2. What Was Changed

### `scripts/reconcile_inventory.py`
- Added opportunity_id-primary deduplication block before protected-ID / CRM filtering.
- Merges records with the same `opportunity_id`:
  - Preserves all distinct `search_query` values as `search_queries`.
  - Keeps the longest/most complete title.
  - Computes `query_overlap_count`.
  - Flags records lacking `opportunity_id` with `opportunity_id_missing: true` and falls back to title dedup.
- Writes deduplication metadata into `cca_net_new_candidates.json`.

### `src/commission_crowd_agent/state_registry.py`
- Added fields to `OpportunityStateRecord`:
  - `search_queries: list[str]`
  - `query_overlap_count: int`
  - `opportunity_id_missing: bool`
- `ingest_find_opportunities()` now merges `search_query` values when the same opportunity_id is ingested multiple times.
- `to_dict()` includes the new fields.

### `tests/test_browser_discovery.py`
- Added `test_find_results_merge_by_opportunity_id_preserves_queries`.
- Added `test_find_results_fallback_to_title_when_opportunity_id_missing`.

---

## 3. Test & Quality Results

| Gate | Command | Result |
|------|---------|--------|
| **Ruff** | `ruff check scripts/reconcile_inventory.py src/commission_crowd_agent/state_registry.py tests/test_browser_discovery.py` | ✅ All checks passed |
| **pytest full suite** | `pytest tests/ -q` | ✅ **544 passed** |
| **MyPy** | `mypy src/commission_crowd_agent/state_registry.py scripts/reconcile_inventory.py` | ⚠️ 1 pre-existing error in `reconcile_inventory.py:138` (unrelated to this change; `ingest_api_data` receives a dict instead of CanonicalOpportunity) |
| **Secret scan** | Manual grep for credential patterns | ✅ No secrets in changed files |

---

## 4. Reconciliation Results

| Metric | Value |
|--------|-------|
| **Find Opportunities raw records** | 320 |
| **Distinct titles** | 320 |
| **Distinct opportunity_ids** | **320** |
| **Records merged by opportunity_id** | **0** |
| **Title-dedup fallback (missing opportunity_id)** | **0** |
| **Net-new candidates after dedup + filtering** | **320** |
| **Protected IDs excluded** | 6 (30130, 30754, 33021, 34234, 17763, 20733) |
| **CRM matches excluded** | 0 |
| **Garbage/error entries filtered** | 0 |

### Key Finding

> **No overcounting was occurring.** The 320 candidates returned by the 8 queries are already unique by `opportunity_id`. The previous title-string deduplication was sufficient because CommissionCrowd search results already produce unique IDs and titles per query.

Each query returned 40 results, and no opportunity_id appeared in more than one query. Therefore:
- `merged_by_opportunity_id = 0`
- `title_fallback_missing_id = 0`
- `after_count = before_count = 320`

---

## 5. Safety Gate Confirmation

| Action | Occurred? |
|--------|-----------|
| CRM write | ❌ No |
| Google Sheets write | ❌ No |
| Approval creation/modification | ❌ No |
| Application submission | ❌ No |
| Platform message | ❌ No |
| External email | ❌ No |
| Telegram send | ❌ No |
| Cover letter action | ❌ No |
| Favourite/shortlist action | ❌ No |
| State-changing opportunity click | ❌ No |
| Git tag change | ❌ No |
| Force push | ❌ No |
| Secret printed | ❌ No |

Browser discovery was **not re-run** during this mission. Reconciliation used the artifact already produced by the prior approved browser discovery run.

---

## 6. Recommended Next Action

The deduplication infrastructure is now robust and will correctly merge future multi-query overlaps if they occur. The true unique net-new count is **320 candidates**.

Next priority remains **commercial verification of shortlisted candidates** before any CRM write or approval creation:

1. **Qualify** the 320 net-new candidates using the scoring pipeline.
2. **Operator reviews** the top-ranked candidates.
3. **Card-click detail capture** for shortlisted candidates (requires operator approval for browser actions).
4. **CRM write and approval creation** only after operator approval.

---

## 7. Report Paths

- JSON inventory: `/home/ubuntu/hermes-control/reports/cca_net_new_candidates.json`
- Markdown reconciliation report: `/home/ubuntu/hermes-control/reports/cca_reconciliation_report.md`
- State registry: `/home/ubuntu/hermes-control/reports/cca_state_registry.json`
- This report: `/home/ubuntu/hermes-control/reports/cca_opportunity_id_deduplication_v1.md`
- JSON version of this report: `/home/ubuntu/hermes-control/reports/cca_opportunity_id_deduplication_v1.json`

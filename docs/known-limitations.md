# CCA MVP — Known Limitations

**Status:** `MVP_CONDITIONALLY_READY`  
**Last updated:** 2026-06-10

## What works
- Authenticated browser discovery via Playwright (CommissionCrowd SPA)
- My Opportunities, Applications, Favourites, Conversations, Messages extraction
- Reconciliation pipeline with protected-ID logic
- Approval-gate hardening (integrity validation, lifecycle blocking, supersession)
- CRM read and controlled write via Google Sheets

## Current limitation: Find Opportunities
The most recent authenticated Find Opportunities run (browser_discovery_v6.py) returned a **404/error page** instead of real search results. The reconciliation script now filters garbage results (titles like `"close"` or bodies containing `"404 NOT FOUND"`).

**Impact:**
- Net-new candidate count = **0**
- No qualified opportunities to draft
- No pending approvals created
- No applications submitted

## Why this happened
CommissionCrowd’s Ember.js SPA occasionally serves an error modal or stale state when navigating to the search hash (`#/opportunities/search`). The error text was captured as a pseudo-opportunity card because the generic card-detector matched modal UI elements.

## Mitigations already in place
1. `scripts/reconcile_inventory.py` now skips find-items with:
   - empty `opportunity_id`
   - `title` in `{"close", ""}`
   - `"There were errors"` in `full_text`
2. The unified registry (`cca_opportunity_state_registry.json`) remains the single source of truth.
3. No application was submitted, no message sent, no invitation accepted.

## Path to full MVP validation
1. Operator re-runs `python3 scripts/browser_discovery_v6.py` (or `browser_adapter.py` equivalent)
2. Verify Find Opportunities page loads real cards with IDs, titles, commission text
3. Re-run `python3 scripts/reconcile_inventory.py`
4. Confirm `net_new_count > 0`
5. Run qualification, CRM write, approval creation
6. Only then create tag `v0.1.0-mvp`

## Other known limitations
- No automatic application submission (by design; operator approval required)
- No automatic platform messaging (by design)
- No external email sending (by design)
- Browser extraction relies on DOM heuristics and may need selector updates if CommissionCrowd redesigns
- Icon-only top navigation (star, checkmark, calendar, people, document, chat, bell) requires visual confirmation or screenshot analysis because labels are absent from the accessibility tree

## Honest verdict
The pipeline is architecturally complete and safe. It is **conditionally ready** because the last live data feed (Find Opportunities) produced an error page rather than real results. Re-running browser discovery when the platform is stable is the only remaining blocker for a full MVP tag.

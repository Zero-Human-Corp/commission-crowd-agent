# CCA MVP — Known Limitations

**Status:** `MVP_IMPLEMENTATION_COMPLETE` — `BLOCKED_EXTERNAL_DEPENDENCY` — `NOT_READY_FOR_OPERATOR_DECISIONS` — `NOT_READY_FOR_PRODUCTION`  
**Last updated:** 2026-06-10

## What works
- Browser discovery code is complete and tested (reconciliation, scoring, approval gates)
- Approval-gate hardening (integrity validation, lifecycle blocking, supersession)
- CRM read and controlled write via Google Sheets

## Current blocker: CommissionCrowd TLS certificate expired

The CommissionCrowd platform is serving an **expired TLS certificate** for `app.commissioncrowd.com`.

- **Certificate subject:** `CN = *.commissioncrowd.com`
- **Expired on:** Oct 23 23:59:59 2024 GMT
- **Current date:** 2026-06-10 (595 days after expiry)
- **Confirmed by:** OpenSSL (verify code 10), curl (error 60), Python urllib, Node.js, Chromium

**Impact:**
- All authenticated browser navigation is blocked
- My Opportunities, Applications, Messages, Invitations, Favourites, and Find Opportunities discovery are all inaccessible
- No live data feed is available
- Card-click detail capture was not tested because the listing page cannot be reached

## Why this happened
CommissionCrowd has not renewed the TLS certificate for `app.commissioncrowd.com`. This is a **remote platform issue**, not a defect in the CommissionCrowd Browser Adapter.

## What was achieved before the blocker
- Prior authenticated runs successfully extracted:
  - 4 My Opportunities
  - 2 Applications
  - 48 Find Opportunities candidates
  - 0 Messages, 0 Invitations, 0 Favourites
- Reconciliation pipeline correctly identified protected opportunities
- 5 shortlisted candidates were scored (39292, 39452, 15256, 36575, 11419)
- Application packs v3 were generated with corrected claims
- All 5 shortlisted candidates require manual verification of vendor identity, territory, and commercial terms

## Previous limitation (now superseded by TLS blocker)
The most recent authenticated Find Opportunities run before the certificate expiry returned a 404/error page instead of real search results. The reconciliation script now filters garbage results (titles like `"close"` or bodies containing `"404 NOT FOUND"`). This issue is now moot because the entire platform is inaccessible.

## Path to full MVP validation
1. **CommissionCrowd renews the TLS certificate** (or operator confirms the blocker is resolved)
2. Verify TLS using the re-entry checklist (OpenSSL code 0, curl without `--insecure`, etc.)
3. Re-run `python3 scripts/browser_discovery_v6.py`
4. Confirm Find Opportunities loads real cards with IDs, titles, commission text
5. Re-run `python3 scripts/reconcile_inventory.py`
6. Confirm `net_new_count > 0`
7. Run card-click detail capture for shortlisted candidates
8. Operator manually verifies vendor identity and commercial terms for top candidates
9. Run qualification, CRM write, approval creation (with operator approval)
10. Only then create tag `v0.1.0-mvp`

## Other known limitations
- No automatic application submission (by design; operator approval required)
- No automatic platform messaging (by design)
- No external email sending (by design)
- Browser extraction relies on DOM heuristics and may need selector updates if CommissionCrowd redesigns
- Icon-only top navigation (star, checkmark, calendar, people, document, chat, bell) requires visual confirmation or screenshot analysis because labels are absent from the accessibility tree

## Honest verdict
The pipeline code is architecturally complete and safe. It is **not ready for production** because the external platform it depends on (CommissionCrowd) is serving an expired certificate. No operator decision, CRM write, approval creation, or application submission can proceed until the certificate is renewed.

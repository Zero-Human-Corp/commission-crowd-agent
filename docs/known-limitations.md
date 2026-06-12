# CCA MVP — Known Limitations

**Status:** `MVP_IMPLEMENTATION_COMPLETE` — `BLOCKED_EXTERNAL_DEPENDENCY` — `NOT_READY_FOR_OPERATOR_DECISIONS` — `NOT_READY_FOR_PRODUCTION`  
**Last updated:** 2026-06-10

## What works
- Browser discovery code is complete and tested (reconciliation, scoring, approval gates)
- Approval-gate hardening (integrity validation, lifecycle blocking, supersession)
- CRM read and controlled write via Google Sheets

## Current blocker: CommissionCrowd TLS certificate expired (app.commissioncrowd.com)

**Update 2026-06-12:** The CommissionCrowd browser adapter in `src/commission_crowd_agent/browser_adapter.py` uses the correct canonical URL `https://www.commissioncrowd.com` and its SPA routes. The previous TLS blocker record identified an **incorrect host** (`app.commissioncrowd.com`) which was **not used by any runtime code**. The correct host (`www.commissioncrowd.com`) serves a valid Let's Encrypt certificate (expires Aug 19 2026). Authenticated browser navigation to the dashboard has been confirmed working.

**Previous finding (superseded):** The TLS diagnostic and card-click blocker reported `app.commissioncrowd.com` as expired. This hostname does not appear in any browser discovery script or the browser adapter. It was tested diagnostically but was never the configured application URL.

**Current status:** Read-only authenticated navigation is now possible. The remaining blocker is commercial verification of shortlisted candidates, not infrastructure.

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

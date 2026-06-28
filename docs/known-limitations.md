# CCA MVP — Known Limitations

**Status:** `MVP_IMPLEMENTATION_COMPLETE` — `DEPENDENCY_HEALTHY` — `NOT_READY_FOR_OPERATOR_DECISIONS` — `NOT_READY_FOR_PRODUCTION`  
**Last updated:** 2026-06-28

## What works
- Browser discovery code is complete and tested (reconciliation, scoring, approval gates)
- Approval-gate hardening (integrity validation, lifecycle blocking, supersession)
- CRM read and controlled write via Google Sheets
- Authenticated read-only navigation on CommissionCrowd (`https://www.commissioncrowd.com`, valid Let's Encrypt certificate)

## Previous blocker (superseded)

A TLS diagnostic on **2026-06-10** reported `app.commissioncrowd.com` as expired. That hostname was **never configured in any runtime code** — it was tested diagnostically but the browser adapter always used `https://www.commissioncrowd.com`, which serves a valid certificate (expires Aug 19 2026).

See `/home/ubuntu/hermes-control/reports/cca_external_dependency_blocker_2026-06-10.md` for the historical audit. That report's wrong-host conclusion is **superseded** by the findings documented here and in `cca_correct_app_base_url_v1.md`.

## Current blocker: candidate identity and commercial-detail reconciliation

Authenticated navigation is working. The remaining blocker is **commercial verification of shortlisted candidates**, not infrastructure. Prior runs identified 48 net-new Find Opportunities candidates and 5 shortlisted prospects, but none have verified commercial details. Candidate IDs and titles require deterministic reconciliation before any CRM write or approval.

## Path to full MVP validation
1. Re-run `python3 scripts/browser_discovery_v6.py` and confirm real cards load
2. Run `python3 scripts/reconcile_inventory.py` and confirm `net_new_count >= 0` with zero garbage entries
3. Run card-click detail capture for shortlisted candidates
4. Operator manually verifies vendor identity and commercial terms for top candidates
5. Run qualification, CRM write, approval creation (with operator approval)
6. Only then create tag `v0.1.0-mvp`

## Other known limitations
- No automatic application submission (by design; operator approval required)
- No automatic platform messaging (by design)
- No external email sending (by design)
- Browser extraction relies on DOM heuristics and may need selector updates if CommissionCrowd redesigns
- Icon-only top navigation (star, checkmark, calendar, people, document, chat, bell) requires visual confirmation or screenshot analysis because labels are absent from the accessibility tree

## Honest verdict
The pipeline code is architecturally complete and safe. Authenticated navigation is possible. It is **not ready for production** because shortlisted candidates lack verified commercial details and deterministic identity reconciliation. No operator decision, CRM write, approval creation, or application submission can proceed until candidate identity and commercial terms are confirmed.

# Supervisor Overall Goal — Syntaxis Labs Commission-Only Sales Agency

## Business Objective

Build a **commission-only sales agency** for **Syntaxis Labs** that:

1. **Sources** high-fit commission-only opportunities from CommissionCrowd and similar platforms.
2. **Researches** each opportunity using public read-only data.
3. **Scores** fit against Syntaxis Labs' capabilities, territory, and preferences.
4. **Prepares** application materials (drafts, packs, profiles) for operator review.
5. **Submits** applications to represent approved vendors — only after explicit operator approval.
6. **Builds ICP campaigns** after vendor acceptance — lead sourcing, buyer outreach, qualification.
7. **Tracks** commission revenue from closed deals through the CRM.

## Role Definition

**Syntaxis Labs acts as an independent commission-only sales partner / middleman.**

- **Principal:** The vendor (e.g., RiverForest RPO) listed on CommissionCrowd.
- **Customer:** The vendor's ICP — companies that need the vendor's product/service.
- **Revenue:** Commission earned from closed deals (typically 10–30%).
- **North Star:** Get accepted by high-fit vendors, then sell their offering to qualified ICP leads using compliant, trackable, approval-gated outreach.

## Source Platforms (Ordered)

1. **CommissionCrowd** (primary, immediate)
2. Other commission-only / partner platforms (future expansion)

## Workflow Stages

| Stage | Code Component | Approval Gate Required |
|-------|---------------|----------------------|
| 1. Source opportunities | `lead_ingestion.py`, `directory_extractor.py` | None (automated) |
| 2. Research opportunity | `deeper_research.py` | `research_scoring` |
| 3. Score rep fit | `lead_scoring.py` | `research_scoring` (same gate) |
| 4. Operator approval to prepare | CRM manual review | `apply_to_principal` or `outreach_draft` |
| 5. Application draft | `workflow_runner.py`, `supervisor_relay.py` | None (prep only) |
| 6. Supervisor review | `supervisor_relay.py` (DRAFT_REVIEW) | None (automated review) |
| 7. Operator approval to submit | CRM manual review | `submit_application_review` |
| 8. Manual or assisted submission | CLI / browser automation | `submit_application_review` |
| 9. Vendor response tracking | CRM status updates | None (monitoring) |
| 10. Accepted or rejected | CRM status updates | None (outcome) |
| 11. Build ICP campaign | `workflows/outreach.py` | `outreach_draft` |
| 12. Lead sourcing | `deeper_research.py` (ICP mode) | `outreach_draft` |
| 13. Buyer outreach draft | `workflow_runner.py` | `outreach_draft` |
| 14. Operator approval to send | CRM manual review | `outreach_send` |
| 15. Send or manual send | `adapters.py` (SMTP) | `outreach_send` |
| 16. Reply tracking | CRM + Telegram | None (monitoring) |
| 17. Qualification | Operator judgment | None (human) |
| 18. Vendor handoff | CRM status update | None (human) |
| 19. Commission tracking | CRM + Google Sheets | None (reporting) |

## Non-Negotiable Governance

1. **Google Sheet CRM is the source of truth.** No approval exists unless visible in the Sheet.
2. **Every review-required JSON must have a human-readable Markdown file.**
3. **No login without explicit operator approval.**
4. **No application submission without explicit operator approval.**
5. **No outreach send without explicit operator approval.**
6. **No messaging companies or buyers without explicit operator approval.**
7. **No external API use without explicit operator approval.**
8. **No credentials printed.**
9. **No secrets committed.**
10. **Supervisor must block Hermes if it tries to skip gates.**
11. **Supervisor must identify stale approvals and prevent acting on superseded gates.**

## Success Metrics

| Metric | Target | Timeline |
|--------|--------|----------|
| CommissionCrowd profile completion | 100% | Immediate |
| Opportunity preferences in scoring rules | Encoded | Immediate |
| High-fit opportunities ranked | ≥ 10 | 2 weeks |
| Application templates reusable | Stored in `/templates/` | 1 week |
| Vendor applications submitted | ≥ 1 after approval | 2 weeks |
| Syntaxis Labs portfolio website | Live or previewable | 1 month |
| Obsidian/OMI knowledge base | Captures decisions, templates, profiles, vendors, ICPs, playbooks | Ongoing |
| Cross-device sync (OCI, MacBook, HP t640) | All shared resources connected | Ongoing |

## Hard Constraints for All Missions

- Do not print secrets.
- Do not commit credentials.
- Do not submit applications without `submit_application_review` approval.
- Do not send outreach without `outreach_send` approval.
- Do not message companies or buyers without explicit approval.
- Do not use CommissionCrowd API/login without a separate approved gate.
- Do not change approval statuses except through approved CRM workflows.
- Do not treat local JSON as source of truth.
- Do not bypass SupervisorRelay.

## Current Active Pipeline

| Entity | Stage | Approval | Status |
|--------|-------|----------|--------|
| RiverForest RPO Opportunity | Pack prepared, pending submission | `d9f3e2a1` | `submit_application_review` — **pending** |

---

*Installed: 2026-05-28*  
*Operator: Syntaxis Labs*  
*Project: commission-crowd-agent*  
*Repository: /home/ubuntu/projects/commission-crowd-agent*

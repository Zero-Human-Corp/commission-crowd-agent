**Implementation Plan (Refreshed)**  
**CommissionCrowd Invisible Agent – MVP**

**Version:** 2.0  
**Date:** June 27, 2026  
**Approach:** Spec-driven development using **AGENTOS** + **Hermes Agent** + **Python CLI**  
**Primary LLM:** Kimi-k2.6 / Kimi-k2.7 (Ollama.com Cloud)  
**Core Tools:** Python 3.11, pytest, Playwright, Telegram, Google Sheets, Hermes hooks, ruff, mypy
**Legacy Reference:** n8n remains available on OCI `:5678` but is **read-only/legacy only** (see ADR-001 and Section 9 below).

---

### 1. Overview

This plan reflects the **actual implementation path taken** for the CommissionCrowd Agent MVP. The original 30-day plan assumed n8n as the primary engine; that has been superseded by a **Git-controlled, testable Python workflow layer** triggered by **Hermes hooks** (see `docs/decisions/ADR-001-replace-n8n-primary-workflows-with-hermes-hooks.md`).

The current system can:
- Authenticate to CommissionCrowd via Playwright and extract live account state
- Reconcile browser-discovered opportunities against the CRM
- Score leads for rep-fit as an independent commission-only sales rep
- Generate application-to-principal drafts
- Gate every CRM write and application submission through an approval gate
- Request and receive operator approvals via Telegram inline-keyboard callbacks
- Submit applications automatically after approval (controlled-write MVP)

**Development Philosophy:**
- Follow **AGENTOS** for spec-driven development
- Use **Graphify** for architecture visualization (optional/backlog)
- Use **code-review-graph** for workflow quality checks (optional/backlog)
- Apply clean principles inspired by **GSTACK**
- Prefer **testable Python code** over opaque n8n JSON workflows

---

### 2. High-Level Timeline

| Phase | Focus                              | Duration     | Key Deliverable                                  | Status        |
|-------|------------------------------------|--------------|--------------------------------------------------|---------------|
| 0     | Foundation & Hermes Migration      | Days 1–5     | Git scaffold + Python CLI + Hermes hooks         | Complete      |
| 1     | Browser Discovery & Reconciliation  | Days 6–12    | Playwright SPA adapter + source-of-truth registry| Complete      |
| 2     | Scoring & Approval Gate             | Days 13–17   | Rep-fit scoring + lifecycle state machine        | Complete      |
| 3     | Telegram Approvals & Controlled-Write MVP | Days 18–22 | Inline-keyboard approvals + application submission engine | Complete |
| 4     | Testing, Hardening & Documentation  | Days 23–27   | 575 tests, ruff clean, operator runbooks, ADRs   | Complete      |
| 5     | Identity/Commercial Verification & Pilot | Days 28+ | Verified candidates + first live client use   | Outstanding   |

---

### 3. Detailed Implementation Plan

#### **Phase 0: Foundation & Hermes Migration (Days 1–5)**

**Objective:** Replace the n8n-first foundation with a Git-controlled Python runtime and Hermes hook layer.

**Tasks:**
- Provision Oracle Cloud Always Free Ampere instance (existing; n8n kept as read-only reference)
- Create project folder structure and Git repository
- Set up Python 3.11 virtual environment, `pyproject.toml`, and dev tooling (ruff, mypy, pytest)
- Create Telegram bot via @BotFather and configure it for Python/Hermes (not n8n)
- Create initial Google Sheets templates (`Leads` + `Config`)
- Implement Pydantic Settings + safe shared secrets loader (`/home/ubuntu/hermes-control/secrets/shared.env`)
- Build Hermes hook scripts under `scripts/hooks/` that wrap the `cca` CLI
- Document the n8n-to-Hermes decision in `docs/decisions/ADR-001-*.md`

**Deliverables:**
- Initialized project folder with recommended structure
- `cca` CLI runnable with `--dry-run` flags
- Hermes hooks able to trigger Python workflows
- All base credentials loaded from shared secrets (no repo-local secrets)

**Tools:** OCI Console, Git, Python 3.11, pip, Hermes Agent

---

#### **Phase 1: Browser Discovery & CRM Reconciliation (Days 6–12)**

**Objective:** Extract live opportunity state from CommissionCrowd and reconcile it against the CRM to identify net-new, protected, and duplicate candidates.

**Tasks:**
- Build Playwright SPA browser adapter (`browser_adapter.py`) that handles icon-only navigation and dynamic loading
- Authenticate to CommissionCrowd and capture dashboard state
- Extract `My Opportunities`, `Applications`, `Messages`, `Invitations`, `Favourite Opportunities`, and `Find Opportunities`
- Implement source-of-truth hierarchy (account state > CRM > API enrichment)
- Build reconciliation script (`reconcile_inventory.py`) and registry (`state_registry.py`)
- Define protected-opportunity rules (active/paused engagements, pending applications)
- Filter garbage/error pages from `Find Opportunities`
- Persist outputs to `/home/ubuntu/hermes-control/reports/`

**Deliverables:**
- Authenticated browser discovery pipeline
- Unified `cca_opportunity_state_registry.json`
- Reconciliation report (`cca_reconciliation_report.md`)
- Identified net-new candidates protected from duplicates

**Milestone:** Operator can run `python3 scripts/browser_discovery_v6.py` and `python3 scripts/reconcile_inventory.py` safely.

**Tools:** Playwright, Python, JSON/Markdown reports, Hermes hooks

---

#### **Phase 2: Scoring & Approval Gate (Days 13–17)**

**Objective:** Score net-new opportunities for rep-fit and implement a lifecycle/approval gate that prevents unsafe CRM writes.

**Tasks:**
- Define rep-fit scoring rubric (minimum deal-size thresholds, industry fit, geography, remote-friendliness)
- Implement **Researcher**, **Writer**, and **Scorer** agents as Python modules
- Build opportunity lifecycle state machine (`sourced` → `researched` → `rep-fit scored` → `application draft created` → `application approved` → `application submitted` → `accepted`/`rejected`)
- Implement `approval_gate.py` with integrity checks and daily/batch limits
- Add approval taxonomy: `research_scoring`, `deeper_research`, `apply_to_principal`, `application_submitted`, `icp_campaign_draft`, `icp_campaign_send`
- Add dry-run guards on every write path
- Add basic error handling and structured logging

**Deliverables:**
- Rep-fit scoring pipeline
- Lifecycle state registry
- Approval gate with validation and limit enforcement
- Tested agent prompts

**Milestone:** Operator can run `cca run-research-cycle --dry-run` and `cca score-opportunities --dry-run` safely.

---

#### **Phase 3: Telegram Approvals & Controlled-Write MVP (Days 18–22)**

**Objective:** Replace n8n command triggers and Gmail/SMTP sending with a Hermes-managed, inline-keyboard approval flow and a controlled application-submission engine.

**Tasks:**
- Build Telegram inline-keyboard approval request generation (`cca request-approval --dry-run`)
- Implement persistent approval callback worker (daemon) that receives operator decisions
- Add Playwright shadow-DOM validation to confirm approval state before writes
- Implement controlled-write MVP: only apply to a principal after explicit operator approval
- Build automated application submission engine that fills CommissionCrowd application forms
- Update lifecycle status to `application_submitted` + timestamp after submission
- Send Telegram confirmation after each approval/submission action
- Enforce daily volume and batch limits from config
- Improve error handling, logging, and audit trail

**Deliverables:**
- Telegram inline-keyboard approval daemon
- Controlled application submission engine
- End-to-end flow: Research → Score → Draft → Approve → Submit
- Audit trail in state registry and reports

**Milestone:** Operator receives a Telegram approval request, clicks approve, and the system submits the application safely.

---

#### **Phase 4: Testing, Hardening & Documentation (Days 23–27)**

**Objective:** Make the Python workflow layer reliable and document it for operator use.

**Tasks:**
- Perform end-to-end testing with real (anonymized) data via pytest and dry runs
- Test error scenarios and recovery paths
- Improve idempotency of workflows (dry-run guards, registry deduplication)
- Add structured logging and `data/runs/` output
- Refine Telegram notifications and approval messages
- Create Operator Runbook (`docs/mvp-operator-runbook.md`)
- Write architecture decision records (ADRs) and update implementation plan
- Run ruff, mypy, and pytest in `./scripts/dev_check.sh`
- Keep n8n instance as read-only reference; do not export new JSON workflows

**Deliverables:**
- Stable MVP with 575 passing tests
- Operator runbooks and ADRs
- Ruff-clean, type-checked Python codebase
- Refreshed documentation set

---

#### **Phase 5: Identity/Commercial Verification & Pilot (Days 28+)**

**Objective:** Close the candidate identity and commercial verification gaps so the system can be used with a real client.

**Tasks:**
- Reconcile candidate identity across CommissionCrowd detail pages, public web signals, and CRM records
- Verify commercial details (company name, industry, products/services, compensation structure, geography) before any application
- Onboard 1 pilot client using the onboarding flow once verification is reliable
- Run the full system for 3–5 days with operator supervision
- Collect feedback on draft quality and usability
- Fix critical issues discovered during pilot
- Refine prompts based on real output quality
- Document lessons learned
- Prepare system for additional clients

**Deliverables:**
- Verified net-new candidates with commercial signals
- Working system used with at least one client/pilot
- Improved prompts and workflows
- Readiness for paid client work

**Blocker:** No CRM write, approval, or application can be made until candidate identity/commercial verification is complete.

---

### 4. Development Workflow (Ongoing)

1. **Define/Update Spec** → Use **AGENTOS**
2. **Visualize** → Use **Graphify** (optional/backlog)
3. **Build/Modify** → Python modules + Hermes hook scripts
4. **Review** → Pull request + pytest + ruff + mypy (code-review-graph optional)
5. **Test** → Unit tests + dry-run CLI commands + manual sample data
6. **Document** → Update relevant docs

---

### 5. Key Milestones

| Milestone | Target Date | Success Criteria |
|---------|-------------|------------------|
| Environment Ready | Day 5 | Python CLI + Hermes hooks runnable; n8n read-only |
| Browser Discovery Working | Day 12 | Playwright extracts authenticated CommissionCrowd state |
| Reconciliation & Scoring Working | Day 17 | Registry identifies net-new, protected, scored candidates |
| Approval Gate & Telegram Approvals | Day 22 | Operator can approve/submit via inline-keyboard with dry-run guards |
| MVP Stable | Day 27 | 575 tests pass; ruff/mypy clean; runbooks finalized |
| Pilot Ready | Day 30+ | Candidate identity/commercial verification gap closed; first client onboarded |

---

### 6. Resource Requirements

- **Time Commitment:** 2–4 hours per day (higher during verification/pilot)
- **Primary Tools:**
  - Hermes Agent (for generating Python modules and prompts)
  - AGENTOS (for specifications)
  - Graphify + code-review-graph (optional/backlog)
  - pytest + ruff + mypy
- **Accounts Needed:**
  - Oracle Cloud (Free Tier)
  - Ollama.com Cloud subscription
  - Google Workspace
  - Telegram Bot
  - CommissionCrowd account

---

### 7. Risks & Mitigations

| Risk                              | Likelihood | Impact | Mitigation |
|-----------------------------------|------------|--------|----------|
| LLM output quality inconsistent   | High       | High   | Strong prompting + human review + iteration |
| Python workflow complexity grows  | Medium     | Medium | Modular modules under `src/workflows/` + tests |
| CommissionCrowd UI changes      | Medium     | High   | Playwright selectors + recovery runbook |
| Candidate identity/commercial verification gaps | High | High | Manual verification workflow; block writes until confirmed |
| Google Sheets limitations         | Medium     | Low    | Keep data volume reasonable in MVP |
| Operator learning curve           | Medium     | Medium | Follow clear runbooks and documentation |
| Telegram approval reliability   | Low        | Medium | Shadow validation + dry-run guards + daemon retry |

---

### 8. Success Criteria for MVP

By Day 30, the system should:
- Authenticate to CommissionCrowd and extract live opportunity state
- Reconcile browser-discovered opportunities against the CRM without duplicates
- Score leads for rep-fit and generate application-to-principal drafts
- Gate every CRM write and application submission through `approval_gate.py`
- Request and receive operator approvals via Telegram inline-keyboard callbacks
- Submit approved applications automatically (controlled-write MVP)
- Provide clear status tracking, audit trail, and notifications
- Be stable enough for pilot client use after identity/commercial verification

---

This refreshed plan reflects the actual implementation path from a legacy n8n-first design to a Hermes-driven, testable Python MVP.

---

### 9. n8n Legacy / Reference Only

n8n was the originally planned primary workflow engine. It remains running on OCI (`:5678`) as a **read-only reference** and is no longer the source of truth for new development.

| Aspect | Legacy (n8n) | Current (Hermes Hooks + Python CLI) |
|--------|--------------|-------------------------------------|
| Orchestration | n8n workflow JSONs | `src/commission_crowd_agent/workflows/*.py` |
| Trigger | n8n Schedule / Telegram nodes | Hermes hook scripts under `scripts/hooks/` |
| Configuration | n8n Credential Store | Pydantic Settings + shared secrets |
| Testing | Manual n8n runs | pytest + dry-run flags |
| Version Control | Exported JSON blobs | Source code + tests |
| Observability | n8n execution log | Hermes reports + `data/runs/` logs |
| Approval | Google Sheets checkbox | Telegram inline-keyboard approval daemon |

No new n8n workflows are created for the MVP. Legacy n8n exports and documentation are preserved under `docs/legacy/n8n/` for reference only.

---

Would you like me to expand Phase 5 (verification/pilot) into more detailed daily tasks, or create a **Verification Checklist** to unblock operator decisions?
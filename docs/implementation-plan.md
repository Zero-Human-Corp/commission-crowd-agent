**Initial Implementation Plan**  
**CommissionCrowd Invisible Agent – MVP**

**Version:** 1.0  
**Date:** May 21, 2026  
**Approach:** Spec-driven development using **AGENTOS** + **Hermes Agent**  
**Primary LLM:** Kimi-k2.6 (Ollama.com Cloud)  
**Core Tools:** n8n, Google Sheets, Telegram, Graphify, code-review-graph

---

### 1. Overview

This plan outlines a **30-day phased implementation** to build a functional MVP of the CommissionCrowd Invisible Agent. The approach is **spec-driven** and leverages AI agents (especially Hermes) heavily, since the operator has limited coding experience.

The goal is to deliver a working system that can:
- Research leads and generate personalized email drafts
- Allow review and approval via Google Sheets + Telegram
- Send approved emails reliably

**Development Philosophy:**
- Follow **AGENTOS** for spec-driven development
- Use **Graphify** for architecture visualization
- Use **code-review-graph** for workflow quality checks
- Apply clean principles inspired by **GSTACK**

---

### 2. High-Level Timeline

| Phase | Focus                              | Duration     | Key Deliverable                          | Status     |
|-------|------------------------------------|--------------|------------------------------------------|------------|
| 0     | Foundation & Environment           | Days 1–3     | Working n8n on OCI + Project Scaffold    | Setup      |
| 1     | Specifications & Architecture      | Days 4–7     | Complete specs + Visual diagrams         | Planning   |
| 2     | Research & Draft Workflow          | Days 8–14    | Working Research + Draft automation      | Core Build |
| 3     | Approval & Sending Workflow        | Days 15–20   | Full end-to-end flow (Approve → Send)    | Core Build |
| 4     | Testing, Hardening & Polish        | Days 21–25   | Stable, documented MVP                   | Quality    |
| 5     | Pilot & First Client Onboarding    | Days 26–30   | Ready for real client use                | Validation |

---

### 3. Detailed Implementation Plan

#### **Phase 0: Foundation & Environment Setup (Days 1–3)**

**Objective:** Set up the development and runtime environment.

**Tasks:**
- Provision Oracle Cloud Always Free Ampere instance
- Install Docker and deploy n8n via Docker Compose
- Enable Basic Auth on n8n
- Create project folder structure on local machine + OCI
- Set up version control (Git) for workflow exports
- Create Telegram bot via @BotFather
- Create initial Google Sheets templates (`Leads` + `Config`)
- Configure n8n credentials (Google Sheets, Telegram, Ollama.com Cloud)

**Deliverables:**
- Working n8n instance accessible via browser
- Initialized project folder with recommended structure
- All base credentials configured in n8n

**Tools:** OCI Console, Docker, Git

---

#### **Phase 1: Specifications & Architecture (Days 4–7)**

**Objective:** Create clear specifications before building.

**Tasks:**
- Use **AGENTOS** to formalize Product Requirements and User Stories
- Refine the existing PRD and SRS documents
- Create architecture diagrams using **Graphify**
- Generate workflow dependency graphs using **code-review-graph**
- Define exact column structure for Google Sheets
- Write detailed system prompts for the three micro-agents (Researcher, Writer, Scorer)
- Define status machine and approval rules

**Deliverables:**
- Updated PRD + SRS
- Architecture diagrams (Graphify)
- Micro-agent prompts (stored in `/prompts`)
- Finalized Google Sheets template structure

**Tools:** AGENTOS, Graphify, code-review-graph, Hermes Agent

---

#### **Phase 2: Research & Draft Workflow (Days 8–14)**

**Objective:** Build the automated research and email drafting capability.

**Tasks:**
- Build `CC_Research_Draft_Main` workflow in n8n
- Implement Google Sheets read/write nodes
- Create and integrate **Researcher Agent** prompt (Kimi-k2.6)
- Create and integrate **Writer Agent** prompt
- Create and integrate **Scorer Agent** (optional but recommended)
- Add status updates (`New` → `Researching` → `Draft Ready`)
- Implement batch processing with limits
- Add Telegram notification when drafts are ready
- Add basic error handling

**Deliverables:**
- Functional Research & Draft workflow
- Tested micro-agent prompts
- Working Telegram notification on draft completion

**Milestone:** Operator can add leads → Run workflow → Receive drafts in Google Sheets

---

#### **Phase 3: Approval & Sending Workflow (Days 15–20)**

**Objective:** Complete the human-in-the-loop sending capability.

**Tasks:**
- Build `CC_Approve_Send_Main` workflow
- Implement Telegram Trigger node for commands (`/approve`, `/send pending`)
- Add logic to read only rows where `Approved = TRUE`
- Integrate Gmail OAuth or SMTP node for sending
- Update status to `Sent` + populate `Sent Timestamp`
- Send Telegram confirmation after sending
- Implement daily volume limit check from Config sheet
- Improve error handling and logging
- Connect both main workflows with shared logic (using sub-workflows)

**Deliverables:**
- End-to-end working flow (Research → Review → Approve → Send)
- Telegram command handling
- Proper status tracking and audit trail

**Milestone:** Operator can review drafts → Approve via checkbox → Trigger sending via Telegram

---

#### **Phase 4: Testing, Hardening & Polish (Days 21–25)**

**Objective:** Make the system reliable and production-ready for pilot use.

**Tasks:**
- Perform end-to-end testing with real (anonymized) data
- Test error scenarios and recovery
- Improve idempotency of workflows
- Add better logging and RunLog sheet (optional)
- Refine Telegram commands and notifications
- Create basic Operator Runbook
- Export all workflows as JSON for backup
- Run **code-review-graph** on final workflows
- Update all documentation

**Deliverables:**
- Stable MVP
- Operator Runbook
- Backup of all workflows
- Finalized documentation set

---

#### **Phase 5: Pilot & First Client Onboarding (Days 26–30)**

**Objective:** Validate the system with a real (or test) client.

**Tasks:**
- Onboard 1 pilot client using the onboarding flow
- Run the full system for 3–5 days
- Collect feedback on draft quality and usability
- Fix critical issues discovered during pilot
- Refine prompts based on real output quality
- Document lessons learned
- Prepare system for additional clients

**Deliverables:**
- Working system used with at least one client/pilot
- Improved prompts and workflows
- Readiness for paid client work

---

### 4. Development Workflow (Ongoing)

1. **Define/Update Spec** → Use **AGENTOS**
2. **Visualize** → Use **Graphify**
3. **Build/Modify** → n8n workflows + Hermes Agent
4. **Review** → Use **code-review-graph**
5. **Test** → Manual + sample data
6. **Document** → Update relevant docs

---

### 5. Key Milestones

| Milestone | Target Date | Success Criteria |
|---------|-------------|------------------|
| Environment Ready | Day 3 | n8n running on OCI + credentials configured |
| Specs Complete | Day 7 | PRD, SRS, prompts, and diagrams finalized |
| Research & Draft Working | Day 14 | Can generate drafts from new leads |
| Full End-to-End Flow | Day 20 | Can approve and send emails via Telegram |
| MVP Stable | Day 25 | System runs reliably with error handling |
| Pilot Complete | Day 30 | Used successfully with at least one client |

---

### 6. Resource Requirements

- **Time Commitment:** 2–4 hours per day (higher in first 2 weeks)
- **Primary Tools:**
  - Hermes Agent (for generating n8n workflows and prompts)
  - AGENTOS (for specifications)
  - Graphify + code-review-graph
- **Accounts Needed:**
  - Oracle Cloud (Free Tier)
  - Ollama.com Cloud subscription
  - Google Workspace
  - Telegram Bot

---

### 7. Risks & Mitigations

| Risk                              | Likelihood | Impact | Mitigation |
|-----------------------------------|------------|--------|----------|
| LLM output quality inconsistent   | High       | High   | Strong prompting + human review + iteration |
| n8n workflow complexity grows     | Medium     | Medium | Use sub-workflows and modular design |
| Google Sheets limitations         | Medium     | Low    | Keep data volume reasonable in MVP |
| Operator learning curve           | Medium     | Medium | Follow clear runbooks and documentation |
| Telegram command reliability      | Low        | Medium | Test thoroughly in Phase 3 |

---

### 8. Success Criteria for MVP

By Day 30, the system should:
- Allow adding leads to Google Sheets
- Automatically research and generate personalized drafts
- Enable review and approval via Google Sheets + Telegram
- Send approved emails reliably
- Provide clear status tracking and notifications
- Be stable enough for pilot client use

---

This **Initial Implementation Plan** gives you a clear, realistic 30-day roadmap to go from zero to a working MVP.

Would you like me to expand any phase into more detailed daily tasks, or create a **Phase 0–1 Execution Checklist** to get started immediately?
**Task List: CommissionCrowd Invisible Agent – MVP**

**Generated using Task Master methodology**  
**Based on:** PRD, SRS, App Flow, Backend Structure, Tech Stack, and Implementation Plan  
**Date:** June 27, 2026 (refreshed)  
**Approach:** Spec-driven development with AGENTOS + Hermes Agent + Python CLI

---

### Task List Overview

| Task ID | Task Name | Priority | Dependencies | Status | Notes |
|---------|-----------|----------|--------------|--------|-------|
| **T-001** | Provision OCI Always Free instance and install n8n | High | None | **Superseded (n8n)** | OCI instance provisioned; n8n remains on `:5678` as read-only reference only. Primary engine is Python CLI + Hermes hooks. |
| **T-002** | Set up project folder structure and Git repository | High | None | **Done/Complete** | - |
| **T-003** | Create Telegram bot and configure in n8n | High | T-001 | **Superseded (n8n)** | Telegram bot configured for Python/Hermes; inline-keyboard approval daemon implemented. |
| **T-004** | Configure base credentials in n8n (Google, Telegram, Ollama) | High | T-001 | **Superseded (n8n)** | Credentials managed via Pydantic Settings + `/home/ubuntu/hermes-control/secrets/shared.env`. |
| **T-005** | Create Google Sheets templates (Leads + Config) | High | None | **Done/Complete** | - |
| **T-006** | Define final Google Sheets column structure | High | T-005 | **Done/Complete** | - |
| **T-007** | Use AGENTOS to formalize PRD and User Stories | High | None | **Done/Complete** | Specs live in `specs/`. |
| **T-008** | Create detailed system prompts for micro-agents | High | T-007 | **Done/Complete** | Researcher, Writer/Scorer prompts in `specs/` and `src/commission_crowd_agent/`. |
| **T-009** | Generate architecture diagrams using Graphify | Medium | T-007 | **Backlog** | Optional visual refresh. |
| **T-010** | Create workflow dependency graph using code-review-graph | Medium | T-009 | **Backlog** | Optional; code is source-controlled and tested. |
| **T-011** | Build `CC_Research_Draft_Main` workflow skeleton | High | T-001, T-006 | **Superseded (n8n)** | Replaced by Python workflow modules under `src/commission_crowd_agent/workflows/`. |
| **T-012** | Implement Google Sheets read/write nodes | High | T-011 | **Superseded (n8n)** | Replaced by `SourceAdapter`/Sheets CLI (`cca sheets-*`). |
| **T-013** | Implement Researcher Micro-Agent (Kimi-k2.6) | High | T-008, T-011 | **Done/Complete** | Browser discovery + public research pipeline operational. |
| **T-014** | Implement Writer Micro-Agent | High | T-013 | **Done/Complete** | Application-to-principal drafts; buyer-outreach writer remains gated until vendor acceptance. |
| **T-015** | Implement Scorer Micro-Agent (optional) | Medium | T-014 | **Done/Complete** | Rep-fit scoring implemented. |
| **T-016** | Add status machine logic (New → Researching → Draft Ready) | High | T-012 | **Done/Complete** | Full opportunity lifecycle state machine in `state_registry.py`. |
| **T-017** | Add batch processing with limits | Medium | T-016 | **Done/Complete** | Config-driven batch limits enforced. |
| **T-018** | Add Telegram notification after draft generation | High | T-003, T-016 | **Done/Complete** | Telegram notifier + approval request messages. |
| **T-019** | Add basic error handling to Research workflow | High | T-016 | **Done/Complete** | Error handling + approval gate + dry-run guards. |
| **T-020** | Build `CC_Approve_Send_Main` workflow skeleton | High | T-011 | **Superseded (n8n)** | Replaced by `approval_gate.py` + Telegram inline-keyboard approvals. |
| **T-021** | Implement Telegram Trigger for commands | High | T-003, T-020 | **Superseded (n8n)** | Hermes hook + inline-keyboard flow replaces n8n command triggers. |
| **T-022** | Add logic to read only approved rows | High | T-020 | **Superseded (n8n)** | Approval validation is now Python logic; no Sheets checkbox gating. |
| **T-023** | Integrate Gmail/SMTP sending node | High | T-004, T-020 | **Superseded (n8n)** | Outreach adapters stubbed; application submission engine is the current write path. |
| **T-024** | Update status to "Sent" + timestamp after sending | High | T-023 | **Done/Complete** | Lifecycle transitions tracked in registry. |
| **T-025** | Add Telegram confirmation after sending | High | T-021 | **Done/Complete** | Approval confirmations and daemon status updates via Telegram. |
| **T-026** | Implement daily volume limit check | Medium | T-024 | **Done/Complete** | Config-driven daily limits enforced. |
| **T-027** | Create reusable Error Handler sub-workflow | High | T-019 | **Superseded (n8n)** | Error handling implemented as Python functions + structured logging. |
| **T-028** | Connect main workflows using sub-workflows | Medium | T-019, T-027 | **Superseded (n8n)** | `workflow_runner.py` orchestrates Python workflow modules. |
| **T-029** | Perform end-to-end testing with sample data | High | T-018, T-025 | **Done/Complete** | 627 tests passing; dry-run path available for every write command. |
| **T-030** | Test error scenarios and recovery paths | High | T-029 | **Done/Complete** | Error scenarios covered by pytest + dry-run validation. |
| **T-031** | Improve workflow idempotency | Medium | T-029 | **Done/Complete** | Dry-run guards and registry deduplication. |
| **T-032** | Create Operator Runbook | Medium | T-029 | **Done/Complete** | `docs/mvp-operator-runbook.md` and related runbooks. |
| **T-033** | Export all workflows as JSON for backup | High | T-028 | **Superseded (n8n)** | Source code + Git is the backup. n8n instance is read-only reference. |
| **T-034** | Run code-review-graph on final workflows | Medium | T-033 | **Backlog** | Optional; code is reviewed via PR + pytest. |
| **T-035** | Onboard pilot client and run full system | High | T-029, T-032 | **Outstanding (operator-gated)** | Operator action only — cannot be automated. The code-side identity gate (T-044) is now complete; pilot onboarding still requires a human operator to run the live browser verification + commercial checks on a real candidate. |
| **T-036** | Refine prompts based on pilot feedback | Medium | T-035 | **Blocked** | Waiting for pilot data. |
| **T-037** | Update all documentation | Medium | T-035 | **Done/Complete** | Docs refreshed to Wave-1 reality: README/SKILL/implementation-plan/known-limitations test counts synced to 627 collected; identity-gate (T-044) code-completion reflected; Phase-5 "outstanding" language corrected. T-035 pilot onboarding remains operator-gated. |
| **T-038** | Build Hermes hook scripts under `scripts/hooks/` | High | T-002 | **Done/Complete** | Bash wrappers for `cca` CLI; `set -euo pipefail` + venv activation. |
| **T-039** | Implement Playwright SPA browser adapter | High | T-002 | **Done/Complete** | `browser_adapter.py`; authenticated navigation confirmed. |
| **T-040** | Implement opportunity lifecycle registry + reconciliation | High | T-039 | **Done/Complete** | `state_registry.py` + `reconcile_inventory.py`. |
| **T-041** | Implement approval gate with integrity checks | High | T-040 | **Done/Complete** | `approval_gate.py`; gates all CRM writes and application submissions. |
| **T-042** | Implement Telegram inline-keyboard approval daemon | High | T-003, T-041 | **Done/Complete** | Persistent callback worker + Playwright shadow validator. |
| **T-043** | Implement controlled-write MVP / application submission engine | High | T-041, T-042 | **Done/Complete** | Automated application submission with operator approval gating. |
| **T-044** | Candidate identity reconciliation and commercial verification | High | T-040 | **Done (code part)** | Identity gate wired into `FormSubmissionEngine.submit_application` and `CRMPipeline` `application_submitted` writes: only `IDENTITY_VERIFIED` + `RECONCILED` candidates proceed; MISMATCH/EMPTY/UNREACHABLE/QUARANTINED/STALE and unverified candidates are blocked and audited via `submission_audit` / `state_registry`. Live pilot onboarding (T-035) remains operator-gated. |

---

### Task Categories Summary

| Category                        | Tasks          | Priority Focus     |
|---------------------------------|----------------|--------------------|
| **Infrastructure & Setup**      | T-001 to T-005, T-038 | High               |
| **Specifications & Planning**   | T-006 to T-010 | High               |
| **Research & Draft Workflow**   | T-011 to T-019 | High               |
| **Approval & Sending Workflow** | T-020 to T-026 | High               |
| **Error Handling & Modularity** | T-027 to T-028 | High               |
| **Testing & Quality**           | T-029 to T-034 | High               |
| **Pilot & Finalization**        | T-035 to T-037, T-044 | High               |
| **Hermes/Python CLI Build**     | T-038 to T-043 | High               |

---

### Dependencies Overview (Critical Path)

**Foundation Path:**
T-002 → T-038 → T-039

**Spec Path:**
T-007 → T-008 → T-013

**Core Build Path (Research):**
T-013 → T-014 → T-015 → T-016 → T-018

**Core Build Path (Approvals & Controlled Writes):**
T-040 → T-041 → T-042 → T-043 → T-024 → T-025

**Final Path:**
T-029 → T-044 → T-035

---

### Task Management Recommendations

Here’s how you can interact with this task list going forward:

| Command / Request                  | What I Can Do |
|------------------------------------|-------------|
| **"Show all tasks"**               | List all tasks with status |
| **"Show high priority tasks"**     | Filter by High priority |
| **"Show tasks for Phase 2"**       | Group by implementation phase |
| **"Mark T-001 as complete"**       | Update status |
| **"Break down T-013"**             | Create subtasks for complex items |
| **"What are the dependencies for T-020?"** | Show prerequisite tasks |
| **"Analyze complexity"**           | Identify tasks that need breakdown |
| **"Create next sprint tasks"**     | Generate focused list for next phase |

---

### Complexity Analysis (Initial)

| Complexity Level | Tasks | Recommendation |
|------------------|-------|----------------|
| **Low**          | T-002, T-005, T-038 | Can be done quickly |
| **Medium**       | T-011, T-012, T-016, T-020, T-021, T-023 (superseded) | n8n-era core workflows |
| **High**         | T-013, T-014, T-018, T-024, T-029, T-039, T-040, T-041, T-042, T-043 | Involves prompting + integration |
| **Very High**    | T-035 (Pilot), T-044 (Identity/Commercial Verification) | Requires real-world validation |

**Suggested Breakdowns:**
- **T-013 (Researcher Agent)** → Break into: Prompt creation → JSON parsing → Testing
- **T-028 (Connect workflows)** → Break into multiple sub-workflow connection tasks
- **T-029 (End-to-end testing)** → Create multiple testing subtasks

---

### Next Steps

Would you like me to:

1. **Expand this list** with more detailed subtasks for the highest priority items?
2. **Create a Phase 0–1 focused task list** (first 7 days)?
3. **Generate a dependency graph** (text or Mermaid) for the full task list?
4. **Mark some tasks as "In Progress"** and start working on the first ones?

Just tell me how you’d like to proceed (e.g., “Start with Phase 0 tasks” or “Break down T-013”).
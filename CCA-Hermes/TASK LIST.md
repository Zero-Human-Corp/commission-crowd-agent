**Task List: CommissionCrowd Invisible Agent – MVP**

**Generated using Task Master methodology**  
**Based on:** PRD, SRS, App Flow, Backend Structure, Tech Stack, and Implementation Plan  
**Date:** May 21, 2026  
**Approach:** Spec-driven development with AGENTOS + Hermes Agent

---

### Task List Overview

| Task ID | Task Name | Priority | Dependencies | Status | Notes |
|---------|-----------|----------|--------------|--------|-------|
| **T-001** | Provision OCI Always Free instance and install n8n | High | None | To Do | Foundation |
| **T-002** | Set up project folder structure and Git repository | High | None | To Do | - |
| **T-003** | Create Telegram bot and configure in n8n | High | T-001 | To Do | - |
| **T-004** | Configure base credentials in n8n (Google, Telegram, Ollama) | High | T-001 | To Do | - |
| **T-005** | Create Google Sheets templates (Leads + Config) | High | None | To Do | - |
| **T-006** | Define final Google Sheets column structure | High | T-005 | To Do | - |
| **T-007** | Use AGENTOS to formalize PRD and User Stories | High | None | To Do | Spec-driven |
| **T-008** | Create detailed system prompts for micro-agents | High | T-007 | To Do | Researcher, Writer, Scorer |
| **T-009** | Generate architecture diagrams using Graphify | Medium | T-007 | To Do | - |
| **T-010** | Create workflow dependency graph using code-review-graph | Medium | T-009 | To Do | - |
| **T-011** | Build `CC_Research_Draft_Main` workflow skeleton | High | T-001, T-006 | To Do | Main workflow |
| **T-012** | Implement Google Sheets read/write nodes | High | T-011 | To Do | - |
| **T-013** | Implement Researcher Micro-Agent (Kimi-k2.6) | High | T-008, T-011 | To Do | - |
| **T-014** | Implement Writer Micro-Agent | High | T-013 | To Do | - |
| **T-015** | Implement Scorer Micro-Agent (optional) | Medium | T-014 | To Do | - |
| **T-016** | Add status machine logic (New → Researching → Draft Ready) | High | T-012 | To Do | - |
| **T-017** | Add batch processing with limits | Medium | T-016 | To Do | - |
| **T-018** | Add Telegram notification after draft generation | High | T-003, T-016 | To Do | - |
| **T-019** | Add basic error handling to Research workflow | High | T-016 | To Do | - |
| **T-020** | Build `CC_Approve_Send_Main` workflow skeleton | High | T-011 | To Do | - |
| **T-021** | Implement Telegram Trigger for commands | High | T-003, T-020 | To Do | `/approve`, `/send pending` |
| **T-022** | Add logic to read only approved rows | High | T-020 | To Do | - |
| **T-023** | Integrate Gmail/SMTP sending node | High | T-004, T-020 | To Do | - |
| **T-024** | Update status to "Sent" + timestamp after sending | High | T-023 | To Do | - |
| **T-025** | Add Telegram confirmation after sending | High | T-021 | To Do | - |
| **T-026** | Implement daily volume limit check | Medium | T-024 | To Do | From Config sheet |
| **T-027** | Create reusable Error Handler sub-workflow | High | T-019 | To Do | - |
| **T-028** | Connect main workflows using sub-workflows | Medium | T-019, T-027 | To Do | - |
| **T-029** | Perform end-to-end testing with sample data | High | T-018, T-025 | To Do | - |
| **T-030** | Test error scenarios and recovery paths | High | T-029 | To Do | - |
| **T-031** | Improve workflow idempotency | Medium | T-029 | To Do | - |
| **T-032** | Create Operator Runbook | Medium | T-029 | To Do | - |
| **T-033** | Export all workflows as JSON for backup | High | T-028 | To Do | - |
| **T-034** | Run code-review-graph on final workflows | Medium | T-033 | To Do | - |
| **T-035** | Onboard pilot client and run full system | High | T-029, T-032 | To Do | Validation |
| **T-036** | Refine prompts based on pilot feedback | Medium | T-035 | To Do | - |
| **T-037** | Update all documentation | Medium | T-035 | To Do | - |

---

### Task Categories Summary

| Category                        | Tasks          | Priority Focus     |
|---------------------------------|----------------|--------------------|
| **Infrastructure & Setup**      | T-001 to T-005 | High               |
| **Specifications & Planning**   | T-006 to T-010 | High               |
| **Research & Draft Workflow**   | T-011 to T-019 | High               |
| **Approval & Sending Workflow** | T-020 to T-026 | High               |
| **Error Handling & Modularity** | T-027 to T-028 | High               |
| **Testing & Quality**           | T-029 to T-034 | High               |
| **Pilot & Finalization**        | T-035 to T-037 | High               |

---

### Dependencies Overview (Critical Path)

**Foundation Path:**
T-001 → T-003 → T-004 → T-011

**Spec Path:**
T-007 → T-008 → T-013

**Core Build Path (Research):**
T-011 → T-012 → T-013 → T-014 → T-016 → T-018

**Core Build Path (Sending):**
T-020 → T-021 → T-023 → T-024 → T-025

**Final Path:**
T-028 → T-029 → T-035

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
| **Low**          | T-001, T-002, T-003, T-005, T-033 | Can be done quickly |
| **Medium**       | T-011, T-012, T-016, T-020, T-021, T-023 | Core workflows |
| **High**         | T-013, T-014, T-018, T-024, T-028, T-029 | Involves prompting + integration |
| **Very High**    | T-035 (Pilot) | Requires real-world validation |

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
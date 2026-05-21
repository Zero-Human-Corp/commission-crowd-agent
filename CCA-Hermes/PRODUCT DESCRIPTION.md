**Product Name:** CommissionCrowd Invisible Agent (also referred to as CC Pipeline Swarm or Invisible Outreach Agent)

**Version:** 1.0 – MVP Specification  
**Date:** May 2026  
**Target Builder:** Hermes Agent (or any strong LLM coding/agentic system) running on Ollama.com Cloud  
**Core Principle:** Build a **completely headless, invisible automation** that lives inside Google Sheets + n8n. No client-facing dashboard, no new logins, no complex UI. The only human touchpoint is a familiar Google Sheet (for review) + Telegram (for control and notifications).

### 1. Product Vision & Objectives
Create a reliable, low-maintenance automation system that:
- Takes leads (primarily from client-uploaded lists in Google Sheets)
- Performs deep research + hyper-personalization using LLMs
- Stages high-quality email drafts for human approval
- Triggers compliant email outreach upon explicit approval
- Runs 24/7 on the user’s OCI Always Free tier via self-hosted n8n
- Uses Ollama.com Cloud models for all intelligence (via API)
- Scales to multiple clients with minimal overhead

**Primary Goal (MVP):** Replace manual lead research + email writing with a semi-automated “research → draft → approve via Sheet + Telegram → send” pipeline that the operator can run for clients.

**Key Constraints to Respect:**
- Zero frontend development
- Heavy reliance on prompting (no hand-written complex code where possible)
- Human-in-the-loop approval is mandatory (never fully autonomous sending)
- Designed for batch processing, not real-time
- Prioritize auditability, reliability, and basic compliance awareness (POPIA + general anti-spam best practices)

### 2. High-Level Architecture
```
Operator (Mac) 
   ↓ (prompts / SSH)
OCI Server (Always Free)
   └── n8n (self-hosted via Docker)
          ├── Scheduled Workflow: Research & Draft
          ├── Triggered Workflow: Approve & Send (via Telegram)
          └── Supporting nodes: Google Sheets, Telegram, HTTP (Ollama.com Cloud), Email/SMTP
                ↓
         Google Sheets (per client or master)
                ↓ (toggle column)
         Telegram Bot (notifications + approval commands)
                ↓
         Email Sending (Gmail API / SMTP node – client credentials)
```

**Micro-Agent Swarm Philosophy (Critical):**
Break intelligence into small, single-purpose agents instead of one giant prompt. This reduces hallucinations and improves quality:
- **Researcher Agent**
- **Writer / Personalizer Agent**
- **Quality Scorer Agent** (optional but recommended)

### 3. Core Data Model – Google Sheets Structure
**Recommended Setup:** One Google Drive folder per client containing:
- `Leads_{ClientName}.gsheet` (main working sheet)
- `Config_{ClientName}.gsheet` (ICP, tone, templates, sending settings)
- Optional `RunLog` tab or separate sheet

**Leads Sheet – Required Columns (exact names recommended for easy n8n mapping):**

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| Lead ID | Text | Unique identifier | `lead_001` |
| Client Name | Text | Which client this belongs to | `HVAC_Pro_Solutions` |
| Full Name | Text | Prospect name | `Johnathan Reed` |
| Company | Text | Company name | `Reed HVAC Services` |
| Email | Text | Primary email | `john@reedhvac.co.za` |
| LinkedIn / Website | Text | Profile or site | `linkedin.com/in/johnreed` or website |
| Source / Notes | Text | How lead was acquired | `Client uploaded list` |
| Research Notes | Long Text | LLM output – key insights, pain points, triggers | `Recently posted about rising energy costs...` |
| Email Subject | Text | Generated subject line | `Quick question about your recent expansion` |
| Email Body | Long Text | Full personalized email | `Hi Johnathan, saw you just opened a new branch...` |
| Personalization Score | Number (1-10) | LLM self-score | `8` |
| Status | Dropdown/Text | `New` → `Researching` → `Draft Ready` → `Approved` → `Sent` → `Replied` | `Draft Ready` |
| Approved | Boolean / Checkbox | Toggle for operator approval | `TRUE` |
| Sent Timestamp | DateTime | When email was actually sent | `2026-05-21 09:15` |
| Reply Status | Text | `None` / `Opened` / `Replied` / `Positive` (manual or future) | `Positive` |
| Error Log | Text | Any issues during processing | `LLM timeout on research` |

**Config Sheet (per client) – Key Fields:**
- Client Name, ICP Description, Value Proposition, Ideal Tone/Voice, Sample Emails (good & bad), Sending Volume Limit per day, SMTP/Gmail Credential Reference, Telegram Chat ID for notifications.

### 4. Main Workflows to Build

#### Workflow A: Research & Draft (Scheduled – e.g., daily at 7 AM SAST)
**Trigger:** n8n Schedule Trigger (Cron)  
**Steps:**
1. Read rows from Leads Sheet where `Status = "New"` or `Status = "Researching"` (limit to batch size, e.g., 20–50).
2. For each row (loop or batch):
   - Update Status → `Researching`
   - Call **Researcher Agent** (via Ollama.com Cloud) → populate `Research Notes`
   - Call **Writer Agent** → generate `Email Subject` + `Email Body`
   - Call **Scorer Agent** (optional) → `Personalization Score`
   - Update row with all outputs + Status = `Draft Ready`
3. After batch completes: Send Telegram notification to operator with:
   - Link to the Google Sheet
   - Summary: “X new drafts ready for Client Y. Review & toggle Approved column.”
4. Error handling: Log failures to Error Log column + Telegram alert. Retry logic for transient LLM errors.

#### Workflow B: Approve & Send (Triggered by Telegram)
**Trigger:** Telegram Trigger node (listens for commands or callback buttons)  
**Supported Commands (examples):**
- `/approve ClientName` or `/send pending`
- `/status ClientName`
- `/run research now`

**Steps when triggered:**
1. Parse command → identify client and scope (all pending approved, or specific rows).
2. Read Leads Sheet for rows where `Approved = TRUE` AND `Status = "Draft Ready"` AND `Sent Timestamp` is empty.
3. For each approved row:
   - Send email using n8n Email node (Gmail OAuth or SMTP – use client-specific credentials stored in n8n)
   - Update `Status = "Sent"`, `Sent Timestamp`
   - Log to RunLog
4. Send confirmation Telegram message: “Sent X emails for Client Y. Summary: ...”
5. Optional: Update a simple dashboard row or summary in Sheet.

**Hybrid Approval UX (Recommended for MVP):**
- Operator reviews drafts directly in Google Sheet and checks the **Approved** column.
- Then sends a simple Telegram message to trigger sending of all currently approved rows.
- Future enhancement: Inline keyboard buttons in Telegram for quick approve/reject per draft (more advanced).

### 5. LLM Micro-Agent Prompts (Provide These to Hermes)
Hermes should generate well-structured system prompts. Key guidelines:
- Use chain-of-thought or structured JSON output where possible.
- Keep context small per agent.
- Include few-shot examples from the client’s Config sheet.
- Always output in consistent structured format (JSON preferred for n8n parsing).

**Example Researcher Agent Prompt Structure:**
```
You are an expert B2B sales researcher. Analyze the provided lead and company information. Extract 3-5 specific, recent, or relevant insights that could be used for hyper-personalized outreach. Focus on pain points, triggers, recent news, or business context. Output ONLY valid JSON.
```

**Writer / Personalizer Agent:** Takes research notes + ICP + tone from Config + lead data → writes natural, non-salesy email.

### 6. Integrations & Technical Requirements
- **n8n on OCI**: Use Docker. Set up credentials for Google Sheets (OAuth), Telegram Bot, Ollama.com Cloud (HTTP Header Auth or custom), and Email (Gmail or SMTP).
- **Ollama.com Cloud**: Call via HTTP Request node (or dedicated Ollama node if available). Use models like Kimi-k2.6-Coder or high-quality alternatives.
- **Google Sheets**: Native n8n Google Sheets node (preferred) or HTTP. Use Service Account or OAuth.
- **Telegram**: Create bot via @BotFather. Use Telegram Trigger + Telegram node. Support both text commands and inline keyboards for future.
- **Email Sending**: Start with Gmail node (easiest, client authorizes). Later add SMTP with proper warm-up guidance.
- **Error Handling & Logging**: Dedicated Error Workflow + RunLog sheet. Telegram alerts for critical failures.
- **Rate Limiting & Safety**: Hard limits per client per day. Never send without explicit approval.

### 7. MVP Scope (First 10–14 Days Build Target)
1. Single-client mode first (hardcode one Sheet ID for testing).
2. Research + Draft workflow (scheduled).
3. Basic Telegram notification when drafts are ready.
4. Manual review in Sheet + “Approved” column.
5. Telegram-triggered Send workflow for approved rows.
6. Basic error logging and status updates.
7. Config sheet support for ICP/tone.

**Post-MVP (Next Phase):**
- Multi-client support via Client column or folder structure
- Inline keyboard approvals in Telegram
- Reply tracking (basic)
- Per-client daily volume caps
- Run history dashboard in Sheets
- Vertical prompt templates (HVAC, Agencies, etc.)

### 8. Non-Functional & Compliance Requirements
- **Reliability**: Workflows must be idempotent where possible. Use unique Lead IDs.
- **Observability**: Clear status tracking in Sheets + Telegram summaries.
- **Security**: Store all credentials in n8n credential store. Never hardcode secrets. Use environment variables on OCI.
- **Compliance Notes** (include in prompts/docs):
  - Always include proper unsubscribe language.
  - Respect client-provided lists and legitimate interest where applicable.
  - Log all sends for audit.
  - Operator remains responsible for final compliance (POPIA, CAN-SPAM, etc.).
- **Cost**: Near zero (uses existing OCI + Ollama.com subscription).

### 9. Success Criteria for the Built System
- Operator can go from “New leads in Sheet” → “Reviewed drafts” → “Approved & sent” with minimal clicks.
- Draft quality is consistently high enough that only light editing is needed.
- System runs reliably overnight without constant babysitting.
- Easy to add a new client (duplicate Sheet + update Config + add to workflow parameters).
- Full audit trail exists in the Google Sheet.

---

**Instructions for Hermes Agent (copy this section when prompting):**

You are an expert n8n + automation architect. Build the complete CommissionCrowd Invisible Agent system exactly as described above.

Start by:
1. Creating the recommended Google Sheet structure (with example data).
2. Generating the full n8n workflow JSONs (or step-by-step node configuration) for Workflow A and Workflow B.
3. Writing the detailed system prompts for the Researcher, Writer, and Scorer agents.
4. Providing the exact Telegram bot setup steps and command handling logic.
5. Including credential setup instructions for OCI + n8n.
6. Adding clear comments and documentation inside the workflows.

Prioritize simplicity, reliability, and the human-in-the-loop approval pattern described. Use micro-agents and structured outputs wherever possible.

Deliver the output in well-organized sections so I can implement it step by step on my OCI server.

---

This specification is detailed, structured, and actionable enough for a strong agent like Hermes to generate production-ready n8n workflows, prompts, and setup instructions with minimal back-and-forth.

Would you like me to also create a shorter “executive summary” version, a sample client onboarding checklist, or expand any section (e.g., full example prompts or n8n node-by-node breakdown)?
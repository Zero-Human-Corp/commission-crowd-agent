<prd>
# Product Requirements Document (PRD) – CommissionCrowd Invisible Agent MVP

## 1. Product Overview
The CommissionCrowd Invisible Agent is a headless automation system that performs scheduled lead research and hyper-personalized email draft generation using Ollama.com Cloud models, stages results in Google Sheets for operator approval, and executes email sending upon explicit Telegram-triggered approval. Built primarily with self-hosted n8n workflows on Oracle Cloud Infrastructure (Always Free tier), it uses Google Sheets as the data and approval layer and Telegram as the control/notification interface. The MVP delivers reliable batch processing with mandatory human-in-the-loop approval and full auditability while maintaining zero custom frontend or client-facing dashboard.

## 2. User Stories

**US-01**  
As the Operator, I want to onboard a new client by creating a dedicated Google Sheet and Config sheet so that the system can process leads for that client.

**US-02**  
As the Operator, I want to define client-specific ICP, tone, and sample emails in a Config sheet so that the LLM agents generate relevant and on-brand outreach.

**US-03**  
As the Operator, I want to upload or paste new leads into the Leads sheet with Status = "New" so that they enter the research pipeline.

**US-04**  
Given a scheduled trigger, when the Research & Draft workflow runs, then it should select up to 30 rows with Status = "New" and update them to "Researching".

**US-05**  
Given a lead row in "Researching" status, when the Researcher micro-agent is called, then it should populate the Research Notes column with structured insights.

**US-06**  
Given populated Research Notes, when the Writer micro-agent is called, then it should generate an Email Subject and Email Body and update the respective columns.

**US-07**  
Given generated email content, when the Scorer micro-agent runs, then it should assign a Personalization Score (1-10) to the row.

**US-08**  
Given completed research and draft, when processing finishes, then the workflow should set Status = "Draft Ready" and send a Telegram notification with the Google Sheet link.

**US-09**  
As the Operator, I want to review drafts directly in the Google Sheets Leads tab so that I can verify quality before approval.

**US-10**  
As the Operator, I want to toggle the "Approved" checkbox column in Google Sheets for selected rows so that I can mark drafts ready for sending.

**US-11**  
As the Operator, I want to send a Telegram command "/approve [ClientName]" or "/send pending" so that the system processes only approved rows.

**US-12**  
Given approved rows with Status = "Draft Ready", when the Approve & Send workflow executes, then it should send the personalized email using the configured Gmail/SMTP credentials.

**US-13**  
Given a successfully sent email, when the send action completes, then the system should update Status = "Sent", set Sent Timestamp, and log the action.

**US-14**  
As the Operator, I want to receive a Telegram confirmation message after a send batch completes so that I have visibility into execution results.

**US-15**  
Given an error during research, draft generation, or sending, when an error occurs, then the system should log details in the Error Log column and send a Telegram alert.

**US-16**  
As the Operator, I want to trigger an on-demand Research & Draft run via Telegram command so that I can process urgent leads outside the schedule.

**US-17**  
As the Operator, I want to view basic run history and statistics in a RunLog tab or summary row so that I can monitor system activity.

**US-18**  
Given multiple clients, when the Research workflow runs, then it should process leads grouped by Client Name using client-specific configuration from the Config sheet.

**US-19**  
As the Operator, I want to update client configuration (tone, volume limits, sending credentials reference) in the Config sheet so that changes take effect on the next run without code changes.

**US-20**  
Given a row with Status = "Sent", when a reply is manually logged or future tracking is added, then the system should allow updating Reply Status.

**US-21**  
As the Operator, I want the system to respect a daily sending volume limit per client defined in Config so that outreach remains controlled and compliant.

**US-22**  
Given a failed email send (bounce or error), when the send node fails, then the workflow should update Status to "Send Failed", log the error, and notify via Telegram.

**US-23**  
As the Operator, I want all workflows to be idempotent so that re-running a workflow on already processed rows does not duplicate actions or corrupt data.

**US-24**  
As the Operator, I want clear status values and timestamps across all rows so that I can quickly understand the state of any lead at any time.

**US-25**  
As the Operator, I want the Telegram bot to support basic status queries (e.g. "/status ClientName") so that I can check pipeline progress without opening Google Sheets.

## 3. User Flows

**Flow 1: Client Onboarding & Configuration**
1. Operator creates a new Google Drive folder for the client.
2. Duplicates template Leads sheet and Config sheet into the folder.
3. Fills Config sheet with ICP, tone guidelines, sample emails, and credential references.
4. Adds initial leads to the Leads sheet with Status = "New".
5. Updates n8n workflow parameters or credentials store with client-specific details (if needed).
6. Activates scheduled workflow for the client.

**Flow 2: Research & Draft Generation (Automated)**
1. n8n Schedule Trigger fires (e.g., daily at 07:00 SAST).
2. Google Sheets node reads rows where Status = "New".
3. For each row in batch: Update to "Researching" → Call Researcher Agent via HTTP to Ollama.com Cloud → Populate Research Notes.
4. Call Writer Agent → Generate Subject and Body.
5. Call Scorer Agent (optional) → Assign score.
6. Update row to Status = "Draft Ready".
7. After batch: Send Telegram notification with summary and Sheet link.

**Flow 3: Review & Approval**
1. Operator receives Telegram notification.
2. Opens Google Sheet link.
3. Reviews Research Notes, Email Subject, and Email Body for selected rows.
4. Toggles "Approved" column to TRUE for desired rows.
5. Optionally replies on Telegram with command to trigger sending.

**Flow 4: Approve & Send Execution**
1. Operator sends Telegram command (e.g. "/approve ClientName").
2. Telegram Trigger node receives message and parses command.
3. Workflow reads rows where Approved = TRUE AND Status = "Draft Ready".
4. For each row: Execute Email node using stored credentials.
5. Update Status = "Sent" and Sent Timestamp.
6. Send Telegram confirmation with count of emails sent.
7. Log execution to RunLog.

**Flow 5: Error Handling & Monitoring**
1. Any node failure routes to Error Workflow.
2. Error details written to Error Log column and/or dedicated log sheet.
3. Telegram alert sent to Operator.
4. Operator reviews logs and manually corrects or re-triggers affected rows.

## 4. Screens and UI/UX

**Note:** There is **no custom web application or dashboard**. The system is intentionally headless.

**Primary Interface 1: Google Sheets (Leads Sheet)**
- Main working interface for data entry, review, and approval.
- Key columns: Lead ID, Client Name, Full Name, Company, Email, Research Notes, Email Subject, Email Body, Personalization Score, Status, Approved (checkbox), Sent Timestamp, Error Log.
- UI Elements: Standard Google Sheets formatting, data validation on Status column, checkbox for Approved, conditional formatting on Status.
- Interactions: Manual editing, sorting/filtering, checkbox toggling.

**Primary Interface 2: Google Sheets (Config Sheet)**
- Client-specific configuration.
- Fields: ICP description, Tone/Voice guidelines, Sample good/bad emails, Daily volume limit, Credential references.
- Used as structured input for LLM prompts.

**Primary Interface 3: Telegram Bot**
- Notifications and control plane.
- Notifications: Drafts ready alerts, send confirmations, error alerts.
- Commands: `/approve`, `/send pending`, `/status`, `/run research`.
- Future: Inline keyboard buttons for quick approve/reject (MVP uses text commands + Sheet checkbox).

## 5. Features and Functionality

- Scheduled batch Research & Draft workflow with micro-agent orchestration.
- Structured LLM calls to Ollama.com Cloud with JSON output parsing.
- Google Sheets read/write with status machine (New → Researching → Draft Ready → Approved → Sent).
- Telegram Trigger for command-based workflow execution.
- Mandatory human approval via Google Sheets checkbox before any sending.
- Config-driven behavior per client (ICP, tone, volume limits).
- Basic error logging and Telegram alerting.
- Idempotent workflow design.
- Support for multiple clients via Client Name column and per-client Config.
- Email sending via n8n Gmail or SMTP nodes with credential isolation.

## 6. Technical Architecture

**High-Level Components:**
- **Orchestration Layer**: Self-hosted n8n (Docker) on Oracle Cloud Infrastructure Always Free Ampere instance.
- **Data Layer**: Google Sheets (primary data store and approval interface).
- **Intelligence Layer**: Ollama.com Cloud accessed via HTTP Request nodes (structured prompts + JSON mode).
- **Control & Notification Layer**: Telegram Bot API via n8n Telegram Trigger and Send nodes.
- **Execution Layer**: n8n Email nodes (Gmail OAuth or SMTP) for final sending.
- **Operator Access**: MacBook via SSH (for n8n management) + Google Sheets + Telegram.

**Interaction Flow:**
n8n workflows read/write Google Sheets → Call Ollama.com Cloud for agents → Update Sheets → Notify/Receive commands via Telegram → Execute email sending.

## 7. System Design

**Core Components:**
- **n8n Instance** (OCI Docker): Hosts all workflows, credentials, and execution history.
- **Google Sheets**: Acts as both database and lightweight UI. Contains Leads, Config, and RunLog tabs.
- **Telegram Bot**: Provides asynchronous control and notifications.
- **Ollama.com Cloud**: External LLM inference (no local model hosting required for MVP).
- **Email Provider**: Client Gmail account (OAuth) or SMTP credentials stored securely in n8n.

**Workflow Separation (Recommended):**
- Workflow A: Research & Draft (Scheduled + on-demand)
- Workflow B: Approve & Send (Telegram triggered)
- Workflow C: Error Handler + Logging (sub-workflow)

## 8. API Specifications

**Internal/External APIs Used:**
- **Ollama.com Cloud API** (HTTP): POST requests with system + user prompts. Expected response: JSON with structured fields (research_notes, subject, body, score).
- **Google Sheets API** (via n8n native node): Read range, Update rows, Append.
- **Telegram Bot API** (via n8n nodes): Send message, receive updates via webhook/polling.
- **Gmail API / SMTP**: Email sending (no custom endpoints exposed).

No public REST API is exposed by the MVP. All interaction occurs through n8n workflows, Google Sheets, and Telegram.

## 9. Data Model

**Primary Entities (implemented as Google Sheets tabs):**

**Leads Sheet**
- Lead ID (Text, unique)
- Client Name (Text)
- Full Name, Company, Email, LinkedIn/Website (Text)
- Research Notes (Long Text)
- Email Subject, Email Body (Text/Long Text)
- Personalization Score (Number)
- Status (Text: New | Researching | Draft Ready | Approved | Sent | Send Failed)
- Approved (Boolean)
- Sent Timestamp (DateTime)
- Error Log (Text)
- Reply Status (Text – future use)

**Config Sheet (per client)**
- Client Name
- ICP Description
- Tone Guidelines
- Sample Emails (good/bad)
- Daily Send Limit
- Credential References (Gmail/SMTP reference names in n8n)

**RunLog Sheet (optional but recommended)**
- Timestamp, Client, Action Type, Rows Processed, Success Count, Error Count, Notes

Relationships: Config → Leads (via Client Name). One-to-many.

## 10. Security Considerations

- All credentials (Google, Telegram, Ollama.com Cloud, Gmail/SMTP) stored in n8n encrypted credential store.
- Use OAuth where possible for Google services.
- Least-privilege Google service account or OAuth scopes.
- Telegram bot token kept secure; bot restricted to private chat with Operator only.
- No sensitive client data stored outside Google Sheets and n8n execution logs.
- Operator manually reviews all content before sending.
- Basic audit trail via status timestamps and RunLog.

## 11. Performance Requirements

- Research & Draft workflow should process 20–50 leads per run within 15–40 minutes (depending on LLM response time).
- Telegram commands should trigger actions within 30 seconds.
- Google Sheets updates should be near real-time.
- System should handle at least 3–5 concurrent clients in MVP without degradation.
- LLM calls should use reasonable timeouts and retry logic for transient failures.

## 12. Scalability Considerations

- n8n on OCI can be scaled vertically (larger Always Free-eligible instance if needed) or by adding more workflow instances.
- Google Sheets has practical limits (~10k–50k rows per sheet); future migration path to Supabase/Postgres considered post-MVP.
- Micro-agent design allows independent scaling of intelligence components.
- Client isolation via Config-driven parameters enables horizontal growth in number of clients.
- Queueing or batch size controls can be added to manage load.

## 13. Testing Strategy

- **Unit/Workflow Testing**: Manual execution of individual n8n nodes and sub-workflows during development.
- **Integration Testing**: End-to-end runs of Research → Draft → Approve → Send flow with sample data.
- **Data Validation**: Verify correct status transitions and column population.
- **Error Path Testing**: Simulate LLM failures, send failures, and malformed data.
- **Idempotency Testing**: Re-run workflows on processed rows and verify no duplication.
- **Operator Acceptance**: Full manual walkthrough by the Operator using real (anonymized) client data.

## 14. Deployment Plan

1. Provision OCI Always Free Ampere instance and install Docker + n8n.
2. Configure n8n with required credentials (Google, Telegram, Ollama.com Cloud, Email).
3. Import and activate the three core workflows (Research & Draft, Approve & Send, Error Handler).
4. Create template Google Sheet structures and share with Operator.
5. Set up Telegram bot and connect to n8n.
6. Configure scheduled triggers and test with a pilot client.
7. Document runbooks for Operator (how to onboard clients, trigger commands, handle common errors).

## 15. Maintenance and Support

- Operator is responsible for daily monitoring via Telegram notifications and Google Sheets.
- Routine tasks: Review error logs, update client Config sheets, occasionally re-authenticate Google credentials.
- Workflow updates performed by editing n8n workflows directly or via prompted regeneration with Hermes.
- LLM prompt improvements handled by updating system prompts in n8n nodes.
- Backup strategy: Export important n8n workflows and keep Google Sheets version history enabled.
- Post-MVP enhancements (inline keyboards, advanced logging, multi-workflow orchestration) can be added incrementally.

</prd>
**Software Requirements Specification (SRS)**

**Document Title:** Software Requirements Specification – CommissionCrowd Invisible Agent MVP  
**Version:** 1.0  
**Date:** May 21, 2026  
**Author:** Grok (based on Product Description and PRD)  
**Status:** Draft for Implementation  

---

### 1. Introduction

#### 1.1 Purpose
This Software Requirements Specification (SRS) defines the functional and non-functional requirements for the **CommissionCrowd Invisible Agent** MVP. It serves as the primary technical reference for building, testing, and maintaining the headless automation system using n8n workflows on Oracle Cloud Infrastructure.

#### 1.2 Scope
The system is a **headless automation platform** that:
- Performs scheduled and on-demand lead research and email personalization using Ollama.com Cloud models.
- Uses Google Sheets as the data store and human approval interface.
- Uses Telegram as the operator control and notification channel.
- Executes email sending only after explicit operator approval.
- Supports multiple clients through configuration-driven workflows.

**Out of Scope for MVP:**
- Custom web dashboard or frontend
- Fully autonomous sending without approval
- Advanced reply tracking or CRM sync
- Local LLM hosting (uses Ollama.com Cloud)
- Mobile application

#### 1.3 Definitions, Acronyms, and Abbreviations
- **Operator**: The person who manages and runs the automation service.
- **Leads Sheet**: Google Sheet containing lead data and approval status.
- **Config Sheet**: Google Sheet storing client-specific settings.
- **Micro-Agent**: Specialized LLM prompt/task (Researcher, Writer, Scorer).
- **n8n**: Workflow automation platform (self-hosted).
- **Status Machine**: New → Researching → Draft Ready → Approved → Sent.

#### 1.4 References
- CommissionCrowd Invisible Agent Product Description (v1.0)
- CommissionCrowd Invisible Agent PRD (v1.0)
- Target Audience Document
- n8n Documentation
- Google Sheets API
- Telegram Bot API
- Ollama.com Cloud API

#### 1.5 Overview
This document is organized into Overall Description, Specific Requirements (Functional & Non-Functional), System Interfaces, and Supporting Information.

---

### 2. Overall Description

#### 2.1 Product Perspective
The CommissionCrowd Invisible Agent is a **workflow orchestration system** rather than a traditional application. It consists of:
- Self-hosted n8n instance running on Oracle Cloud Infrastructure (Always Free tier)
- Google Sheets as the primary persistent data store and approval layer
- Telegram Bot for asynchronous control and notifications
- External LLM inference via Ollama.com Cloud
- Email sending via Gmail API or SMTP

The system has **no standalone client application**. All interaction occurs through Google Sheets and Telegram.

#### 2.2 Product Functions
Major functions include:
- Scheduled and manual execution of Research & Draft workflows
- Structured LLM calls for research and email generation
- Status-based workflow control using Google Sheets
- Human approval via checkbox + Telegram command
- Controlled email execution
- Error logging and alerting
- Basic multi-client support via configuration

#### 2.3 User Characteristics
**Primary User**: Operator (non-developer but technically comfortable with prompting, Google Sheets, and basic workflow concepts).  
The Operator interacts with the system daily for review, approval, and monitoring. No end-client users interact directly with the system.

#### 2.4 Constraints
- Must run on Oracle Cloud Infrastructure Always Free tier resources.
- Must use existing Ollama.com Cloud subscription for LLM inference.
- Must remain headless (no custom frontend development).
- Must enforce human approval before any email is sent.
- Google Sheets is the mandated data and approval interface.

#### 2.5 Assumptions and Dependencies
- Operator has access to Google Workspace and can create/share Sheets.
- Operator maintains a Telegram bot.
- Ollama.com Cloud API remains accessible and stable.
- Client provides leads and grants necessary access (Sheets or email credentials).
- n8n credential store is used for all secrets.

---

### 3. Specific Requirements

#### 3.1 Functional Requirements

**FR-1: Workflow Execution**
- **FR-1.1**: The system shall support a scheduled Research & Draft workflow that runs automatically at a configurable time (default: daily at 07:00 SAST).
- **FR-1.2**: The system shall allow the Operator to trigger the Research & Draft workflow on-demand via a Telegram command.
- **FR-1.3**: The system shall support a Telegram-triggered Approve & Send workflow.

**FR-2: Lead Processing & Status Management**
- **FR-2.1**: The system shall read leads from a Google Sheet where `Status = "New"`.
- **FR-2.2**: The system shall update lead status through the following machine: `New → Researching → Draft Ready → Approved → Sent`.
- **FR-2.3**: The system shall only process rows that have not yet been sent (`Sent Timestamp` is empty).

**FR-3: LLM Micro-Agent Orchestration**
- **FR-3.1**: The system shall call separate micro-agents (Researcher, Writer, Scorer) via HTTP requests to Ollama.com Cloud.
- **FR-3.2**: Each micro-agent shall return structured JSON output.
- **FR-3.3**: The system shall populate `Research Notes`, `Email Subject`, `Email Body`, and `Personalization Score` columns based on agent responses.

**FR-4: Approval Mechanism**
- **FR-4.1**: The system shall only send emails for rows where the `Approved` column is set to `TRUE`.
- **FR-4.2**: The Approve & Send workflow shall be triggered exclusively by a Telegram command from the Operator.
- **FR-4.3**: The system shall prevent sending if the `Approved` flag is not explicitly set.

**FR-5: Email Execution**
- **FR-5.1**: The system shall send personalized emails using credentials stored in n8n (Gmail OAuth or SMTP).
- **FR-5.2**: After successful sending, the system shall update `Status = "Sent"` and populate `Sent Timestamp`.
- **FR-5.3**: The system shall respect per-client daily sending volume limits defined in the Config sheet.

**FR-6: Notifications & Control**
- **FR-6.1**: The system shall send a Telegram notification when a batch of drafts is ready for review.
- **FR-6.2**: The system shall send a Telegram confirmation after an Approve & Send batch completes.
- **FR-6.3**: The Telegram bot shall support commands including `/approve`, `/send pending`, `/status`, and `/run research`.

**FR-7: Error Handling & Logging**
- **FR-7.1**: The system shall log errors in the `Error Log` column of the Leads sheet.
- **FR-7.2**: The system shall send a Telegram alert when a critical error occurs during workflow execution.
- **FR-7.3**: Failed send attempts shall update status to `Send Failed`.

**FR-8: Multi-Client Support**
- **FR-8.1**: The system shall support multiple clients using the `Client Name` column and per-client Config sheets.
- **FR-8.2**: Configuration (tone, ICP, volume limits) shall be read dynamically from the Config sheet.

#### 3.2 Non-Functional Requirements

**NFR-1: Performance**
- Research & Draft workflow shall complete processing of up to 50 leads within 40 minutes.
- Telegram command response time shall be under 30 seconds.
- Google Sheets updates shall reflect within 10 seconds of workflow execution.

**NFR-2: Reliability**
- Workflows shall be designed to be idempotent.
- The system shall retry transient LLM or API failures up to 3 times before logging an error.
- Scheduled workflows shall continue running even if individual rows fail.

**NFR-3: Security**
- All credentials shall be stored in the n8n encrypted credential store.
- The Telegram bot shall only respond to the Operator’s private chat.
- Google Sheets access shall use OAuth with minimal required scopes.
- No sensitive data shall be logged in plain text outside Google Sheets and n8n execution history.

**NFR-4: Maintainability**
- All LLM prompts shall be stored in n8n nodes and easily editable.
- Workflow logic shall be modular (separate Research and Send workflows).
- Clear status values and timestamps shall be maintained for auditability.

**NFR-5: Usability (for Operator)**
- The Operator shall be able to review and approve leads using only Google Sheets and Telegram.
- No custom UI development shall be required.

#### 3.3 Interface Requirements

**3.3.1 User Interfaces**
- Google Sheets (Leads and Config tabs)
- Telegram Bot (commands and notifications)

**3.3.2 Software Interfaces**
- **n8n Internal**: Workflow engine, nodes (Google Sheets, Telegram, HTTP Request, Email, Switch, IF, etc.)
- **External**:
  - Google Sheets API
  - Telegram Bot API
  - Ollama.com Cloud API (HTTP)
  - Gmail API or SMTP

**3.3.3 Communication Interfaces**
- HTTPS for all external API calls (Ollama.com Cloud, Google, Telegram)
- Webhook or polling for Telegram updates

#### 3.4 Data Requirements

- Primary data store: Google Sheets
- Key entities: Leads, Client Configuration, Run Logs
- All lead data and approval decisions must be persisted in Google Sheets
- Status field must enforce valid state transitions

#### 3.5 System Attributes

- **Availability**: Workflows should run reliably on OCI Always Free infrastructure.
- **Auditability**: Full history of status changes and actions must be visible in Google Sheets.
- **Portability**: Workflows should be exportable as JSON for backup or migration.

---

### 4. System Requirements

- **Hosting**: Oracle Cloud Infrastructure (Ampere A1 or compatible Always Free instance)
- **Platform**: Docker + n8n (latest stable version)
- **External Services**:
  - Google Workspace account with Sheets access
  - Telegram Bot (created via @BotFather)
  - Ollama.com Cloud subscription
  - Gmail or SMTP account for sending (per client)

---

### 5. Appendices

**A. Status Values (Enum)**
`New`, `Researching`, `Draft Ready`, `Approved`, `Sent`, `Send Failed`

**B. Core Workflow Summary**
- **Research & Draft Workflow**: Scheduled + Manual trigger
- **Approve & Send Workflow**: Telegram trigger only
- **Error Handling**: Sub-workflow or Error branch

**C. Traceability**
All functional requirements in Section 3.1 map directly to the User Stories defined in the PRD.

---

This SRS document provides a clear, traceable, and implementation-focused specification for building the CommissionCrowd Invisible Agent MVP.

Would you like me to expand any section (e.g., add more detailed interface specifications, acceptance criteria for each FR, or create a requirements traceability matrix)?
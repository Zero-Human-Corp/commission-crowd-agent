**TECH STACK Document**

**Product:** CommissionCrowd Invisible Agent  
**Version:** 1.0  
**Date:** May 21, 2026  
**LLM Choice:** Kimi-k2.6 (via Ollama.com Cloud)

---

### 1. Introduction

This document defines the complete technology stack for building and operating the **CommissionCrowd Invisible Agent** — a headless, spec-driven automation system for lead research, personalized outreach, and pipeline management.

The stack is designed to be:
- Lightweight and low-cost (leveraging Oracle Cloud Always Free)
- Highly agentic and spec-driven
- Maintainable with strong visualization and code review practices
- Aligned with modern AI-first development workflows

---

### 2. Core Technology Stack Overview

| Layer                    | Technology                          | Purpose                                      | Notes |
|--------------------------|-------------------------------------|----------------------------------------------|-------|
| **Orchestration**        | n8n (Self-hosted)                   | Workflow automation engine                   | Primary backend |
| **Infrastructure**       | Oracle Cloud Infrastructure (OCI)   | Hosting & compute                            | Always Free Ampere tier |
| **LLM / Intelligence**   | Kimi-k2.6 via Ollama.com Cloud      | Research, writing, and scoring agents        | Primary model |
| **Data Layer**           | Google Sheets                       | Data storage, configuration & approval UI    | Primary data store |
| **Control Plane**        | Telegram Bot API                    | Operator commands & notifications            | Lightweight interface |
| **Email Delivery**       | Gmail API / SMTP                    | Final email sending                          | Per-client credentials |
| **Development Framework**| AGENTOS                             | Spec-driven development                      | Core methodology |
| **Visualization**        | Graphify + code-review-graph        | Architecture & code review visualization     | Quality & documentation |
| **Scaffolding / Stack**  | GSTACK by Gary Tan                  | Modern development stack principles          | Guiding architecture |

---

### 3. Infrastructure

| Component              | Choice                              | Justification |
|------------------------|-------------------------------------|-------------|
| **Cloud Provider**     | Oracle Cloud Infrastructure (OCI)   | Always Free tier with powerful Ampere instances (up to 24GB RAM) |
| **Compute**            | Ampere A1 Compute (ARM)             | Best performance/price in Always Free tier |
| **Containerization**   | Docker + Docker Compose             | Standard for running n8n reliably |
| **Hosting Model**      | Self-hosted n8n                     | Full control, zero recurring cost |

**Deployment Target:** Single OCI Always Free instance running n8n via Docker.

---

### 4. AI & LLM Layer

| Component              | Technology                  | Role |
|------------------------|-----------------------------|------|
| **Primary LLM**        | **Kimi-k2.6** (Ollama.com Cloud) | Research Agent, Writer Agent, Scorer Agent |
| **Inference Method**   | Ollama.com Cloud API        | Hosted model access via HTTP |
| **Agent Architecture** | Micro-Agent Swarm           | Separate specialized prompts for research, writing, and scoring |
| **Prompt Management**  | Stored in n8n nodes         | Version-controlled via workflow exports |

**Why Kimi-k2.6?**
- Strong performance in structured output and reasoning
- Good at following complex instructions
- Reliable via Ollama.com Cloud

---

### 5. Development & Scaffolding Tools

This project follows a **spec-driven, agentic development approach**.

| Tool                        | Purpose                                      | Integration in Project |
|----------------------------|----------------------------------------------|------------------------|
| **AGENTOS**                | Spec-driven development framework            | Primary methodology for building workflows and agents |
| **GSTACK by Gary Tan**     | Modern full-stack / clean architecture principles | Guides overall project structure and modularity |
| **Graphify**               | Architecture diagram & visualization tool    | Used to generate system flow diagrams |
| **code-review-graph**      | Code review and dependency visualization     | Used during development and maintenance for quality checks |

**Development Philosophy:**
- Start with clear specifications (using AGENTOS)
- Visualize architecture using **Graphify**
- Maintain code/workflow quality using **code-review-graph**
- Follow clean, modular principles inspired by **GSTACK**

---

### 6. Data & Integration Layer

| Component             | Technology              | Role |
|-----------------------|-------------------------|------|
| **Primary Database**  | Google Sheets           | Lead data, configuration, approval flags, and audit trail |
| **API Integration**   | n8n HTTP Request nodes  | Communication with Ollama.com Cloud, Google APIs, Telegram |
| **Authentication**    | OAuth2 + n8n Credentials| Secure access to Google and other services |
| **File/Template Storage** | Google Drive         | Client-specific sheets and templates |

---

### 7. Workflow Orchestration

| Component             | Technology     | Details |
|-----------------------|----------------|--------|
| **Workflow Engine**   | n8n            | Core of the entire system |
| **Workflow Style**    | Modular + Sub-workflows | Research & Draft, Approve & Send, Error Handler |
| **Trigger Types**     | Schedule + Telegram Trigger | Automated + Operator-controlled |
| **State Management**  | Google Sheets columns | Status machine (New → Researching → Draft Ready → Approved → Sent) |

---

### 8. Communication & Notifications

| Component          | Technology             | Usage |
|--------------------|------------------------|-------|
| **Operator Control** | Telegram Bot         | Commands (`/approve`, `/status`, etc.) |
| **Notifications**   | Telegram Bot           | Draft ready alerts, send confirmations, error alerts |
| **Email Sending**   | Gmail API / SMTP       | Final personalized outreach |

---

### 9. Recommended Project Structure

```
/CommissionCrowd_Invisible_Agent/
├── workflows/                  # Exported n8n workflow JSONs
│   ├── CC_Research_Draft_Main.json
│   ├── CC_Approve_Send_Main.json
│   ├── CC_Error_Handler.json
│   └── CC_Telegram_Router.json
├── prompts/                    # LLM system prompts
│   ├── researcher.md
│   ├── writer.md
│   └── scorer.md
├── specs/                      # AGENTOS specifications
│   ├── prd.md
│   ├── srs.md
│   └── user-stories.md
├── diagrams/                   # Generated by Graphify
│   ├── architecture.png
│   └── data-flow.png
├── templates/                  # Google Sheets templates
│   ├── Leads_Template.xlsx
│   └── Config_Template.xlsx
├── docs/                       # All project documentation
│   ├── Tech_Stack.md
│   ├── Security_Guidelines.md
│   └── App_Flow.md
├── reviews/                    # code-review-graph outputs
└── README.md
```

---

### 10. Development Workflow

1. **Specification Phase** — Use **AGENTOS** to define clear specs and user stories.
2. **Visualization Phase** — Use **Graphify** to create architecture and flow diagrams.
3. **Implementation Phase** — Build modular n8n workflows following GSTACK-inspired clean principles.
4. **Review Phase** — Use **code-review-graph** to analyze workflow structure and dependencies.
5. **Testing Phase** — Run end-to-end flows with sample data.
6. **Deployment Phase** — Deploy to OCI Docker instance.
7. **Iteration** — Update specs → Regenerate diagrams → Refine workflows.

---

### 11. Technology Justifications

| Decision                    | Reason |
|----------------------------|--------|
| **n8n as core**            | Best balance of power, flexibility, and low-code for automation |
| **OCI Always Free**        | Zero infrastructure cost with strong hardware |
| **Kimi-k2.6**              | Excellent structured reasoning and output quality |
| **Google Sheets**          | Familiar, collaborative, and sufficient as a data + UI layer |
| **Telegram**               | Lightweight, reliable, and excellent for operator control |
| **AGENTOS + Graphify + code-review-graph** | Enables high-quality, spec-driven, visual development |
| **GSTACK principles**      | Provides modern architectural guidance for long-term maintainability |

---

### 12. Summary

| Category               | Chosen Technology                          | Category               | Chosen Technology |
|------------------------|--------------------------------------------|------------------------|-------------------|
| Orchestration          | n8n                                        | LLM                    | Kimi-k2.6 (Ollama.com Cloud) |
| Infrastructure         | Oracle Cloud (Always Free)                 | Development Framework  | AGENTOS |
| Data Store             | Google Sheets                              | Visualization          | Graphify |
| Control & Notifications| Telegram                                   | Code Review            | code-review-graph |
| Architecture Guidance  | GSTACK by Gary Tan                         | Containerization       | Docker |

---

This **Tech Stack** combines reliable automation infrastructure with modern agentic and spec-driven development practices.

Would you like me to also create:
- A **Development Environment Setup Guide** based on this stack?
- A **Recommended n8n + AGENTOS Workflow**?
- A version of this document focused on **long-term evolution** of the stack?
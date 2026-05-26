# Architecture — Commission Crowd Agent

## Overview

The Commission Crowd Agent is a **headless AI automation system** that replaces n8n as its primary workflow engine with **Hermes-triggered, Git-controlled Python workflows**. It runs on Oracle Cloud Infrastructure (OCI) and is operated via Telegram.

See `docs/decisions/ADR-001-replace-n8n-primary-workflows-with-hermes-hooks.md` for the architectural decision record.

---

## High-Level Architecture

```
Operator (Telegram / Hermes)
        │
        ▼
+-------------------------------------+
│  Hermes Agent / Telegram Bot        │
│  (commands, approval, status)       │
+-------------------------------------+
        │
        ▼
+-------------------------------------+
│  Hook Scripts (scripts/hooks/)      │
│  preflight, run_research, etc.     │
+-------------------------------------+
        │
        ▼
+-------------------------------------+
│  Python CLI (commission_crowd_agent) │
│  config, domain, workflows, adapters │
+-------------------------------------+
        │
        ▼
+------------+  +-------------+  +----------------+
│  Google    │  │  Ollama /  │  │  Telegram    │
│  Sheets    │  │  LLM       │  │  (notifier)  │
+------------+  +-------------+  +----------------+
```

---

## Components

### 1. Operator Interface
- **Hermes Agent via Telegram** — primary control plane
- **Google Sheets** — lightweight data and approval layer (optional, not MVP-blocking)

### 2. Hook Scripts (`scripts/hooks/`)
Each hook is a bash script that:
- Enforces `set -euo pipefail`
- Changes to the repo root
- Calls the Python CLI with the corresponding subcommand
- Writes run artifacts to `data/runs/` (gitignored)

Hooks:
| Hook | Purpose |
|------|---------|
| `preflight.sh` | Verify settings, adapters, secrets readiness |
| `run_research_cycle.sh` | Fetch leads → research → draft → score |
| `score_opportunities.sh` | Re-evaluate or score existing leads |
| `draft_outreach.sh` | Generate email drafts for approved leads |
| `request_approval.sh` | Send operator approval summary via Telegram |
| `send_approved_outreach.sh` | Send emails for leads marked approved |
| `daily_summary.sh` | Report pipeline stats to operator |

### 3. Python CLI (`src/commission_crowd_agent/cli.py`)
- `status` — show adapter readiness
- `run-research-cycle --dry-run` — full research-to-draft pipeline
- `score-opportunities` — batch scoring
- `draft-outreach` — generate emails
- `request-approval` — queue approval request
- `send-approved-outreach` — dispatch approved emails
- `daily-summary` — operator-facing stats

### 4. Workflow Core (`src/commission_crowd_agent/workflows/`)
- `research_cycle.py` — fetch, research, write, score
- `scoring.py` — LLM-based personalisation scoring
- `outreach.py` — email composition and dispatch
- `approvals.py` — approval gate logic

### 5. Adapters (`src/commission_crowd_agent/adapters.py` and future modules)
- **SourceAdapter** — Google Sheets read/write
- **ScoringAdapter** — Ollama.com Cloud / LLM calls
- **NotifierAdapter** — Telegram Bot notifications
- **OutreachAdapter** — Gmail / SMTP send

All adapters accept stub implementations for tests.

---

## Data Flow

### Research & Draft Cycle
1. Hook calls `cca run-research-cycle`
2. CLI loads config → instantiates adapters
3. SourceAdapter fetches leads with `status = New`
4. For each lead:
   - ScoringAdapter.research() → `research_notes`
   - ScoringAdapter.write_email() → `subject`, `body`
   - ScoringAdapter.score() → `personalization_score`
5. SourceAdapter updates rows with `status = Draft Ready`
6. NotifierAdapter sends Telegram summary to operator

### Approval & Send Cycle
1. Operator reviews drafts in Sheets (or via Telegram summary)
2. Operator toggles `Approved = TRUE` or sends `/approve` command
3. Hook calls `cca send-approved-outreach`
4. OutreachAdapter dispatches emails
5. SourceAdapter updates `status = Sent`, `sent_timestamp`
6. NotifierAdapter sends confirmation

---

## Testing Strategy
- **Unit tests**: pytest with stub adapters, no secrets needed
- **Dry-run mode**: every CLI command supports `--dry-run`
- **Integration tests**: only run when real `.env` is present and operator approves
- **dev_check.sh**: ruff + mypy + pytest in one command

---

## Legacy n8n
- n8n instance remains running on OCI (`:5678`) as **reference only**.
- Any existing workflow exports are stored under `docs/legacy/n8n/`.
- No new n8n workflows are created for MVP.
- If Hermes-hooks architecture succeeds, n8n may be fully decommissioned in a future phase.

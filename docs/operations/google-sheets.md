# Google Sheets Schema — Commission Crowd Agent

## Overview

A shared Google Sheet acts as a lightweight CRM and state store before a database is needed.
Each tab maps to a domain entity in the agent pipeline.

## Spreadsheet structure

### Tab 1: `leads`

| Column | Type | Description |
|--------|------|-------------|
| lead_id | str | UUID or stable ID |
| source | str | Where the lead was discovered |
| name | str | Full name |
| company | str | Company name |
| url | str | Website or LinkedIn URL |
| email | str | Contact email |
| status | str | `new`, `researching`, `draft_ready`, `approved`, `sent`, `rejected` |
| created_at | ISO datetime | When the lead was first seen |
| notes | str | Free-text research notes |

### Tab 2: `opportunities`

| Column | Type | Description |
|--------|------|-------------|
| opportunity_id | str | UUID |
| lead_id | str | FK to leads.lead_id |
| title | str | Opportunity title |
| score | int | 1–10 personalisation score |
| stage | str | `new`, `researching`, `scored`, `drafting`, `pending_approval`, `approved`, `sent`, `won`, `lost` |
| next_action | str | What the agent should do next |
| created_at | ISO datetime | |
| updated_at | ISO datetime | |

### Tab 3: `approvals`

| Column | Type | Description |
|--------|------|-------------|
| approval_id | str | UUID |
| opportunity_id | str | FK |
| draft_text | str | Full outreach draft |
| approval_status | str | `pending`, `approved`, `rejected` |
| approved_by | str | Operator name or Telegram ID |
| approved_at | ISO datetime | |
| telegram_message_id | str | Message ID of the approval request in Telegram |

### Tab 4: `runs`

| Column | Type | Description |
|--------|------|-------------|
| run_id | str | UUID |
| workflow | str | `research_cycle`, `scoring`, `draft_outreach`, `send_approved` |
| status | str | `started`, `completed`, `failed` |
| started_at | ISO datetime | |
| completed_at | ISO datetime | |
| summary | str | JSON or free-text summary |

### Tab 5: `outcomes`

| Column | Type | Description |
|--------|------|-------------|
| outcome_id | str | UUID |
| opportunity_id | str | FK |
| result | str | `replied`, `meeting_booked`, `no_reply`, `bounced`, `unsubscribed` |
| revenue_signal | str | `high`, `medium`, `low` |
| notes | str | |
| recorded_at | ISO datetime | |

## Setup

1. Create a new Google Sheet with the tabs above.
2. Set the first row of each tab to the column headers.
3. Note the **Spreadsheet ID** from the URL.
4. Add `GOOGLE_SHEETS_SPREADSHEET_ID=<id>` to `/home/ubuntu/hermes-control/secrets/shared.env`.
5. Add either service account credentials (recommended for server use) or OAuth tokens.

### Service account credentials (recommended)

```bash
# In /home/ubuntu/hermes-control/secrets/shared.env
GOOGLE_APPLICATION_CREDENTIALS_PATH=/home/ubuntu/hermes-control/secrets/cca-service-account.json
```

Or inline the JSON:

```bash
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

### OAuth credentials (legacy / user-consent flow)

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
```

## Notes

- The adapter will auto-create tabs if `ensure_schema()` is called with `--write`.
- All writes default to **dry-run** unless `--write` is explicitly passed.
- No credentials are stored in the repository.

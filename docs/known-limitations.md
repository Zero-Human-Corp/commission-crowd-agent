# CCA MVP Known Limitations

Version: MVP v0.1.0 | Commit: `7d39c6f`
Date: 2026-06-10

## What Works
- ✅ Live CommissionCrowd API fetch (`cca shadow-run`)
- ✅ Canonical opportunity model with 20+ fields
- ✅ Evidence-based multi-factor scoring (commission, territory, residual, data, enablement, market)
- ✅ Live-shadow mode with zero external writes
- ✅ Synthetic contamination detection
- ✅ Truthful application draft generation with payload hash
- ✅ `.env` > `shared.env` credential precedence

## What's Blocked (Requires Operator Input)
1. **Controlled-write mode** — needs working Google Sheets credentials (`GOOGLE_APPLICATION_CREDENTIALS_PATH` or service account JSON)
2. **Approval gate writes** — same Sheets dependency
3. **Telegram digest** — needs `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` configured
4. **Operator identity in drafts** — currently uses `OPERATOR_NAME` from `.env`; if blank, falls back to "Your Name"

## What's Explicitly Out Of Scope
- Automatic CommissionCrowd application submission
- Browser automation for applying
- Automatic external email sending
- Automatic approval (all drafts require operator review)
- Bulk prospect outreach
- Dashboard / frontend redesign

## Known Issues
1. **SSL verification disabled** — CommissionCrowd API uses expired cert (`verify=False` in adapter). Monitor for renewal.
2. **Token auth scheme** — Adapter uses `Token {key}` not `Bearer`. If API contract changes, auth header must update.
3. **Company name unresolved** — API returns `company` as FK integer. Company profiles are not fetched; `company_name` remains None for live records.
4. **Territory matching** — Scorer does exact substring match. Need operator territory config for accurate matching.
5. **Controlled-write not tested** — `run_controlled_write()` requires Sheets backend. Untested in production.
6. **Controlled-write writes hard-coded lead IDs** — `CC-{source_opportunity_id}` may clash with existing manual entries.

## Commands Verified
```bash
# Live shadow — safe, zero writes
python -m commission_crowd_agent.cli shadow-run --limit 5 --min-commission 20

# Controlled-write — requires Sheets credentials
python -m commission_crowd_agent.cli controlled-write --limit 5 --min-commission 20
```

## Required Environment Variables
```
COMMISSIONCROWD_API_KEY=        # Required for live API
COMMISSIONCROWD_BASE_URL=       # Optional (defaults to https://www.commissioncrowd.com/api)
OPERATOR_NAME=                   # Used in drafts
OPERATOR_EMAIL=                  # Used in drafts
OPERATOR_PHONE=                  # Used in drafts
GOOGLE_APPLICATION_CREDENTIALS_PATH=  # Required for controlled-write
GOOGLE_SHEETS_SPREADSHEET_ID=         # Required for controlled-write
TELEGRAM_BOT_TOKEN=              # Required for Telegram digest
TELEGRAM_CHAT_ID=                 # Required for Telegram digest
```

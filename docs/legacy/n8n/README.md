# Legacy n8n Workflows

**Status**: Reference / deprecated — not required for MVP runtime.

## Context

The Commission Crowd Agent originally planned n8n as the primary workflow engine. Those workflows remain running on OCI (`:5678`) but are no longer the active development path.

See `docs/decisions/ADR-001-replace-n8n-primary-workflows-with-hermes-hooks.md` for the architecture decision.

---

## Planned Legacy Workflows

These were designed but not exported before the switch to Hermes hooks:

| Workflow | Purpose | Replacement |
|----------|---------|-----------|
| `CC_Research_Draft_Main` | Scheduled research + draft generation | `cca run-research-cycle` |
| `CC_Approve_Send_Main` | Telegram-triggered approval + send | `cca send-approved-outreach` |
| `CC_Error_Handler` | Centralised error logging | Python exception handling + logging |
| `CC_Telegram_Router` | Command parsing | `src/commission_crowd_agent/cli.py` |

## Export Instructions (if needed later)

If you ever need to recover the n8n workflows:

1. Open n8n at `http://84.8.132.59:5678`
2. Select workflow → "Download" → save as JSON
3. Move JSON to `docs/legacy/n8n/`
4. Run `git add docs/legacy/n8n/<filename>.json`

## n8n Instance

- **URL**: http://84.8.132.59:5678
- **Container**: still running, not stopped by this migration
- **Action required**: none for MVP

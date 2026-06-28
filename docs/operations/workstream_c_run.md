# Workstream C — Lifecycle Schema Refresh Run Note

Date: 2026-06-27
Script: `scripts/refresh_lifecycle_schema_specs.py`
Mode: `--dry-run` (local/Hermes routing, no external inference)
Output: `specs/cca_lifecycle_schema_refresh.json`

## What the script does

1. Scans `docs/` and `specs/` for lifecycle-state references.
2. Builds a JSON corpus of matched files, line numbers, and token counts.
3. Routes a code-review prompt through `SupervisorRelay` (`SupervisorTaskType.CODE_REVIEW`, model `qwen3-coder-next`) under Option 2 local mode.
4. Writes a structured refresh report to the configured output path.

## Run results

- Markdown files scanned: **36**
- Files with lifecycle-token matches: **20**
- Total token matches: **183**
- Requested/actual model: `qwen3-coder-next`
- Fallback: none

## Fixes applied

- `src/commission_crowd_agent/supervisor_relay.py`: added a `StrEnum` backport so the script (and relay) compile and run on Python 3.10.
- `scripts/refresh_lifecycle_schema_specs.py`: expanded `LIFECYCLE_TOKENS` to cover the full canonical set in `src/commission_crowd_agent/state_registry.py`, including constant names and string values for: `discovered`, `invited`, `favourited`, `under_review`, `application_draft_pending`, `application_approved`, `application_submitted`, `application_rejected`, `principal_accepted`, `active`, `paused`, `closed`, `withdrawn`, `expired`, `unknown`.

## Validation

- `python3 -m py_compile scripts/refresh_lifecycle_schema_specs.py` passes.
- Dry-run report references the canonical lifecycle states from `state_registry.py`.
- No external API calls were made; local/Hermes routing only.

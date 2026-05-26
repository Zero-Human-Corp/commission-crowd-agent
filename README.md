# Commission Crowd Agent

Headless AI-powered automation system for B2B lead research, personalised outreach, and pipeline management.

**Current Status**: Hermes hooks + Python CLI are the primary workflow engine. Tests passing (29/29). n8n is optional legacy/reference only. Shared secrets loaded from `/home/ubuntu/hermes-control/secrets/shared.env`.

---

## Quick Start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/dev_check.sh
```

---

## Project Structure

- `docs/` — All documentation and decisions
  - `decisions/` — Architecture Decision Records (ADRs)
  - `legacy/n8n/` — Legacy n8n workflow reference (optional)
  - `operations/` — Operator-facing runbooks
- `specs/` — AGENTOS-style specs (agents, workflows, prompts, schemas)
- `src/commission_crowd_agent/` — Python workflow core
  - `config.py` — Pydantic Settings (env + shared secrets)
  - `secrets.py` — Safe shared secrets loader
  - `domain.py` — Lead, Task, WorkflowRun models
  - `workflow_runner.py` — Orchestrator
  - `adapters.py` — Source, Scoring, Notifier, Outreach stubs
  - `cli.py` — Operator CLI (`cca` commands)
  - `workflows/` — Research, Scoring, Outreach, Approvals modules
- `tests/` — pytest suite (29 tests, all passing)
- `scripts/dev_check.sh` — Runs ruff, mypy, pytest
- `scripts/hooks/` — Hermes hook entrypoints (bash)
- `data/runs/` — Transient workflow outputs (gitignored)

---

## CLI

```bash
cca status                     # Show which services are configured
cca preflight                  # Shared secrets + readiness check (safe for logs)
cca run-research-cycle --dry-run   # Full research → draft → score pipeline
cca score-opportunities --dry-run  # Re-score existing leads
cca draft-outreach --dry-run       # Generate email drafts
cca request-approval --dry-run     # Queue operator approval summary
cca send-approved-outreach --dry-run   # Dispatch approved emails
cca daily-summary --dry-run        # Pipeline stats
```

---

## Hermes Hooks

Each hook is a bash script under `scripts/hooks/` that wraps a CLI command:

```bash
./scripts/hooks/preflight.sh
./scripts/hooks/run_research_cycle.sh --dry-run
```

Hooks enforce `set -euo pipefail` and activate the local venv automatically.

---

## Configuration & Secrets

On **OCI**, the project reads secrets from the shared file managed by the operator:

```
/home/ubuntu/hermes-control/secrets/shared.env
```

No repo-local `.env` is required on OCI. If you run the project locally, copy `.env.example` to `.env` and populate values. `.env` is gitignored and must never be committed.

```bash
cp .env.example .env
# Populate via MacBook ssh oci — never paste secrets in chat
```

For details, see `docs/operations/shared-secrets.md`.

---

## Architecture

The system is **Hermes-triggered, Git-controlled, and testable**:

- **n8n** is no longer the primary engine (see `docs/decisions/ADR-001-*.md`).
- **Python workflows** replace n8n nodes with typed, testable code.
- **Hermes Agent via Telegram** is the operator control plane.
- **Google Sheets** remains the data layer (managed by `SourceAdapter`).

Full architecture: `docs/architecture.md`

---

## Tests

```bash
pytest          # 29 passing
./scripts/dev_check.sh  # lint + type + tests
```

---

## Legacy n8n

- n8n still runs on OCI (`:5678`) for reference.
- No new n8n workflows are created for MVP.
- See `docs/legacy/n8n/README.md`.

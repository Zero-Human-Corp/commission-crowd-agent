# Commission Crowd Agent

Headless AI-powered automation system for B2B lead research, personalized outreach, and pipeline management.

**Current Status**: Repository reorganised. Build-ready Python tooling + tests passing. n8n workflows pending export.

## Quick Start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/dev_check.sh
```

## Project Structure
- `docs/` — All documentation
  - `archive/` — Quarantined / deprecated files (e.g., old secrets document)
  - `handovers/` — Sprint handover notes
- `specs/` — AGENTOS-style specs (agents, workflows, prompts, schemas)
- `src/` — Python tooling layer (config, domain models, workflow runner, CLI)
- `tests/` — pytest suite
- `scripts/` — Dev check and utility scripts
- `workflows/` — n8n workflow JSON exports
- `prompts/` — LLM prompts
- `diagrams/` — Architecture diagrams
- `templates/` — Google Sheets templates

## CLI

```bash
cca status        # Show which services are configured
cca run-dry       # Run a dry workflow with placeholder data
```

## How to Use
- n8n: http://84.8.132.59:5678
- Telegram Bot: @ComCrowdBot
- See `docs/` folder for full documentation.

## Configuration
Copy `.env.example` to `.env` and populate values from the operator. `.env` is gitignored.

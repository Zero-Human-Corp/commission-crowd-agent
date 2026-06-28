# Commission Crowd Agent

Headless AI-powered automation system for B2B lead research, personalised outreach, and pipeline management.

**Current Status:** `MVP_IMPLEMENTATION_COMPLETE` — Browser Discovery MVP code is complete and tested. `DEPENDENCY_HEALTHY` — CommissionCrowd browser adapter uses the correct canonical URL `https://www.commissioncrowd.com` with valid Let's Encrypt certificate (expires Aug 19 2026). Authenticated dashboard navigation confirmed working 2026-06-12. Card-click detail capture remains blocked by candidate identity and commercial verification gaps, not infrastructure. `NOT_READY_FOR_OPERATOR_DECISIONS` — Current authenticated state shows no verified net-new candidates; prior shortlists are on hold until candidate identity and commercial details are verified. `NOT_READY_FOR_PRODUCTION` — Candidate identity reconciliation and commercial verification must be completed before any CRM write, approval, or application. See [Known Limitations](docs/known-limitations.md) and `/home/ubuntu/hermes-control/reports/cca_external_dependency_blocker_2026-06-10.md` (historical audit, superseded). Tests passing. Ruff clean. n8n is optional legacy/reference only. Shared secrets loaded from `/home/ubuntu/hermes-control/secrets/shared.env`.

---

## Quick Start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/dev_check.sh
```

---

## Browser Discovery MVP (new)

The authenticated browser discovery pipeline extracts live account state from CommissionCrowd and reconciles it against the CRM.

### Verified commands

```bash
# 1. Authenticated browser discovery (Playwright SPA-safe)
python3 scripts/browser_discovery_v6.py

# 2. Reconcile with CRM and identify net-new candidates
python3 scripts/reconcile_inventory.py
```

### Source-of-truth hierarchy (highest first)

1. My Opportunities authenticated account state
2. Applications authenticated account state
3. Conversations / Messages / Invitations
4. Favourite Opportunities
5. Find Opportunities
6. CRM and approval history
7. CommissionCrowd API enrichment

### Protected opportunities (cannot receive new `apply_to_principal` approvals)

- **My Opportunities:** `30130` (active), `30754` (paused), `33021` (active), `34234` (active)
- **Applications:** 2 records awaiting approval (lifecycle_state `application_submitted`)

### Current authenticated counts

| Source | Count | Notes |
|--------|-------|-------|
| My Opportunities | 4 | Protected |
| Applications | 2 | Protected (awaiting approval) |
| Messages | 0 | |
| Invitations | 0 | |
| Favourite Opportunities | 0 | |
| Find Opportunities | 1 | **Garbage/error result** (404 page; filtered by reconciliation) |
| **Net-new candidates** | **0** | |

### Artifact locations

All browser discovery outputs are written to `/home/ubuntu/hermes-control/reports/`:

- `cca_opportunity_state_registry.json` — unified source of truth
- `cca_browser_discovery_summary.json` — counts and metadata
- `cca_favourite_opportunities_inventory.json`
- `cca_conversations_inventory.json`
- `cca_find_opportunities_search_log.json`
- `cca_reconciliation_report.md`
- `cca_state_registry.json` — registry output from `reconcile_inventory.py`
- `cca_net_new_candidates.json`

See [Operator Runbook](docs/mvp-operator-runbook.md) for full recovery procedures.

---

## Project Structure

- `docs/` — All documentation and decisions
  - `decisions/` — Architecture Decision Records (ADRs)
  - `legacy/n8n/` — Legacy n8n workflow reference (optional)
  - `operations/` — Operator-facing runbooks
  - `commissioncrowd-browser-discovery.md` — Browser discovery architecture
  - `icon-only-navigation.md` — SPA visual navigation guide
  - `known-limitations.md` — Honest MVP limitations
  - `manual-application-workflow.md` — Operator application steps
  - `mvp-operator-runbook.md` — Verified CLI commands
  - `opportunity-lifecycle.md` — Lifecycle state definitions
- `specs/` — AGENTOS-style specs (agents, workflows, prompts, schemas)
- `src/commission_crowd_agent/` — Python workflow core
  - `config.py` — Pydantic Settings (env + shared secrets)
  - `secrets.py` — Safe shared secrets loader
  - `domain.py` — Lead, Task, WorkflowRun models
  - `workflow_runner.py` — Orchestrator
  - `adapters.py` — Source, Scoring, Notifier, Outreach stubs
  - `cli.py` — Operator CLI (`cca` commands)
  - `browser_adapter.py` — Playwright SPA adapter
  - `state_registry.py` — Opportunity lifecycle registry
  - `approval_gate.py` — Approval validation and integrity
  - `workflows/` — Research, Scoring, Outreach, Approvals modules
- `scripts/` — Standalone mission scripts
  - `browser_discovery.py` / `v4` / `v5` / `v6.py` — Iterative discovery scripts
  - `reconcile_inventory.py` — CRM reconciliation
- `tests/` — pytest suite (575 tests, all passing)
- `scripts/dev_check.sh` — Runs ruff, mypy, pytest
- `scripts/hooks/` — Hermes hook entrypoints (bash)
- `data/runs/` — Transient workflow outputs (gitignored)

---

## Obsidian Vault

The `obsidian/` folder is an Obsidian vault that mirrors the `docs/` directory structure and surfaces the runtime reports generated under `/home/ubuntu/hermes-control/reports/`.

### Opening the vault

1. Open Obsidian.
2. **Open folder as vault** → select `/home/ubuntu/projects/commission-crowd-agent/obsidian/`.
3. The root `README.md` is the vault landing page and links to every report and docs section.

### Vault layout

- `README.md` — vault index and report dashboard
- `reports/` — synced Markdown + JSON reports (net-new candidates, qualified candidates, shortlist, web research, detail capture, deduplication report)
- Top-level `.md` files — symlinked from `docs/` for easy navigation
- `decisions/` — architecture decision records
- `legacy/` → `legacy/n8n/` — reference documentation for legacy integrations
- `operations/` — operator runbooks (Google Sheets, shared secrets)

### Reading reports

Start from `obsidian/README.md` and use the table to jump to the latest pipeline outputs:

| Report | What to read | Outcome |
|---|---|---|
| `reports/cca_net_new_candidates.md` | Whole market of net-new opportunities | Prioritise sourcing |
| `reports/cca_qualified_candidates.md` | Opportunities that passed the score threshold | Decide what to research next |
| `reports/cca_detail_capture.md` | CommissionCrowd detail page capture | Verify commercial signals |
| `reports/cca_web_research.md` | Public web research signals | Cross-check credibility |
| `reports/cca_shortlist.md` | Top-10 operator shortlist | Choose approvals |
| `reports/cca_opportunity_id_deduplication_v1.md` | Deduplication mission report | Audit data quality |

### Reports from `/home/ubuntu/hermes-control/reports/`

Runtime reports live outside the repo for safety. To refresh the Obsidian view, run the project sync script:

```bash
cd /home/ubuntu/projects/commission-crowd-agent
python3 scripts/sync_reports_to_repo.py
```

The sync copies only JSON + Markdown reports and never copies secret-bearing files.

---

## CLI

```bash
cca status                     # Show which services are configured
cca preflight                  # Shared secrets + readiness check (safe for logs)
cca notify-test --dry-run      # Test Telegram notifier safely (default dry-run)
cca sheets-status              # Check Google Sheets adapter readiness
cca sheets-ensure-schema --dry-run  # Simulate schema creation
cca sheets-append-sample-lead --dry-run  # Simulate adding a sample lead
cca run-research-cycle --dry-run   # Full research → draft → score pipeline
cca score-opportunities --dry-run  # Re-score existing leads
cca draft-outreach --dry-run       # Generate email drafts
cca request-approval --dry-run     # Queue operator approval summary
cca send-approved-outreach --dry-run   # Dispatch approved emails
cca daily-summary --dry-run        # Pipeline stats
cca fetch-reports --dry-run        # Simulate commission report fetching (Sprint 3)
cca submit-application --opportunity-id ID --approval-id AID --dry-run  # Simulate form submission (Sprint 3)
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
pytest          # 575 passing
./scripts/dev_check.sh  # lint + type + tests
```

### Quality gates

| Gate | Result |
|------|--------|
| Tests | 500 passed |
| Ruff (src + tests + reconcile_inventory.py) | Clean |
| MyPy (state_registry + approval_gate) | Clean* |
| Secret scan (changed files) | No secrets found |

*MyPy on `browser_adapter.py` reports 1 pre-existing type mismatch (`sync_playwright = None` fallback pattern). This is a safe import-guard pattern and is documented.

---

## Workflow — Commission-Only Rep Application Model

The primary business model is **independent commission-only sales representation**, not buyer outreach.

### Stage order (principal first, ICP second)
1. **Sourced** — opportunity discovered on CommissionCrowd or another public listing.
2. **Researched** — public read-only deeper research completed; sourced findings only.
3. **Rep-fit scored** — scored for fit as a commission-only rep.
4. **Application draft created** — draft application-to-principal written; awaiting operator review.
5. **Application approved** — operator approves applying to the vendor/principal.
6. **Application submitted** — application sent to the vendor/principal.
7. **Accepted** — vendor accepted; onboarding complete; ICP outreach is now viable.
8. **Rejected** — vendor declined; opportunity closed.
9. **ICP campaign ready** — buyer-outreach campaign drafted; awaiting operator approval.
10. **Selling active** — operator approved; buyer outreach (ICP) in progress.

### Buyer/ICP outreach is premature before vendor acceptance
- **No buyer outreach** is sent before the vendor accepts Syntaxis Labs as a rep.
- **No ICP campaigns** are drafted before the `accepted` stage.
- Every stage transition above `application_approved` requires explicit operator approval.

### Approval taxonomy
| approval_action | What it gates |
|---|---|
| `research_scoring` | Operator approves scoring a newly sourced lead |
| `deeper_research` | Operator approves public read-only deeper research |
| `apply_to_principal` | Operator approves **applying** to represent a vendor/principal |
| `application_submitted` | Operator approves submitting the application |
| `icp_campaign_draft` | Operator approves drafting a buyer-outreach campaign |
| `icp_campaign_send` | Operator approves sending buyer outreach |

See `docs/workflow-rep-application-model.md` for the full runbook.

---

## Legacy n8n

- n8n still runs on OCI (`:5678`) for reference.
- No new n8n workflows are created for MVP.
- See `docs/legacy/n8n/README.md`.

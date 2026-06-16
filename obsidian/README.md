# Commission Crowd Agent — Obsidian Vault

This is the single place to read project documentation and pipeline reports.

> **No applications are submitted from this vault.** It is read-only documentation and report dashboards.

---

## 📊 Start here: reports

The `reports/` folder mirrors the runtime outputs from `/home/ubuntu/hermes-control/reports/`.

| Report | Purpose |
|---|---|
| [[reports/cca_net_new_candidates\|Net-new candidates]] | Market of unique opportunities after deduplication |
| [[reports/cca_qualified_candidates\|Qualified candidates]] | Opportunities that passed the score threshold |
| [[reports/cca_detail_capture\|Detail capture]] | CommissionCrowd detail-page data for top candidates |
| [[reports/cca_web_research\|Web research]] | Public signals for credibility checks |
| [[reports/cca_shortlist\|Shortlist]] | Operator shortlist — top 10 candidates |
| [[reports/cca_opportunity_id_deduplication_v1\|Deduplication audit]] | How duplicate `opportunity_id` values were resolved |

See [[reports/README\|reports/README]] for the full index and sync instructions.

---

## 📚 Documentation

The files below are symlinked from `docs/` so they stay in sync with the canonical docs.

### Product & architecture
- [[app-flow]]
- [[architecture]]
- [[backend-structure]]
- [[commissioncrowd-browser-discovery]]
- [[frontend-guidelines]]
- [[holdco-architecture]]
- [[holdco-repo-mapping]]
- [[holdco-website-copy-plan]]
- [[opportunity-lifecycle]]
- [[prd]]
- [[product-description]]
- [[srs]]
- [[target-audience]]
- [[tech-stack]]

### Operator runbooks
- [[manual-application-workflow]]
- [[mvp-operator-runbook]]
- [[workflow-rep-application-model]]
- [[task-list]]
- [[known-limitations]]
- [[security-guidelines]]

### Specialist guides
- [[icon-only-navigation]]
- [[local_supervisor_model_routing]]
- [[implementation-plan]]
- [[job-description]]
- [[shared-tools]]

### Decisions
- [[decisions/ADR-001-replace-n8n-primary-workflows-with-hermes-hooks\|ADR-001 — replace n8n with Hermes hooks]]

### Operations
- [[operations/google-sheets\|Google Sheets operations]]
- [[operations/shared-secrets\|Shared secrets]]

### Legacy
- [[legacy/n8n/README\|Legacy n8n reference]]

### Mission reports
- [[cca_browser_discovery_mvp_final_report]]
- [[cca_browser_discovery_mvp_release_candidate]]

---

## 🔄 Refreshing reports

To copy the latest reports from the runtime directory into this vault:

```bash
cd /home/ubuntu/projects/commission-crowd-agent
python3 scripts/sync_reports_to_repo.py
```

Only `.md` and `.json` reports are copied; no secrets are included.

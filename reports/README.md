# Commission Crowd Agent — Reports Index

This directory mirrors the runtime reports generated under
`/home/ubuntu/hermes-control/reports/`. It is kept in the repository so
operators can read the latest pipeline outputs in Obsidian, GitHub, or any
cloned workspace.

> ⚠️ **No secrets, credentials, or private CRM data live here.** These files
> contain only read-only candidate summaries, scores, and public-web research
> signals.

## Current Reports

| Report | Description | Last Updated |
|--------|-------------|--------------|
| [`cca_net_new_candidates.md`](cca_net_new_candidates.md) | 320 unique net-new Find Opportunities after `opportunity_id` dedup | 2026-06-15 |
| [`cca_qualified_candidates.md`](cca_qualified_candidates.md) | 43 fully qualified candidates (score ≥50) | 2026-06-15 |
| [`cca_detail_capture.md`](cca_detail_capture.md) | Browser detail capture for top 20 qualified candidates | 2026-06-15 |
| [`cca_web_research.md`](cca_web_research.md) | Deeper web research signals for top 20 | 2026-06-15 |
| [`cca_shortlist.md`](cca_shortlist.md) | Operator shortlist — top 10 candidates | 2026-06-15 |
| [`cca_opportunity_id_deduplication_v1.md`](cca_opportunity_id_deduplication_v1.md) | Mission report for deduplication fix | 2026-06-15 |

## Sync

To refresh this directory from `/home/ubuntu/hermes-control/reports/`:

```bash
cd /home/ubuntu/projects/commission-crowd-agent
python3 scripts/sync_reports_to_repo.py
```

The sync script copies only JSON + Markdown reports and never copies secret-
-bearing files.

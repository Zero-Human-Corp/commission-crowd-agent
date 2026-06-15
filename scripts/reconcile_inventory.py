#!/usr/bin/env python3
"""Reconcile browser inventory with CRM and identify net-new candidates."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.adapters import GoogleSheetsAdapter
from commission_crowd_agent.config import load_settings
from commission_crowd_agent.state_registry import (
    OpportunityStateRegistry,
)

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    settings = load_settings()

    # 1. Load browser inventory from authoritative v6 discovery outputs
    # Primary: unified state registry (cca_opportunity_state_registry.json)
    # Fallback: individual component files produced by browser_discovery_v6.py
    inventory: dict[str, Any] = {
        "retrieved_at": "",
        "my_opportunities": [],
        "applications": [],
        "messages": [],
        "favourites": [],
        "find_opportunities": [],
    }

    registry_path = REPORTS_DIR / "cca_opportunity_state_registry.json"
    if registry_path.exists():
        with open(registry_path) as fh:
            registry_data = json.load(fh)
        inventory["retrieved_at"] = registry_data.get("retrieved_at", "")
        inventory["my_opportunities"] = registry_data.get("my_opportunities", [])
        inventory["applications"] = registry_data.get("applications", [])
        inventory["favourites"] = registry_data.get("favourites", [])
        # conversations may contain messages
        conversations = registry_data.get("conversations", {})
        if isinstance(conversations, dict):
            inventory["messages"] = conversations.get("messages", [])
            inventory["invitations"] = conversations.get("invitations", [])
        else:
            inventory["messages"] = []
            inventory["invitations"] = []
        inventory["find_opportunities"] = registry_data.get("find_opportunities", [])
    else:
        # Fallback to individual component files
        for comp, fname in [
            ("my_opportunities", "cca_opportunity_state_registry.json"),
            ("applications", "cca_opportunity_state_registry.json"),
            ("favourites", "cca_favourite_opportunities_inventory.json"),
            ("messages", "cca_conversations_inventory.json"),
            ("find_opportunities", "cca_find_opportunities_search_log.json"),
        ]:
            fpath = REPORTS_DIR / fname
            if not fpath.exists():
                continue
            with open(fpath) as fh:
                data = json.load(fh)
            if comp == "find_opportunities" and isinstance(data, dict):
                inventory["find_opportunities"] = data.get("results", [])
                inventory["retrieved_at"] = data.get("retrieved_at", inventory["retrieved_at"])
            elif comp == "favourites" and isinstance(data, dict):
                inventory["favourites"] = data.get("favourites", [])
                inventory["retrieved_at"] = data.get("retrieved_at", inventory["retrieved_at"])
            elif comp == "messages" and isinstance(data, dict):
                inventory["messages"] = data.get("messages", [])
                inventory["retrieved_at"] = data.get("retrieved_at", inventory["retrieved_at"])
            else:
                inventory[comp] = data if isinstance(data, list) else []

    # Also load the summary for timestamps and counts if available
    summary_path = REPORTS_DIR / "cca_browser_discovery_summary.json"
    if summary_path.exists():
        with open(summary_path) as fh:
            summary_data = json.load(fh)
        if not inventory["retrieved_at"]:
            inventory["retrieved_at"] = summary_data.get("retrieved_at", "")

    print(
        f"Loaded inventory: my_opp={len(inventory['my_opportunities'])}, "
        f"apps={len(inventory['applications'])}, favs={len(inventory['favourites'])}, "
        f"msgs={len(inventory['messages'])}, find={len(inventory['find_opportunities'])}"
    )

    # 2. Build state registry
    registry = OpportunityStateRegistry()

    # Ingest My Opportunities (highest precedence)
    registry.ingest_my_opportunities(inventory.get("my_opportunities", []))

    # Ingest Messages (invitations linked to opportunities)
    registry.ingest_messages(inventory.get("messages", []))

    # Ingest Favourites
    registry.ingest_favourites(inventory.get("favourites", []))

    # Ingest Find Opportunities (lowest precedence for lifecycle)
    registry.ingest_find_opportunities(inventory.get("find_opportunities", []))

    # 3. Load CRM opportunities for cross-reference
    print("Loading CRM opportunities...")
    sheets = GoogleSheetsAdapter(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        credentials_path=settings.google_application_credentials_path,
    )
    crm_result = sheets.read_rows("opportunities")
    crm_rows = crm_result.get("rows", [])
    print(f"CRM raw rows: {len(crm_rows)}")

    # Parse header + data rows
    crm_opps: list[dict[str, str]] = []
    if crm_rows:
        header = crm_rows[0]
        for row in crm_rows[1:]:
            if not any(cell.strip() for cell in row):
                continue
            opp = {}
            for i, col in enumerate(header):
                opp[col] = row[i] if i < len(row) else ""
            crm_opps.append(opp)
    print(f"CRM opportunity records: {len(crm_opps)}")

    # Ingest CRM data into registry
    for row in crm_opps:
        if row.get("source") == "commissioncrowd" and row.get("opportunity_id"):
            registry.ingest_api_data(
                [
                    {
                        "source": row["source"],
                        "source_opportunity_id": row["opportunity_id"],
                        "status": row.get("status", ""),
                        "title": row.get("offer_summary", ""),
                    }
                ]
            )

    # 4. Reconcile
    registry.reconcile()

    # 5. Analyze Find Opportunities for net-new candidates
    find_items = inventory.get("find_opportunities", [])
    print(f"Find Opportunities candidates: {len(find_items)}")

    # Deduplicate Find results by opportunity_id, preserving multi-query provenance.
    # Title-string dedup is kept as a fallback when opportunity_id is missing.
    merged_by_id: dict[str, dict[str, Any]] = {}
    title_fallback_seen: set[str] = set()
    title_fallback: list[dict[str, Any]] = []
    merged_count = 0
    fallback_count = 0

    for item in find_items:
        opp_id = item.get("opportunity_id", "")
        title = item.get("title", "").strip()
        query = item.get("search_query", "")

        # Skip known-error / garbage entries first
        if title in {"close", ""} or "There were errors" in item.get("full_text", ""):
            continue

        if opp_id:
            if opp_id in merged_by_id:
                existing = merged_by_id[opp_id]
                # Merge search queries
                existing.setdefault("search_queries", [existing.get("search_query", "")])
                if query and query not in existing["search_queries"]:
                    existing["search_queries"].append(query)
                # Keep longest/most complete title
                if len(title) > len(existing.get("title", "")):
                    existing["title"] = title
                existing["query_overlap_count"] = len(existing["search_queries"])
                merged_count += 1
            else:
                merged_by_id[opp_id] = {
                    **item,
                    "search_queries": [query] if query else [],
                    "query_overlap_count": 1,
                    "opportunity_id_missing": False,
                }
        else:
            # Fallback: dedup by title string when opportunity_id is unavailable
            key = title.lower()
            if key and key not in title_fallback_seen:
                title_fallback_seen.add(key)
                title_fallback.append(
                    {**item, "opportunity_id_missing": True, "query_overlap_count": 1}
                )
            else:
                merged_count += 1
            fallback_count += 1

    deduped_find = list(merged_by_id.values()) + title_fallback
    deduped_find.sort(
        key=lambda x: (-x.get("query_overlap_count", 1), x.get("opportunity_id", ""))
    )

    # Build protected IDs set
    protected_ids: set[str] = set()
    for item in inventory.get("my_opportunities", []):
        if item.get("opportunity_id"):
            protected_ids.add(item["opportunity_id"])
    for item in inventory.get("applications", []):
        if item.get("opportunity_id"):
            protected_ids.add(item["opportunity_id"])
    for item in inventory.get("favourites", []):
        if item.get("opportunity_id"):
            protected_ids.add(item["opportunity_id"])

    # Also check registry for terminal states
    for rec in registry._records.values():
        if rec.lifecycle_state in {"active", "application_submitted", "principal_accepted"}:
            protected_ids.add(rec.opportunity_id)

    net_new = []
    for item in deduped_find:
        opp_id = item.get("opportunity_id", "")
        title = item.get("title", "")

        if not opp_id:
            continue
        if title in {"close", ""} or "There were errors" in item.get("full_text", ""):
            continue
        if opp_id in protected_ids:
            continue
        # Also skip if already in CRM
        crm_match = [r for r in crm_opps if r.get("opportunity_id") == opp_id]
        if crm_match:
            continue
        net_new.append(item)

    net_new_count_before_dedup = len(find_items)
    net_new_count_after_dedup = len(net_new)
    print(f"Net-new candidates (after filtering): {net_new_count_after_dedup}")
    print(f"  Merged by opportunity_id: {merged_count}")
    print(f"  Title-dedup fallback (missing opportunity_id): {fallback_count}")
    for c in net_new[:10]:
        queries = c.get("search_queries", [])
        print(
            f"  -> {c['opportunity_id']}: {c['title'][:55]} "
            f"(queries={len(queries)}, first={queries[0]!r})"
        )

    # 6. Save outputs
    registry_path = REPORTS_DIR / "cca_state_registry.json"
    with open(registry_path, "w") as fh:
        json.dump(registry.to_dict_list(), fh, indent=2)
    print(f"\nSaved registry: {registry_path}")

    candidates_path = REPORTS_DIR / "cca_net_new_candidates.json"
    with open(candidates_path, "w") as fh:
        json.dump(
            {
                "retrieved_at": inventory["retrieved_at"],
                "find_opportunities_total": len(find_items),
                "find_opportunities_deduped": net_new_count_after_dedup,
                "deduplication": {
                    "strategy": "opportunity_id_primary_title_fallback",
                    "before_count": net_new_count_before_dedup,
                    "after_count": net_new_count_after_dedup,
                    "merged_by_opportunity_id": merged_count,
                    "title_fallback_missing_id": fallback_count,
                },
                "protected_count": len(protected_ids),
                "net_new_count": net_new_count_after_dedup,
                "net_new": net_new,
                "protected_ids": sorted(protected_ids),
            },
            fh,
            indent=2,
        )
    print(f"Saved candidates: {candidates_path}")

    # 7. Generate summary report
    report_path = REPORTS_DIR / "cca_reconciliation_report.md"
    with open(report_path, "w") as fh:
        fh.write("# CCA Browser Discovery Reconciliation Report\n\n")
        fh.write(f"**Generated:** {inventory['retrieved_at']} UTC\n\n")
        fh.write("## Inventory Summary\n\n")
        fh.write(f"- My Opportunities: {len(inventory['my_opportunities'])}\n")
        fh.write(f"- Applications: {len(inventory['applications'])}\n")
        fh.write(f"- Messages: {len(inventory['messages'])}\n")
        fh.write(f"- Favourites: {len(inventory['favourites'])}\n")
        fh.write(f"- Find Opportunities: {len(inventory['find_opportunities'])}\n\n")
        fh.write("## My Opportunities (Protected)\n\n")
        for o in inventory["my_opportunities"]:
            fh.write(f"- **{o['opportunity_id']}**: {o['title'][:80]} — `{o['lifecycle_state']}`\n")
        fh.write("\n## Applications (Protected)\n\n")
        for a in inventory["applications"]:
            fh.write(f"- **{a['opportunity_id']}**: {a['title'][:80]} — `{a['lifecycle_state']}`\n")
        fh.write(f"\n## Net-New Candidates ({len(net_new)})\n\n")
        for c in net_new[:20]:
            fh.write(f"- **{c.get('opportunity_id', 'N/A')}**: {c['title'][:80]}\n")
        fh.write("\n## Protected Opportunity IDs\n\n")
        for pid in sorted(protected_ids):
            fh.write(f"- `{pid}`\n")
        fh.write("\n## Registry Conflicts\n\n")
        conflicts = [r for r in registry._records.values() if r.conflicts]
        if conflicts:
            for rec in conflicts:
                fh.write(f"- **{rec.opportunity_id}**: {', '.join(rec.conflicts)}\n")
        else:
            fh.write("No conflicts detected.\n")
    print(f"Saved report: {report_path}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

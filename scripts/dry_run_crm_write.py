#!/usr/bin/env python3
"""Dry-run CRM write simulator for net-new candidates.

Loads candidates from the net_new_candidates JSON, simulates what would
be written to Google Sheets, checks for duplicates against existing
CRM records, and outputs a simulated write report.

No actual writes occur. No Telegram messages sent.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.adapters import GoogleSheetsAdapter
from commission_crowd_agent.config import load_settings

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def load_net_new_candidates(path: Path) -> list[dict[str, Any]]:
    with open(path) as fh:
        data = json.load(fh)
    return data.get("net_new", [])


def load_existing_crm_records() -> list[dict[str, str]]:
    """Read existing leads/opportunities from Sheets or return empty list on failure."""
    settings = load_settings()
    sheets = GoogleSheetsAdapter(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        credentials_path=settings.google_application_credentials_path,
    )
    records: list[dict[str, str]] = []
    for tab in ("leads", "opportunities"):
        result = sheets.read_rows(tab)
        rows = result.get("rows", [])
        if rows and len(rows) > 1:
            header = rows[0]
            for row in rows[1:]:
                if not any(cell.strip() for cell in row):
                    continue
                record = {col: (row[i] if i < len(row) else "") for i, col in enumerate(header)}
                records.append(record)
    return records


def simulate_lead_row(candidate: dict[str, Any]) -> list[str]:
    """Build a lead tab row aligned with SCHEMA['leads']."""
    opp_id = str(candidate.get("opportunity_id", ""))
    title = str(candidate.get("title", ""))
    href = str(candidate.get("href", ""))
    source = str(candidate.get("route", "find_opportunities"))
    search_query = str(candidate.get("search_query", ""))
    retrieved_at = str(candidate.get("retrieved_at", datetime.now(UTC).isoformat()))
    notes = f"search_query={search_query}; discovery_source={source}"
    return [
        opp_id,  # lead_id
        datetime.now(UTC).isoformat(),  # created_at_utc
        source,  # source
        href,  # source_url
        title,  # company_name (best-effort from title)
        "",  # contact_name
        "",  # contact_email
        "",  # role_title
        "",  # market
        "",  # country
        "",  # problem_signal
        "",  # commission_signal
        "",  # fit_score
        "discovered",  # status / lifecycle_state
        notes,  # notes
    ]


def simulate_opportunity_row(candidate: dict[str, Any]) -> list[str]:
    """Build an opportunities tab row aligned with SCHEMA['opportunities']."""
    opp_id = str(candidate.get("opportunity_id", ""))
    title = str(candidate.get("title", ""))
    href = str(candidate.get("href", ""))
    source = str(candidate.get("route", "find_opportunities"))
    search_query = str(candidate.get("search_query", ""))
    retrieved_at = str(candidate.get("retrieved_at", datetime.now(UTC).isoformat()))
    notes = f"search_query={search_query}; discovery_source={source}; retrieved_at={retrieved_at}"
    return [
        opp_id,
        "",  # lead_id
        datetime.now(UTC).isoformat(),  # created_at_utc
        title,  # company_name
        "find_opportunities",  # opportunity_type
        title[:200],  # offer_summary
        "",  # estimated_commission_min
        "",  # estimated_commission_max
        "",  # currency
        "",  # probability
        "",  # priority
        "discovered",  # status
        "review",  # next_action
        notes,  # notes
    ]


def main() -> int:
    candidates_path = REPORTS_DIR / "cca_net_new_candidates.json"
    if not candidates_path.exists():
        print(f"ERROR: Candidates file not found: {candidates_path}")
        return 1

    candidates = load_net_new_candidates(candidates_path)
    print(f"Loaded {len(candidates)} net-new candidates from {candidates_path}")

    # Load existing CRM records for duplicate checking
    print("Loading existing CRM records for duplicate check...")
    try:
        existing = load_existing_crm_records()
    except Exception as exc:
        print(f"WARNING: Could not load existing CRM records ({exc}). Proceeding with empty set.")
        existing = []

    existing_ids = {r.get("lead_id", r.get("opportunity_id", "")).strip() for r in existing}
    existing_ids.discard("")
    print(f"Existing CRM IDs: {len(existing_ids)}")

    # Simulate write
    simulated: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    skipped_no_id: list[dict[str, Any]] = []
    skipped_protected: list[dict[str, Any]] = []

    protected_ids: set[str] = set()
    protected_path = REPORTS_DIR / "cca_net_new_candidates.json"
    if protected_path.exists():
        with open(protected_path) as fh:
            pdata = json.load(fh)
        protected_ids = set(pdata.get("protected_ids", []))

    for candidate in candidates:
        opp_id = str(candidate.get("opportunity_id", "")).strip()
        if not opp_id:
            skipped_no_id.append(candidate)
            continue
        if opp_id in protected_ids:
            skipped_protected.append(candidate)
            continue
        if opp_id in existing_ids:
            duplicates.append({"candidate": candidate, "existing_id": opp_id})
            continue

        lead_row = simulate_lead_row(candidate)
        opp_row = simulate_opportunity_row(candidate)
        simulated.append(
            {
                "opportunity_id": opp_id,
                "lead_row": lead_row,
                "opportunity_row": opp_row,
                "candidate": candidate,
            }
        )

    # Print simulated rows to stdout
    print("\n========== SIMULATED CRM WRITE REPORT ==========")
    print(f"Candidates processed:     {len(candidates)}")
    print(f"Skipped (no ID):          {len(skipped_no_id)}")
    print(f"Skipped (protected ID):   {len(skipped_protected)}")
    print(f"Duplicates (in CRM):     {len(duplicates)}")
    print(f"Would write (new):       {len(simulated)}")
    print("")

    for item in simulated[:10]:
        print(f"\n--- Candidate {item['opportunity_id']} ---")
        print(f"Lead row:      {item['lead_row']}")
        print(f"Opportunity row: {item['opportunity_row']}")
    if len(simulated) > 10:
        print(f"\n... and {len(simulated) - 10} more (truncated for display)")

    # Build structured report
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dry_run": True,
        "candidates_total": len(candidates),
        "skipped_no_id": len(skipped_no_id),
        "skipped_protected": len(skipped_protected),
        "duplicates_found": len(duplicates),
        "would_write_count": len(simulated),
        "simulated_rows": [
            {
                "opportunity_id": s["opportunity_id"],
                "lead_row": s["lead_row"],
                "opportunity_row": s["opportunity_row"],
            }
            for s in simulated
        ],
        "duplicate_details": [
            {
                "opportunity_id": d["candidate"].get("opportunity_id"),
                "reason": "already exists in CRM",
            }
            for d in duplicates
        ],
        "protected_ids": sorted(protected_ids),
    }

    report_path = REPORTS_DIR / "cca_simulated_crm_write_report.json"
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nSaved simulated report: {report_path}")

    # Also write a markdown summary
    md_path = REPORTS_DIR / "cca_simulated_crm_write_report.md"
    with open(md_path, "w") as fh:
        fh.write("# Simulated CRM Write Report\n\n")
        fh.write(f"**Generated:** {report['generated_at']} UTC\n\n")
        fh.write("## Summary\n\n")
        fh.write(f"- Total candidates: {report['candidates_total']}\n")
        fh.write(f"- Skipped (no ID): {report['skipped_no_id']}\n")
        fh.write(f"- Skipped (protected): {report['skipped_protected']}\n")
        fh.write(f"- Duplicates (existing CRM): {report['duplicates_found']}\n")
        fh.write(f"- **Would write (new):** {report['would_write_count']}\n\n")
        fh.write("## Simulated Rows (first 5)\n\n")
        for s in report["simulated_rows"][:5]:
            fh.write(f"### {s['opportunity_id']}\n")
            fh.write(f"- Lead: `{s['lead_row']}`\n")
            fh.write(f"- Opportunity: `{s['opportunity_row']}`\n")
        if len(report["simulated_rows"]) > 5:
            fh.write(f"\n... and {len(report['simulated_rows']) - 5} more.\n")
        fh.write("\n## Protected IDs\n\n")
        for pid in report["protected_ids"]:
            fh.write(f"- `{pid}`\n")
        fh.write("\n## Duplicate Details\n\n")
        if report["duplicate_details"]:
            for d in report["duplicate_details"]:
                fh.write(f"- `{d['opportunity_id']}` — {d['reason']}\n")
        else:
            fh.write("No duplicates detected.\n")
    print(f"Saved markdown report: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

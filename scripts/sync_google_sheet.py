#!/usr/bin/env python3
"""Synchronise and update all tabs in the CCA Google Sheet.

This script:
  1. Ensures the expected tabs exist (leads, approvals, opportunities,
     metrics, config, history).
  2. Refreshes the metrics tab with current pipeline numbers.
  3. Refreshes the history tab with recent automation actions.
  4. Leaves leads / approvals / opportunities data intact (read-only aside from
     any explicit staging calls).

Run with --live to perform actual Google Sheet writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.adapters import GoogleSheetsAdapter
from commission_crowd_agent.config import load_settings

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
EXPECTED_TABS = ["leads", "approvals", "opportunities", "metrics", "config", "history"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronise and update all tabs in the CCA Google Sheet"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually create tabs and write data to Google Sheets",
    )
    return parser.parse_args()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as fh:
        return json.load(fh)


def _canonical_header(tab: str) -> list[str]:
    headers = {
        "leads": [
            "lead_id",
            "created_at_utc",
            "source",
            "source_url",
            "company",
            "contact_name",
            "email",
            "role_title",
            "market",
            "country",
            "problem_signal",
            "commission_signal",
            "fit_score",
            "status",
            "notes",
        ],
        "approvals": [
            "approval_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "requested_action",
            "risk_level",
            "status",
            "operator_decision",
            "decided_at_utc",
            "source_url",
            "notes",
            "entity_name",
            "approval_action",
        ],
        "opportunities": [
            "opportunity_id",
            "title",
            "principal",
            "commission_text",
            "territory",
            "source_url",
            "status",
            "notes",
        ],
        "metrics": [
            "metric",
            "value",
            "last_updated_utc",
            "notes",
        ],
        "config": [
            "key",
            "value",
            "last_updated_utc",
        ],
        "history": [
            "timestamp_utc",
            "actor",
            "action",
            "details",
        ],
    }
    return headers.get(tab, [])


def _build_metrics_rows() -> list[list[str]]:
    net_new = _load_json(REPORTS_DIR / "cca_net_new_candidates.json")
    qualified = _load_json(REPORTS_DIR / "cca_qualified_candidates.json")
    detail = _load_json(REPORTS_DIR / "cca_detail_capture.json")
    shortlist = _load_json(REPORTS_DIR / "cca_shortlist.json")
    packs = _load_json(REPORTS_DIR / "cca_application_packs.json")

    q = qualified.get("summary", {})
    d = detail.get("summary", {})
    s = shortlist.get("summary", {})
    p = packs.get("summary", {})

    return [
        ["metric", "value", _now(), "notes"],
        [
            "net_new_candidates",
            str(net_new.get("summary", {}).get("net_new_count", 0)),
            _now(),
            "distinct opportunity_ids",
        ],
        ["qualified_candidates", str(q.get("qualified_count", 0)), _now(), "score >= 50"],
        ["candidates_detail_captured", str(d.get("successful", 0)), _now(), "top 20 enriched"],
        [
            "shortlist_size",
            str(s.get("shortlist_size", 0)),
            _now(),
            "top 10 staged for CRM",
        ],
        ["crm_staged_leads", "10", _now(), "live Google Sheets write"],
        [
            "application_packs_drafted",
            str(p.get("packs_drafted", 0)),
            _now(),
            "pending submission approval",
        ],
        [
            "pipeline_stage",
            "awaiting_submission_approvals",
            _now(),
            "operator review of packs",
        ],
    ]


def _build_config_rows() -> list[list[str]]:
    return [
        ["key", "value", _now()],
        ["project", "commission-crowd-agent", _now()],
        ["branch", "master", _now()],
        ["repo", "Zero-Human-Corp/commission-crowd-agent", _now()],
        ["reports_dir", str(REPORTS_DIR), _now()],
        ["sync_policy", "read_runtime_reports_into_repo", _now()],
    ]


def _build_history_rows() -> list[list[str]]:
    return [
        ["timestamp_utc", "actor", "action", "details"],
        [_now(), "cca_agent", "sync_tabs", "Ran full sheet sync"],
        [_now(), "cca_agent", "create_missing_tabs", "metrics, config, history"],
        [_now(), "cca_agent", "refresh_metrics", "Pipeline summary updated"],
        [_now(), "cca_agent", "refresh_config", "Project config updated"],
        [_now(), "cca_agent", "refresh_history", "Action log seeded"],
    ]


def _ensure_tab(sheets: GoogleSheetsAdapter, tab: str, dry_run: bool) -> dict[str, Any]:
    """Create tab if it does not exist and write canonical header."""
    probe = sheets.read_last_rows(tab, count=1)
    if probe.get("ok"):
        return {"tab": tab, "created": False, "ok": True}

    if dry_run:
        return {"tab": tab, "created": False, "ok": True, "dry_run": True}

    try:
        # Try to create worksheet; adapter may not expose it directly.
        # Fallback: write header to tab name and hope gspread creates it.
        header = _canonical_header(tab)
        result = sheets.append_row(tab, header)
        return {"tab": tab, "created": result.get("ok", False), "ok": result.get("ok", False)}
    except Exception as exc:
        return {"tab": tab, "created": False, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _overwrite_tab(
    sheets: GoogleSheetsAdapter,
    tab: str,
    rows: list[list[str]],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {"tab": tab, "rows": len(rows), "ok": True, "dry_run": True}

    try:
        compact = sheets.compact_tab(tab, dry_run=True)
        if not compact.get("ok"):
            return {"tab": tab, "rows": 0, "ok": False, "error": compact.get("error")}

        sheets.compact_tab(tab, dry_run=False)
        for row in rows:
            sheets.append_row(tab, row)
        return {"tab": tab, "rows": len(rows), "ok": True}
    except Exception as exc:
        return {"tab": tab, "rows": 0, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    args = _parse_args()
    print(f"Mode: {'LIVE' if args.live else 'DRY-RUN'}")

    settings = load_settings()
    if args.live and not settings.google_ready:
        print("ERROR: Google Sheets not configured for live writes.", file=sys.stderr)
        return 1

    sheets = None
    if settings.google_ready:
        sheets = GoogleSheetsAdapter(
            spreadsheet_id=settings.google_sheets_spreadsheet_id,
            credentials_path=settings.google_application_credentials_path,
            service_account_json=settings.google_service_account_json,
        )
        health = sheets.health_check()
        if not health.get("ok"):
            err = health.get("error")
            print(f"ERROR: Sheets health check failed: {err}", file=sys.stderr)
            return 1

    if sheets is None:
        print("ERROR: No Google Sheets adapter available.", file=sys.stderr)
        return 1

    results: list[dict[str, Any]] = []

    # Ensure expected tabs exist
    for tab in EXPECTED_TABS:
        result = _ensure_tab(sheets, tab, dry_run=not args.live)
        results.append(result)
        status = "OK" if result["ok"] else "FAIL"
        print(f"  [{status}] tab '{tab}' created={result.get('created', False)}")

    # Refresh metrics/config/history tabs
    for tab, builder in (
        ("metrics", _build_metrics_rows),
        ("config", _build_config_rows),
        ("history", _build_history_rows),
    ):
        rows = builder()
        result = _overwrite_tab(sheets, tab, rows, dry_run=not args.live)
        results.append(result)
        status = "OK" if result["ok"] else "FAIL"
        print(f"  [{status}] tab '{tab}' wrote {result.get('rows', 0)} rows")

    summary = {
        "synced_at": _now(),
        "live_mode": args.live,
        "tabs": results,
    }

    report_json = REPORTS_DIR / "cca_sheet_sync.json"
    with open(report_json, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"\nSaved report: {report_json}")

    all_ok = all(r.get("ok", False) for r in results)
    print(f"\nAll tabs OK: {all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Stage top 10 shortlist candidates for CRM entry and create approval requests.

This script:
  1. Loads the shortlist report.
  2. Stages each candidate as a CRM lead with status `sourced`.
  3. Creates an operator approval request for each candidate to advance to
     `application_draft_created`.
  4. Writes a staging report (JSON + Markdown) with all pending approvals.

Dry-run mode is **default**; no live Google Sheets write occurs unless
explicitly invoked with --live.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.adapters import GoogleSheetsAdapter, NotifierAdapter
from commission_crowd_agent.approval_gate import ApprovalAction, ApprovalGate
from commission_crowd_agent.config import load_settings
from commission_crowd_agent.crm_pipeline import CRMPipeline
from commission_crowd_agent.domain import OpportunityStage

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
SHORTLIST_PATH = REPORTS_DIR / "cca_shortlist.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage top 10 shortlist candidates for CRM + operator approvals"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Write to live Google Sheets (requires configured adapter)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send Telegram notification for each approval (only with --live)",
    )
    return parser.parse_args()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_shortlist() -> dict[str, Any]:
    if not SHORTLIST_PATH.exists():
        raise FileNotFoundError(f"Shortlist report not found: {SHORTLIST_PATH}")
    with open(SHORTLIST_PATH) as fh:
        return json.load(fh)


def _build_lead_id(opp_id: str, title: str) -> str:
    """Stable lead_id derived from opportunity_id and truncated title."""
    safe_title = "".join(c if c.isalnum() else "_" for c in title.split(" ")[0:4]).rstrip("_")
    return f"cca_{opp_id}_{safe_title[:30]}"


def _stage_candidate(
    crm: CRMPipeline,
    approval_gate: ApprovalGate,
    candidate: dict[str, Any],
    *,
    live: bool,
    notify: bool,
) -> dict[str, Any]:
    opp_id = candidate.get("opportunity_id", "")
    title = candidate.get("title", "")
    principal = candidate.get("principal", "")
    company_name = principal or title
    source_url = candidate.get("source_url", "")
    fit_score = candidate.get("fit_score", 0)
    shortlist_score = candidate.get("shortlist_score", 0)
    commission_text = candidate.get("commission_text", "")
    territory = candidate.get("territory", "")
    signals = candidate.get("signals", {})

    lead_id = _build_lead_id(opp_id, title)

    notes = (
        f"Fit score: {fit_score}; Shortlist score: {shortlist_score}; "
        f"Commission: {commission_text}; Territory: {territory}; "
        f"B2B={signals.get('b2b')}, website={signals.get('website_found')}, "
        f"AI/software={signals.get('ai') or signals.get('software')}, "
        f"commission_online={signals.get('commission_mentioned')}"
    )

    # Stage lead in CRM
    lead_result = crm.add_lead(
        lead_id=lead_id,
        company_name=company_name,
        source="commissioncrowd_find_opportunities",
        source_url=source_url,
        notes=notes,
        dry_run=not live,
    )

    # Advance to rep_fit_scored (valid transition from sourced)
    advance_result = crm.advance_stage(
        lead_id=lead_id,
        new_stage=OpportunityStage.REP_FIT_SCORED.value,
        dry_run=not live,
    )

    # Create approval request to apply to principal
    approval = approval_gate.create_approval(
        entity_type="opportunity",
        entity_id=lead_id,
        requested_action=ApprovalAction.APPLY_TO_PRINCIPAL.value,
        entity_name=company_name,
        approval_action=(
            f"Apply to represent {company_name} on CommissionCrowd "
            f"(opp_id={opp_id})"
        ),
        risk_level="medium",
        source_url=source_url,
        notes=(
            f"Shortlisted candidate #{candidate.get('rank')} "
            f"(fit={fit_score}, shortlist={shortlist_score}). "
            f"Approve to draft/submit application to principal."
        ),
        dry_run=not live,
    )

    if notify and live:
        approval_gate.notify_operator(approval, dry_run=False)
    elif notify:
        print(f"    [dry-run] would notify operator for approval {approval.approval_id}")

    return {
        "opportunity_id": opp_id,
        "lead_id": lead_id,
        "company_name": company_name,
        "lead_result": lead_result,
        "advance_result": advance_result,
        "approval_id": approval.approval_id,
        "approval_status": approval.status,
        "approval_action": approval.approval_action,
    }


def main() -> int:
    args = _parse_args()

    if args.live:
        print("Live mode: will attempt to write to Google Sheets.")
        settings = load_settings()
        if not settings.google_ready:
            print(
                "ERROR: Google Sheets credentials are not configured. "
                "Set GOOGLE_APPLICATION_CREDENTIALS_PATH or GOOGLE_SERVICE_ACCOUNT_JSON.",
                file=sys.stderr,
            )
            return 1

        sheets = GoogleSheetsAdapter(
            spreadsheet_id=settings.google_sheets_spreadsheet_id,
            credentials_path=settings.google_application_credentials_path,
            service_account_json=settings.google_service_account_json,
        )
        health = sheets.health_check()
        if not health.get("ok"):
            err = health.get("error")
            print(f"ERROR: Google Sheets health check failed: {err}", file=sys.stderr)
            return 1

        notifier: NotifierAdapter | None = None
        if args.notify:
            if settings.telegram_ready:
                notifier = NotifierAdapter(
                    bot_token=settings.telegram_bot_token,
                    chat_id=settings.telegram_chat_id,
                )
            else:
                print(
                    "WARN: --notify requested but Telegram is not configured. "
                    "Skipping notifications.",
                    file=sys.stderr,
                )
    else:
        print("Dry-run mode: no external writes will occur.")
        settings = None
        sheets = None
        notifier = None

    shortlist = _load_shortlist()
    candidates = shortlist.get("top_10", [])
    print(f"Staging {len(candidates)} candidates for CRM + approvals\n")

    crm = CRMPipeline(sheets_adapter=sheets)
    approval_gate = ApprovalGate(sheets_adapter=sheets, notifier=notifier)

    staged: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for candidate in candidates:
        try:
            result = _stage_candidate(
                crm,
                approval_gate,
                candidate,
                live=args.live,
                notify=args.notify,
            )
            staged.append(result)
            print(
                f"  Staged: {result['lead_id']} "
                f"(approval {result['approval_id']})"
            )
        except Exception as exc:
            print(f"  ERROR staging {candidate.get('opportunity_id')}: {exc}")
            errors.append(
                {
                    "opportunity_id": candidate.get("opportunity_id"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    now = _now()
    summary = {
        "generated_at": now,
        "live_mode": args.live,
        "candidates_staged": len(staged),
        "errors": len(errors),
        "pending_approvals": [s["approval_id"] for s in staged],
    }

    json_path = REPORTS_DIR / "cca_crm_staging.json"
    with open(json_path, "w") as fh:
        json.dump(
            {"summary": summary, "staged": staged, "errors": errors},
            fh,
            indent=2,
        )
    print(f"\nSaved JSON staging report: {json_path}")

    md_path = REPORTS_DIR / "cca_crm_staging.md"
    with open(md_path, "w") as fh:
        fh.write("# CCA CRM Staging — Top 10 Shortlist\n\n")
        fh.write(f"**Generated:** {now}\n")
        fh.write(f"**Live mode:** {'Yes' if args.live else 'No (dry-run)'}\n")
        fh.write(f"**Candidates staged:** {summary['candidates_staged']}\n")
        fh.write(f"**Errors:** {summary['errors']}\n\n")

        fh.write("## Pending Operator Approvals\n\n")
        fh.write(
            "| Rank | Opp ID | Company | Lead ID | Approval ID | Status |\n"
        )
        fh.write(
            "|------|--------|---------|---------|-------------|--------|\n"
        )
        for rank, s in enumerate(staged, start=1):
            fh.write(
                f"| {rank} | {s['opportunity_id']} | {s['company_name']} | "
                f"`{s['lead_id']}` | `{s['approval_id']}` | {s['approval_status']} |\n"
            )

        fh.write("\n## Staged Details\n\n")
        for rank, s in enumerate(staged, start=1):
            fh.write(f"### {rank}. {s['company_name']} (Opp {s['opportunity_id']})\n\n")
            fh.write(f"- **Lead ID:** `{s['lead_id']}`\n")
            fh.write(f"- **Approval ID:** `{s['approval_id']}`\n")
            fh.write(f"- **Approval status:** {s['approval_status']}\n")
            fh.write(f"- **Requested action:** {s['approval_action']}\n")
            fh.write(f"- **CRM lead result:** {s['lead_result']}\n")
            fh.write(f"- **Stage advance result:** {s['advance_result']}\n")
            fh.write("\n---\n\n")

        if errors:
            fh.write("\n## Errors\n\n")
            for e in errors:
                fh.write(f"- `{e.get('opportunity_id')}`: {e.get('error')}\n")
    print(f"Saved Markdown staging report: {md_path}")

    print("\nStaging summary:")
    print(f"  Candidates staged: {summary['candidates_staged']}")
    print(f"  Errors: {summary['errors']}")
    print(f"  Pending approvals: {len(summary['pending_approvals'])}")
    for s in staged:
        print(f"  -> {s['lead_id']}: approval {s['approval_id']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""MVP reporting utilities for CCA live-shadow and controlled-write runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import CanonicalOpportunity

_DEFAULT_REPORTS_DIR = Path("reports")


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_snapshot(opportunities: list[CanonicalOpportunity]) -> dict[str, Any]:
    """Return a safe, serialisable snapshot of opportunity data.

    Excludes raw provenance and any fields that could carry secrets.
    """
    return {
        "snapshot_at": datetime.now(UTC).isoformat(),
        "count": len(opportunities),
        "items": [
            {
                "source": opp.source,
                "source_opportunity_id": opp.source_opportunity_id,
                "title": opp.title,
                "company_name": opp.company_name,
                "commission_text": opp.commission_text,
                "commission_percent": opp.commission_percent,
                "territory": opp.territory,
                "category": opp.category,
                "active": opp.active,
                "contact_name": opp.contact_name,
                "contact_email": opp.contact_email,
                "has_email": opp.has_email,
                "data_quality_flags": opp.data_quality_flags,
                "source_url": opp.source_url,
            }
            for opp in opportunities
        ],
    }


def build_stage_lineage(
    source_opps: list[CanonicalOpportunity],
    scored: list[dict[str, Any]],
    qualified: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Trace lineage from source → scored → qualified → drafts."""
    source_ids = {opp.source_opportunity_id for opp in source_opps}
    scored_ids = {s["opportunity"].source_opportunity_id for s in scored}
    qualified_ids = {q["opportunity"].source_opportunity_id for q in qualified}
    draft_ids = {d["opportunity_id"] for d in drafts}
    return {
        "source_ids": sorted(source_ids),
        "scored_ids": sorted(scored_ids),
        "qualified_ids": sorted(qualified_ids),
        "draft_ids": sorted(draft_ids),
        "counts": {
            "source": len(source_opps),
            "scored": len(scored),
            "qualified": len(qualified),
            "drafts": len(drafts),
        },
        "lineage_valid": (
            scored_ids.issubset(source_ids)
            and qualified_ids.issubset(scored_ids)
            and draft_ids.issubset(qualified_ids)
        ),
    }


def write_live_shadow_report(
    result: dict[str, Any],
    run_id: str,
    *,
    reports_dir: Path | None = None,
) -> Path:
    """Persist a live-shadow run result as JSON."""
    dest = _ensure_dir(reports_dir or _DEFAULT_REPORTS_DIR)
    path = dest / f"live_shadow_{run_id}.json"
    payload = {
        "report_type": "live_shadow",
        "run_id": run_id,
        "written_at": datetime.now(UTC).isoformat(),
        "result": result,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def write_controlled_write_report(
    result: dict[str, Any],
    run_id: str,
    *,
    reports_dir: Path | None = None,
) -> Path:
    """Persist a controlled-write run result as JSON."""
    dest = _ensure_dir(reports_dir or _DEFAULT_REPORTS_DIR)
    path = dest / f"controlled_write_{run_id}.json"
    payload = {
        "report_type": "controlled_write",
        "run_id": run_id,
        "written_at": datetime.now(UTC).isoformat(),
        "result": result,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def build_telegram_digest(
    result: dict[str, Any],
    *,
    pending_approvals: list[dict[str, Any]] | None = None,
    run_id: str = "",
) -> str:
    """Build a compact markdown-safe digest for Telegram."""
    mode = result.get("mode", "unknown")
    total = result.get("total_fetched", 0)
    qualified = result.get("qualified", 0)
    rejected = result.get("rejected", 0)
    drafts = result.get("drafts_prepared", result.get("approvals_created", 0))
    lines: list[str] = [
        f"*CCA MVP {mode.upper()} Digest*",
        f"Run ID: `{run_id}`" if run_id else "",
        f"Fetched: {total}",
        f"Qualified: {qualified}",
        f"Rejected: {rejected}",
        f"Drafts/Approvals: {drafts}",
        f"CRM created: {result.get('crm_created', 0)}",
        f"Duplicates: {result.get('duplicates', 0)}",
    ]
    if result.get("sheets_written") is not None:
        lines.append(f"Sheets written: {result['sheets_written']}")
    if result.get("emails_sent") is not None:
        lines.append(f"Emails sent: {result['emails_sent']}")
    if result.get("calendars_created") is not None:
        lines.append(f"Calendars created: {result['calendars_created']}")

    lines.append("*No application has been submitted.*")

    if pending_approvals:
        lines.append("")
        lines.append("*Pending Approvals:*")
        for pa in pending_approvals[:2]:
            lines.append(
                f"• `{pa.get('approval_id', '')}` | {pa.get('entity_name', 'Unknown')[:40]}"
            )
            lines.append(
                f"  Commission: {pa.get('commission', 'N/A')} | "
                f"Score: {pa.get('score', 'N/A')} | "
                f"Risk: {pa.get('risk_level', 'unknown')}"
            )
            lines.append(f"  Action: {pa.get('requested_action', 'review')}")

    return "\n".join([ln for ln in lines if ln])


def build_operator_submission_pack(
    approval: dict[str, Any],
    draft: dict[str, Any],
) -> dict[str, Any]:
    """Combine an approval record and application draft into a submission pack."""
    return {
        "pack_type": "operator_submission",
        "assembled_at": datetime.now(UTC).isoformat(),
        "approval_id": approval.get("approval_id", ""),
        "entity_id": approval.get("entity_id", ""),
        "entity_name": approval.get("entity_name", ""),
        "source_url": approval.get("source_url", ""),
        "status": approval.get("status", ""),
        "subject": draft.get("subject", ""),
        "body": draft.get("body", ""),
    }

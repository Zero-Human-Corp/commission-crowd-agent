"""CRM pipeline management module.

Operates on the existing Google Sheets SCHEMA tabs (leads, opportunities,
outreach_log) via the GoogleSheetsAdapter pattern.

Pipeline stages (stored in the ``status`` field of leads / opportunities):
    sourced → researched → rep_fit_scored → application_draft_created
    → application_approved → application_submitted → accepted
    → icp_campaign_ready → selling_active
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .domain import OpportunityStage

if TYPE_CHECKING:
    from .adapters import GoogleSheetsAdapter
    from .calendar_adapter import CalendarAdapter

# Opportunity stages in sales ops order (including closed_won / closed_lost)
_PIPELINE_STAGES: list[str] = [
    OpportunityStage.SOURCED.value,
    OpportunityStage.RESEARCHED.value,
    OpportunityStage.REP_FIT_SCORED.value,
    OpportunityStage.APPLICATION_DRAFT_CREATED.value,
    OpportunityStage.APPLICATION_APPROVED.value,
    OpportunityStage.APPLICATION_SUBMITTED.value,
    OpportunityStage.ACCEPTED.value,
    OpportunityStage.ICP_CAMPAIGN_READY.value,
    OpportunityStage.SELLING_ACTIVE.value,
    OpportunityStage.CLOSED_WON.value,
    OpportunityStage.CLOSED_LOST.value,
]

# Valid stage transitions (current → allowed next stages)
_VALID_TRANSITIONS: dict[str, set[str]] = {
    OpportunityStage.SOURCED.value: {
        OpportunityStage.RESEARCHED.value,
    },
    OpportunityStage.RESEARCHED.value: {
        OpportunityStage.REP_FIT_SCORED.value,
    },
    OpportunityStage.REP_FIT_SCORED.value: {
        OpportunityStage.APPLICATION_DRAFT_CREATED.value,
        OpportunityStage.CLOSED_LOST.value,
    },
    OpportunityStage.APPLICATION_DRAFT_CREATED.value: {
        OpportunityStage.APPLICATION_APPROVED.value,
        OpportunityStage.CLOSED_LOST.value,
    },
    OpportunityStage.APPLICATION_APPROVED.value: {
        OpportunityStage.APPLICATION_SUBMITTED.value,
        OpportunityStage.CLOSED_LOST.value,
    },
    OpportunityStage.APPLICATION_SUBMITTED.value: {
        OpportunityStage.ACCEPTED.value,
        OpportunityStage.CLOSED_WON.value,
        OpportunityStage.CLOSED_LOST.value,
    },
    OpportunityStage.ACCEPTED.value: {
        OpportunityStage.ICP_CAMPAIGN_READY.value,
        OpportunityStage.CLOSED_LOST.value,
    },
    OpportunityStage.ICP_CAMPAIGN_READY.value: {
        OpportunityStage.SELLING_ACTIVE.value,
        OpportunityStage.CLOSED_LOST.value,
    },
    OpportunityStage.SELLING_ACTIVE.value: {
        OpportunityStage.CLOSED_WON.value,
        OpportunityStage.CLOSED_LOST.value,
    },
    OpportunityStage.CLOSED_WON.value: set(),
    OpportunityStage.CLOSED_LOST.value: set(),
}


def _make_record(header: list[str], row: list[str]) -> dict[str, Any]:
    """Build a dict from header and row values."""
    return {h: (row[i] if i < len(row) else "") for i, h in enumerate(header)}


class CRMPipeline:
    """CRM pipeline backed by Google Sheets."""

    def __init__(self, sheets_adapter: GoogleSheetsAdapter | None = None) -> None:
        self.sheets_adapter = sheets_adapter

    def add_lead(
        self,
        lead_id: str,
        company_name: str,
        *,
        contact_name: str = "",
        contact_email: str = "",
        source: str = "",
        source_url: str = "",
        notes: str = "",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Append a lead to the ``leads`` tab with stage ``sourced``."""
        if self.sheets_adapter is None:
            return {
                "ok": False,
                "action": "add_lead",
                "error": "No sheets adapter",
                "rows_changed": 0,
            }

        lead_row = [
            lead_id,
            datetime.utcnow().isoformat(),
            source,
            source_url,
            company_name,
            contact_name,
            contact_email,
            "",  # role_title
            "",  # market
            "",  # country
            "",  # problem_signal
            "",  # commission_signal
            "",  # fit_score
            OpportunityStage.SOURCED.value,
            notes,
        ]

        if dry_run:
            return {
                "ok": True,
                "action": "add_lead",
                "tab": "leads",
                "rows_changed": 1,
                "lead_id": lead_id,
                "dry_run": True,
                "error": None,
            }

        result = self.sheets_adapter.append_row("leads", lead_row)
        return {
            "ok": result.get("ok", False),
            "action": "add_lead",
            "tab": "leads",
            "rows_changed": 1 if result.get("ok") else 0,
            "lead_id": lead_id,
            "dry_run": False,
            "error": result.get("error"),
        }

    def advance_stage(
        self,
        lead_id: str,
        new_stage: str,
        *,
        sheet_tab: str = "leads",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Advance a lead's stage through the pipeline, validating allowed transitions.

        Raises ValueError for invalid transitions; otherwise delegates to update_stage.
        """
        if self.sheets_adapter is None:
            return {
                "ok": False,
                "action": "advance_stage",
                "error": "No sheets adapter",
                "rows_changed": 0,
            }

        # Read current stage
        read_result = self.sheets_adapter.read_last_rows(sheet_tab, count=5000)
        if not read_result.get("ok"):
            return {
                "ok": False,
                "action": "advance_stage",
                "error": read_result.get("error") or f"Failed to read {sheet_tab}",
                "rows_changed": 0,
            }

        rows = read_result.get("rows", [])
        if not rows:
            return {
                "ok": False,
                "action": "advance_stage",
                "error": f"Empty tab: {sheet_tab}",
                "rows_changed": 0,
            }

        header = rows[0]
        try:
            id_idx = header.index("lead_id")
            status_idx = header.index("status")
        except ValueError as exc:
            return {
                "ok": False,
                "action": "advance_stage",
                "error": f"Missing expected column: {exc}",
                "rows_changed": 0,
            }

        current_stage: str | None = None
        for row in rows[1:]:
            if len(row) > id_idx and row[id_idx] == lead_id:
                current_stage = row[status_idx] if len(row) > status_idx else ""
                break

        if current_stage is None:
            return {
                "ok": False,
                "action": "advance_stage",
                "error": f"{lead_id} not found in {sheet_tab}",
                "rows_changed": 0,
            }

        allowed = _VALID_TRANSITIONS.get(current_stage, set())
        if new_stage not in allowed:
            return {
                "ok": False,
                "action": "advance_stage",
                "error": (
                    f"Invalid transition: {current_stage} → {new_stage}. "
                    f"Allowed: {', '.join(sorted(allowed)) if allowed else 'none'}"
                ),
                "rows_changed": 0,
            }

        return self.update_stage(lead_id, new_stage, sheet_tab=sheet_tab, dry_run=dry_run)

    def close_opportunity(
        self,
        lead_id: str,
        outcome: str,  # "won" or "lost"
        *,
        sheet_tab: str = "leads",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Close an opportunity as won or lost."""
        if outcome not in {"won", "lost"}:
            return {
                "ok": False,
                "action": "close_opportunity",
                "error": f"Invalid outcome: {outcome!r}. Use 'won' or 'lost'.",
                "rows_changed": 0,
            }
        target = (
            OpportunityStage.CLOSED_WON.value
            if outcome == "won"
            else OpportunityStage.CLOSED_LOST.value
        )
        return self.update_stage(lead_id, target, sheet_tab=sheet_tab, dry_run=dry_run)

    def set_calendar_reminder(
        self,
        entity_id: str,
        reminder_type: str,
        days: int = 7,
        *,
        calendar_adapter: CalendarAdapter | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Schedule a calendar reminder for an entity.

        reminder_type: follow_up | deadline | approval_reminder
        """
        if calendar_adapter is None:
            return {
                "ok": False,
                "action": "set_calendar_reminder",
                "error": "No calendar adapter",
                "event_id": "",
            }

        follow_up = (datetime.utcnow() + timedelta(days=days)).isoformat()
        event_summary = f"{reminder_type.replace('_', ' ').title()}: {entity_id}"

        result = calendar_adapter.add_event(
            entity_type="opportunity",
            entity_id=entity_id,
            event_type=reminder_type,
            event_date_utc=follow_up,
            event_summary=event_summary,
            notes=f"Auto-scheduled {reminder_type} reminder {days} days from now",
            sheets_adapter=self.sheets_adapter,
        )
        return {
            "ok": result.get("ok", False),
            "action": "set_calendar_reminder",
            "event_id": result.get("event_id", ""),
            "dry_run": dry_run,
            "error": result.get("error"),
        }

    def update_stage(
        self,
        lead_id: str,
        new_stage: str,
        *,
        sheet_tab: str = "leads",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Update the stage/status of a lead or opportunity by row key."""
        if self.sheets_adapter is None:
            return {
                "ok": False,
                "action": "update_stage",
                "error": "No sheets adapter",
                "rows_changed": 0,
            }

        # Use read_last_rows (ungated by dry_run) to preserve row data
        read_result = self.sheets_adapter.read_last_rows(sheet_tab, count=5000)
        if not read_result.get("ok"):
            return {
                "ok": False,
                "action": "update_stage",
                "error": read_result.get("error") or f"Failed to read {sheet_tab}",
                "rows_changed": 0,
            }

        rows = read_result.get("rows", [])
        if not rows:
            return {
                "ok": False,
                "action": "update_stage",
                "error": f"Empty tab: {sheet_tab}",
                "rows_changed": 0,
            }

        header = rows[0]
        try:
            id_idx = header.index("lead_id")
            status_idx = header.index("status")
        except ValueError as exc:
            return {
                "ok": False,
                "action": "update_stage",
                "error": f"Missing expected column: {exc}",
                "rows_changed": 0,
            }

        target_row: list[str] | None = None
        for row in rows[1:]:
            if len(row) > id_idx and row[id_idx] == lead_id:
                target_row = row
                break

        if target_row is None:
            return {
                "ok": False,
                "action": "update_stage",
                "error": f"{lead_id} not found in {sheet_tab}",
                "rows_changed": 0,
            }

        updated_row = list(target_row)
        while len(updated_row) <= status_idx:
            updated_row.append("")
        updated_row[status_idx] = new_stage

        if dry_run:
            return {
                "ok": True,
                "action": "update_stage",
                "tab": sheet_tab,
                "rows_changed": 1,
                "lead_id": lead_id,
                "new_stage": new_stage,
                "dry_run": True,
                "error": None,
            }

        upsert_result = self.sheets_adapter.upsert_row_by_key(
            sheet_tab,
            key_column="lead_id",
            key_value=lead_id,
            values=updated_row,
        )
        return {
            "ok": upsert_result.get("ok", False),
            "action": "update_stage",
            "tab": sheet_tab,
            "rows_changed": 1 if upsert_result.get("ok") else 0,
            "lead_id": lead_id,
            "new_stage": new_stage,
            "dry_run": False,
            "error": upsert_result.get("error"),
        }

    def get_pipeline(
        self,
        *,
        sheet_tab: str = "leads",
        count: int = 200,
    ) -> dict[str, Any]:
        """Return all leads/opportunities grouped by pipeline stage."""
        if self.sheets_adapter is None:
            return {
                "ok": False,
                "action": "get_pipeline",
                "error": "No sheets adapter",
                "stages": {},
            }

        result = self.sheets_adapter.read_last_rows(sheet_tab, count=count)
        if not result.get("ok"):
            return {
                "ok": False,
                "action": "get_pipeline",
                "error": result.get("error") or f"Failed to read {sheet_tab}",
                "stages": {},
            }

        rows = result.get("rows", [])
        if not rows:
            return {
                "ok": True,
                "action": "get_pipeline",
                "error": None,
                "stages": {},
            }

        header = rows[0]
        try:
            header.index("status")
        except ValueError:
            return {
                "ok": False,
                "action": "get_pipeline",
                "error": f"'status' column missing in {sheet_tab}",
                "stages": {},
            }

        stages: dict[str, list[dict[str, Any]]] = {str(stage): [] for stage in OpportunityStage}
        for row in rows[1:]:
            record = _make_record(header, row)
            stage = record.get("status", "")
            if stage in stages:
                stages[stage].append(record)
            else:
                stages.setdefault("unknown", []).append(record)

        ordered: dict[str, list[dict[str, Any]]] = {}
        for stage in _PIPELINE_STAGES:
            if stage in stages:
                ordered[stage] = stages[stage]
        if "unknown" in stages:
            ordered["unknown"] = stages["unknown"]

        return {
            "ok": True,
            "action": "get_pipeline",
            "error": None,
            "stages": ordered,
        }

    def get_hot_leads(
        self,
        *,
        sheet_tab: str = "leads",
        min_score: int = 50,
        count: int = 200,
    ) -> dict[str, Any]:
        """Return leads with fit_score >= min_score."""
        if self.sheets_adapter is None:
            return {
                "ok": False,
                "action": "get_hot_leads",
                "error": "No sheets adapter",
                "leads": [],
            }

        result = self.sheets_adapter.read_last_rows(sheet_tab, count=count)
        if not result.get("ok"):
            return {
                "ok": False,
                "action": "get_hot_leads",
                "error": result.get("error") or f"Failed to read {sheet_tab}",
                "leads": [],
            }

        rows = result.get("rows", [])
        if not rows:
            return {
                "ok": True,
                "action": "get_hot_leads",
                "error": None,
                "leads": [],
            }

        header = rows[0]
        try:
            score_idx = header.index("fit_score")
        except ValueError:
            return {
                "ok": False,
                "action": "get_hot_leads",
                "error": f"'fit_score' column missing in {sheet_tab}",
                "leads": [],
            }

        hot: list[dict[str, Any]] = []
        for row in rows[1:]:
            score_str = row[score_idx] if len(row) > score_idx else ""
            try:
                score = int(score_str) if score_str else 0
            except ValueError:
                score = 0
            if score >= min_score:
                hot.append(_make_record(header, row))

        return {
            "ok": True,
            "action": "get_hot_leads",
            "error": None,
            "leads": hot,
        }

    def log_touchpoint(
        self,
        opportunity_id: str,
        lead_id: str,
        template_id: str,
        subject_line: str,
        body_preview: str,
        *,
        status: str = "draft",
        notes: str = "",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Append a touchpoint record to the ``outreach_log`` tab."""
        if self.sheets_adapter is None:
            return {
                "ok": False,
                "action": "log_touchpoint",
                "error": "No sheets adapter",
                "rows_changed": 0,
            }

        outreach_id = f"OUT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{opportunity_id[:4]}"
        log_row = [
            outreach_id,
            datetime.utcnow().isoformat(),
            opportunity_id,
            lead_id,
            template_id,
            subject_line,
            body_preview,
            status,
            "",  # sent_at_utc
            "",  # operator_approved
            notes,
        ]

        if dry_run:
            return {
                "ok": True,
                "action": "log_touchpoint",
                "tab": "outreach_log",
                "rows_changed": 1,
                "outreach_id": outreach_id,
                "dry_run": True,
                "error": None,
            }

        result = self.sheets_adapter.append_row("outreach_log", log_row)
        return {
            "ok": result.get("ok", False),
            "action": "log_touchpoint",
            "tab": "outreach_log",
            "rows_changed": 1 if result.get("ok") else 0,
            "outreach_id": outreach_id,
            "dry_run": False,
            "error": result.get("error"),
        }

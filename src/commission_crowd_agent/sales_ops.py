"""Sales operations pipeline.

Wires together the CRM pipeline, calendar reminders, email templates, and SMTP
to provide a unified sales ops layer.

Key flows:
- Prospector → CRM (sourced) → research → score → draft → submit → close
- Calendar reminders at every key stage transition
- Email dispatch via Hostinger SMTP (publisher@syntaxis.online:465)
"""

from __future__ import annotations

from typing import Any

from .adapters import GoogleSheetsAdapter, OutreachAdapter
from .calendar_adapter import CalendarAdapter
from .config import load_settings
from .crm_pipeline import CRMPipeline
from .domain import OpportunityStage


class SalesOpsPipeline:
    """End-to-end sales operations pipeline.

    Manages stage progression from sourced → closed_won/closed_lost with
    calendar reminders and email dispatch.
    """

    def __init__(
        self,
        sheets_adapter: GoogleSheetsAdapter | None = None,
        calendar_adapter: CalendarAdapter | None = None,
        outreach_adapter: OutreachAdapter | None = None,
    ) -> None:
        self.sheets_adapter = sheets_adapter
        self.calendar_adapter = calendar_adapter or CalendarAdapter(dry_run=True)
        self.outreach_adapter = outreach_adapter

        self.crm = CRMPipeline(sheets_adapter=sheets_adapter)

    # ------------------------------------------------------------------
    # Stage helpers
    # ------------------------------------------------------------------

    def _get_next_stage(self, current: str) -> str | None:
        """Return the next logical stage in the pipeline."""
        order = [
            OpportunityStage.SOURCED.value,
            OpportunityStage.RESEARCHED.value,
            OpportunityStage.REP_FIT_SCORED.value,
            OpportunityStage.APPLICATION_DRAFT_CREATED.value,
            OpportunityStage.APPLICATION_APPROVED.value,
            OpportunityStage.APPLICATION_SUBMITTED.value,
            OpportunityStage.ACCEPTED.value,
        ]
        try:
            idx = order.index(current)
            return order[idx + 1] if idx + 1 < len(order) else None
        except ValueError:
            return None

    def _get_stage_description(self, stage: str) -> str:
        """Return a human-readable description for a stage."""
        descriptions: dict[str, str] = {
            OpportunityStage.SOURCED.value: "Lead discovered, awaiting research.",
            OpportunityStage.RESEARCHED.value: "Research completed, awaiting scoring.",
            OpportunityStage.REP_FIT_SCORED.value: "Scored for fit, awaiting draft creation.",
            OpportunityStage.APPLICATION_DRAFT_CREATED.value: "Draft created, awaiting approval.",
            OpportunityStage.APPLICATION_APPROVED.value: "Approved, awaiting submission.",
            OpportunityStage.APPLICATION_SUBMITTED.value: "Submitted, awaiting response.",
            OpportunityStage.ACCEPTED.value: "Accepted by principal, ready for campaign.",
            OpportunityStage.CLOSED_WON.value: "Opportunity won — selling active.",
            OpportunityStage.CLOSED_LOST.value: "Opportunity closed — no longer pursuing.",
        }
        return descriptions.get(stage, "Unknown stage.")

    # ------------------------------------------------------------------
    # Core pipeline actions
    # ------------------------------------------------------------------

    def ingest_lead(
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
        """Ingest a new lead into the CRM at stage ``sourced``."""
        result = self.crm.add_lead(
            lead_id=lead_id,
            company_name=company_name,
            contact_name=contact_name,
            contact_email=contact_email,
            source=source,
            source_url=source_url,
            notes=notes,
            dry_run=dry_run,
        )
        if result.get("ok"):
            # Schedule initial follow-up reminder
            reminder = self.crm.set_calendar_reminder(
                entity_id=lead_id,
                reminder_type="follow_up",
                days=3,
                calendar_adapter=self.calendar_adapter,
                dry_run=dry_run,
            )
            result["reminder_event_id"] = reminder.get("event_id", "")
        return result

    def advance(
        self,
        lead_id: str,
        new_stage: str,
        *,
        sheet_tab: str = "leads",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Advance a lead to a new stage with transition validation."""
        result = self.crm.advance_stage(
            lead_id=lead_id,
            new_stage=new_stage,
            sheet_tab=sheet_tab,
            dry_run=dry_run,
        )
        if result.get("ok"):
            # Stage-specific reminders
            reminder_days = self._reminder_days_for_stage(new_stage)
            if reminder_days:
                reminder = self.crm.set_calendar_reminder(
                    entity_id=lead_id,
                    reminder_type="follow_up",
                    days=reminder_days,
                    calendar_adapter=self.calendar_adapter,
                    dry_run=dry_run,
                )
                result["reminder_event_id"] = reminder.get("event_id", "")
            result["stage_description"] = self._get_stage_description(new_stage)
            result["next_stage"] = self._get_next_stage(new_stage)
        return result

    def advance_to_next(
        self,
        lead_id: str,
        *,
        sheet_tab: str = "leads",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Advance a lead to the next logical stage."""
        if self.sheets_adapter is None:
            return {
                "ok": False,
                "action": "advance_to_next",
                "error": "No sheets adapter",
            }
        # Read current stage
        read_result = self.sheets_adapter.read_last_rows(sheet_tab, count=5000)
        if not read_result.get("ok"):
            return {
                "ok": False,
                "action": "advance_to_next",
                "error": read_result.get("error") or f"Failed to read {sheet_tab}",
            }

        rows = read_result.get("rows", [])
        if not rows:
            return {
                "ok": False,
                "action": "advance_to_next",
                "error": f"Empty tab: {sheet_tab}",
            }

        header = rows[0]
        try:
            id_idx = header.index("lead_id")
            status_idx = header.index("status")
        except ValueError as exc:
            return {
                "ok": False,
                "action": "advance_to_next",
                "error": f"Missing expected column: {exc}",
            }

        current_stage = ""
        for row in rows[1:]:
            if len(row) > id_idx and row[id_idx] == lead_id:
                current_stage = row[status_idx] if len(row) > status_idx else ""
                break

        if not current_stage:
            return {
                "ok": False,
                "action": "advance_to_next",
                "error": f"{lead_id} not found in {sheet_tab}",
            }

        next_stage = self._get_next_stage(current_stage)
        if not next_stage:
            return {
                "ok": False,
                "action": "advance_to_next",
                "error": f"No next stage after {current_stage}",
            }

        return self.advance(lead_id, next_stage, sheet_tab=sheet_tab, dry_run=dry_run)

    def close_opportunity(
        self,
        lead_id: str,
        outcome: str,  # "won" or "lost"
        *,
        sheet_tab: str = "leads",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Close an opportunity as won or lost."""
        return self.crm.close_opportunity(
            lead_id=lead_id,
            outcome=outcome,
            sheet_tab=sheet_tab,
            dry_run=dry_run,
        )

    # ------------------------------------------------------------------
    # Email dispatch
    # ------------------------------------------------------------------

    def dispatch_email(
        self,
        *,
        to_address: str = "",
        template_name: str = "",
        context: dict[str, Any] | None = None,
        subject: str = "",
        body: str = "",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Send an email using the configured SMTP adapter.

        If template_name is provided, renders from templates first.
        Falls back to explicit subject/body if no template given.
        """
        if self.outreach_adapter is None:
            # Build default using Hostinger credentials from config
            settings = load_settings()
            self.outreach_adapter = OutreachAdapter(
                smtp_host=settings.smtp_host,
                smtp_port=settings.smtp_port,
                smtp_user=settings.smtp_user,
                smtp_pass=settings.smtp_pass,
                from_address=settings.smtp_from,
                dry_run=dry_run,
            )

        if template_name:
            return self.outreach_adapter.send_from_template(
                template_name=template_name,
                context=context or {},
                to_address=to_address,
            )

        return self.outreach_adapter.send_email(
            to_address=to_address,
            subject=subject,
            body=body,
        )

    # ------------------------------------------------------------------
    # Reminder helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reminder_days_for_stage(stage: str) -> int | None:
        """Return follow-up reminder days for a given stage."""
        days_map: dict[str, int] = {
            OpportunityStage.SOURCED.value: 3,
            OpportunityStage.RESEARCHED.value: 2,
            OpportunityStage.REP_FIT_SCORED.value: 3,
            OpportunityStage.APPLICATION_DRAFT_CREATED.value: 5,
            OpportunityStage.APPLICATION_APPROVED.value: 2,
            OpportunityStage.APPLICATION_SUBMITTED.value: 7,
        }
        return days_map.get(stage)

    # ------------------------------------------------------------------
    # Pipeline overview
    # ------------------------------------------------------------------

    def pipeline_summary(
        self,
        *,
        sheet_tab: str = "leads",
        count: int = 200,
    ) -> dict[str, Any]:
        """Return a structured summary of the current pipeline."""
        result = self.crm.get_pipeline(sheet_tab=sheet_tab, count=count)
        if not result.get("ok"):
            return result

        stages = result.get("stages", {})
        summary: dict[str, int] = {}
        for stage in OpportunityStage:
            summary[stage.value] = len(stages.get(stage.value, []))

        total = sum(summary.values())
        open_count = (
            total
            - summary.get(OpportunityStage.CLOSED_WON.value, 0)
            - summary.get(OpportunityStage.CLOSED_LOST.value, 0)
        )

        return {
            "ok": True,
            "action": "pipeline_summary",
            "total": total,
            "open": open_count,
            "closed_won": summary.get(OpportunityStage.CLOSED_WON.value, 0),
            "closed_lost": summary.get(OpportunityStage.CLOSED_LOST.value, 0),
            "stages": summary,
            "error": None,
        }

    def upcoming_reminders(
        self,
        days: int = 7,
    ) -> dict[str, Any]:
        """Return upcoming calendar reminders."""
        if self.calendar_adapter is None:
            return {
                "ok": True,
                "action": "upcoming_reminders",
                "events": [],
            }
        return self.calendar_adapter.list_upcoming_events(
            days=days,
            sheets_adapter=self.sheets_adapter,
        )

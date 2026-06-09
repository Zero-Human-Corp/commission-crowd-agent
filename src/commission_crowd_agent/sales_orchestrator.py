"""Sales orchestrator — combines prospector, CRM, email templates, and calendar.

Provides end-to-end B2B sales campaign automation:
1. PROSPECT → fetch opportunities (CommissionCrowd API or browser scrape)
2. SCORE → fit/commission scoring via domain models
3. ENRICH → auto-research (web search, domain lookup)
4. DRAFT → generate application/pitch using email templates
5. GATE → human approval via ApprovalGate
6. SUBMIT → (approved only) log to CRM + schedule follow-up calendar events
7. PIPELINE → track all leads through CRM stages

Dry-run by default. No live sends without explicit operator opt-in.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from .approval_gate import ApprovalGate
from .calendar_adapter import CalendarAdapter
from .config import load_settings
from .crm_pipeline import CRMPipeline
from .domain import OpportunityStage
from .email_templates import render_template

if TYPE_CHECKING:
    from .adapters import GoogleSheetsAdapter


class SalesOrchestrator:
    """End-to-end sales campaign orchestrator.

    Parameters
    ----------
    sheets_adapter: GoogleSheetsAdapter
        CRM pipeline backend (Google Sheets with leads/opportunities tabs).
    calendar_adapter: CalendarAdapter | None
        Calendar backend for follow-ups and reminders.
    dry_run: bool
        If True (default), no real writes occur — only drafts and reports.
    """

    def __init__(
        self,
        sheets_adapter: GoogleSheetsAdapter | None = None,
        calendar_adapter: CalendarAdapter | None = None,
        dry_run: bool = True,
    ) -> None:
        self.crm = CRMPipeline(sheets_adapter=sheets_adapter)
        self.calendar = calendar_adapter or CalendarAdapter(dry_run=dry_run)
        self.dry_run = dry_run
        self.gate = ApprovalGate(sheets_adapter=sheets_adapter)
        self.settings = load_settings()

    # ────────────────────────────── 1. PROSPECT ──────────────────────────────
    def ingest_opportunities(
        self,
        opportunities: list[dict[str, Any]],
        *,
        source: str = "commissioncrowd",
    ) -> dict[str, Any]:
        """Ingest scored opportunities into the CRM pipeline (stage = sourced).

        Returns a summary dict with counts and any errors.
        """
        ingested: list[str] = []
        errors: list[str] = []
        for opp in opportunities:
            lead_id = f"CC-{uuid.uuid4().hex[:8]}"
            company_name = opp.get("company_name", opp.get("title", "Unknown"))
            contact_name = opp.get("contact_name", "")
            contact_email = opp.get("contact_email", "")
            notes = (
                f"Commission: {opp.get('commission_pc', '?')}% | "
                f"Score: {opp.get('fit_score', '?')} | "
                f"Source URL: {opp.get('source_url', '')}"
            )
            result = self.crm.add_lead(
                lead_id=lead_id,
                company_name=company_name,
                contact_name=contact_name,
                contact_email=contact_email,
                source=source,
                source_url=opp.get("source_url", ""),
                notes=notes,
                dry_run=self.dry_run,
            )
            if result.get("ok"):
                ingested.append(lead_id)
            else:
                errors.append(f"{lead_id}: {result.get('error', 'unknown')}")

        return {
            "ok": len(errors) == 0,
            "action": "ingest_opportunities",
            "total": len(opportunities),
            "ingested": len(ingested),
            "errors": errors,
            "lead_ids": ingested,
            "dry_run": self.dry_run,
        }

    # ────────────────────────────── 2. ENRICH ───────────────────────────────
    def enrich_lead(
        self,
        lead_id: str,
        *,
        web_context: str = "",
    ) -> dict[str, Any]:
        """Advance a lead from sourced → researched with enrichment context.

        If web_context is provided, it is stored in the notes field.
        """
        advance_result = self.crm.advance_stage(
            lead_id=lead_id,
            new_stage=OpportunityStage.RESEARCHED.value,
            dry_run=self.dry_run,
        )
        if not advance_result.get("ok"):
            return advance_result

        return {
            "ok": True,
            "action": "enrich_lead",
            "lead_id": lead_id,
            "new_stage": OpportunityStage.RESEARCHED.value,
            "web_context": web_context,
            "dry_run": self.dry_run,
        }

    # ────────────────────────────── 3. DRAFT ───────────────────────────────────
    def draft_application(
        self,
        lead_id: str,
        *,
        template_name: str = "application_submission",
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate an application email draft for a lead.

        Looks up the lead in CRM, renders the chosen template, and stores the
        draft for human approval.

        Also advances stage: researched → application_draft_created.
        """
        pipeline = self.crm.get_pipeline(count=200)
        if not pipeline.get("ok"):
            return {
                "ok": False,
                "action": "draft_application",
                "error": pipeline.get("error", "Failed to read pipeline"),
                "lead_id": lead_id,
            }

        # Find lead record
        lead_record: dict[str, Any] | None = None
        for _stage, records in pipeline.get("stages", {}).items():
            for rec in records:
                if rec.get("lead_id") == lead_id:
                    lead_record = rec
                    break
            if lead_record:
                break

        if lead_record is None:
            return {
                "ok": False,
                "action": "draft_application",
                "error": f"Lead {lead_id} not found in CRM",
                "lead_id": lead_id,
            }

        company_name = lead_record.get("company_name", "")
        contact_name = lead_record.get("contact_name", "")
        contact_email = lead_record.get("contact_email", "")

        ctx: dict[str, Any] = {
            "contact_name": contact_name or "Hiring Manager",
            "company_name": company_name,
            "sender_name": self.settings.operator_name or "Gopolang Makokwe",
            "sender_email": self.settings.operator_email or "publisher@syntaxis.online",
            "sender_phone": self.settings.operator_phone or "+27847360736",
            "territory": "Global",
            "icp_summary": "B2B SaaS buyers, decision-makers in IT/Operations",
            "commission_structure": "20%+ commission on closed sales",
            "industry_focus": "SaaS, Cybersecurity, Technology",
            "years_experience": "10+",
            "context": "",
        }
        if extra_context:
            ctx.update(extra_context)

        try:
            subject, body = render_template(template_name, ctx)
        except (ValueError, KeyError) as exc:
            return {
                "ok": False,
                "action": "draft_application",
                "error": f"Template render error: {exc}",
                "lead_id": lead_id,
            }

        # Advance stage to application_draft_created
        advance_result = self.crm.advance_stage(
            lead_id=lead_id,
            new_stage=OpportunityStage.APPLICATION_DRAFT_CREATED.value,
            dry_run=self.dry_run,
        )
        if not advance_result.get("ok"):
            return {
                "ok": False,
                "action": "draft_application",
                "error": advance_result.get("error", "Stage advance failed"),
                "lead_id": lead_id,
            }

        return {
            "ok": True,
            "action": "draft_application",
            "lead_id": lead_id,
            "template": template_name,
            "subject": subject,
            "body": body,
            "to_email": contact_email,
            "dry_run": self.dry_run,
        }

    # ────────────────────────────── 4. GATE ────────────────────────────────────
    def submit_for_approval(
        self,
        lead_id: str,
        subject: str,
        body: str,
        to_email: str,
    ) -> dict[str, Any]:
        """Submit a drafted application for human operator approval.

        Uses ApprovalGate to create a review entry.
        """
        return self.gate.submit(
            lead_id=lead_id,
            subject=subject,
            body=body,
            to_email=to_email,
        )

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Return all pending approval requests."""
        return self.gate.list_pending()

    def approve_and_send(
        self,
        approval_id: str,
        *,
        calendar_reminder_days: int = 7,
    ) -> dict[str, Any]:
        """Operator-approval wrapper: approve the draft and schedule follow-up.

        1. Marks approval as approved in the gate
        2. Advances CRM stage: application_draft_created → application_approved
        3. Schedules calendar follow-up reminder

        Does NOT actually send email — that requires a separate SMTP adapter call.
        """
        approval_result = self.gate.approve(approval_id)
        if not approval_result.get("ok"):
            return approval_result

        lead_id = approval_result.get("lead_id", "")
        if not lead_id:
            return {
                "ok": False,
                "action": "approve_and_send",
                "error": "Missing lead_id in approval record",
                "approval_id": approval_id,
            }

        # Advance stage
        advance_result = self.crm.advance_stage(
            lead_id=lead_id,
            new_stage=OpportunityStage.APPLICATION_APPROVED.value,
            dry_run=self.dry_run,
        )
        if not advance_result.get("ok"):
            return {
                "ok": False,
                "action": "approve_and_send",
                "error": advance_result.get("error", "Stage advance failed"),
                "lead_id": lead_id,
                "approval_id": approval_id,
            }

        # Schedule follow-up reminder
        cal_result = self.calendar.schedule_follow_up(
            entity_type="opportunity",
            entity_id=lead_id,
            days=calendar_reminder_days,
            sheets_adapter=self.crm.sheets_adapter,
        )

        return {
            "ok": True,
            "action": "approve_and_send",
            "lead_id": lead_id,
            "approval_id": approval_id,
            "calendar_event_id": cal_result.get("event_id", ""),
            "dry_run": self.dry_run,
        }

    # ────────────────────────────── 5. PIPELINE ───────────────────────────────
    def get_pipeline_report(self) -> dict[str, Any]:
        """Return full pipeline status grouped by stage with counts."""
        return self.crm.get_pipeline(count=200)

    def get_overdue_follow_ups(
        self,
        days: int = 7,
    ) -> dict[str, Any]:
        """Return opportunities with no activity in N days."""
        upcoming = self.calendar.list_upcoming_events(
            days=days,
            sheets_adapter=self.crm.sheets_adapter,
        )
        if not upcoming.get("ok"):
            return {
                "ok": False,
                "action": "get_overdue_follow_ups",
                "error": upcoming.get("error", "Calendar read failed"),
                "overdue": [],
            }

        # Build set of lead_ids that have upcoming events
        covered: set[str] = set()
        for ev in upcoming.get("events", []):
            eid = ev.get("entity_id", "")
            if eid.startswith("CC-"):
                covered.add(eid)

        pipeline = self.crm.get_pipeline(count=200)
        if not pipeline.get("ok"):
            return {
                "ok": False,
                "action": "get_overdue_follow_ups",
                "error": pipeline.get("error", "Pipeline read failed"),
                "overdue": [],
            }

        overdue: list[dict[str, Any]] = []
        for stage, records in pipeline.get("stages", {}).items():
            # Only active stages (not closed)
            if stage in {OpportunityStage.CLOSED_WON.value, OpportunityStage.CLOSED_LOST.value}:
                continue
            for rec in records:
                lid = rec.get("lead_id", "")
                if lid and lid not in covered:
                    overdue.append(
                        {
                            "lead_id": lid,
                            "company_name": rec.get("company_name", ""),
                            "stage": stage,
                            "status": rec.get("status", ""),
                        }
                    )

        return {
            "ok": True,
            "action": "get_overdue_follow_ups",
            "overdue_count": len(overdue),
            "overdue": overdue,
        }

    # ────────────────────────────── 6. CAMPAIGN ────────────────────────────────
    def run_campaign_cycle(
        self,
        opportunities: list[dict[str, Any]],
        *,
        auto_draft: bool = False,
        min_score: int = 50,
    ) -> dict[str, Any]:
        """Run one full campaign cycle: ingest → enrich → draft (optional) → report.

        If auto_draft is True, generates application drafts for leads that pass
        the minimum score threshold.
        """
        # 1. Ingest
        ingest = self.ingest_opportunities(opportunities, source="commissioncrowd")
        lead_ids = ingest.get("lead_ids", [])

        # 2. Enrich
        enriched: list[str] = []
        for lid in lead_ids:
            r = self.enrich_lead(lid)
            if r.get("ok"):
                enriched.append(lid)

        # 3. Draft (optional, approval-gated)
        drafts: list[dict[str, Any]] = []
        if auto_draft:
            for lid in enriched:
                draft = self.draft_application(lid)
                if draft.get("ok"):
                    # Submit for approval
                    approval = self.submit_for_approval(
                        lead_id=lid,
                        subject=draft["subject"],
                        body=draft["body"],
                        to_email=draft.get("to_email", ""),
                    )
                    drafts.append(
                        {
                            "lead_id": lid,
                            "subject": draft["subject"],
                            "to_email": draft.get("to_email", ""),
                            "approval_id": approval.get("approval_id", ""),
                        }
                    )

        return {
            "ok": True,
            "action": "run_campaign_cycle",
            "total_opportunities": len(opportunities),
            "ingested": ingest.get("ingested", 0),
            "enriched": len(enriched),
            "drafts_created": len(drafts),
            "drafts": drafts,
            "pending_approvals": len(self.get_pending_approvals()),
            "dry_run": self.dry_run,
        }

"""Minimal workflow runner interface and dry-run support.

Designed to be called from CLI or imported into n8n Code nodes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapters import GoogleSheetsAdapter

from .domain import Lead, LeadStatus, Task, TaskType, WorkflowRun


class WorkflowRunner:
    """Orchestrate a batch of leads through research → draft → score."""

    def __init__(
        self,
        dry_run: bool = True,
        sheets_adapter: GoogleSheetsAdapter | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.sheets_adapter = sheets_adapter

    def run_research_and_draft(
        self,
        client_name: str,
        leads: list[Lead],
    ) -> WorkflowRun:
        """Execute research + writing for a batch of leads."""
        run = WorkflowRun(
            run_id=str(uuid.uuid4())[:8],
            client_name=client_name,
        )

        for lead in leads:
            if lead.status != LeadStatus.NEW:
                continue

            # Research task
            research_task = Task(
                task_id=str(uuid.uuid4())[:8],
                task_type=TaskType.RESEARCH,
                lead_id=lead.lead_id,
            )
            research_task.mark_started()
            if self.dry_run:
                research_task.mark_done(output=f"[DRY] Research notes for {lead.company}")
            else:
                # TODO: wire to real Researcher Adapter
                research_task.mark_done(output="")
            lead.research_notes = research_task.output
            run.tasks.append(research_task)

            # Writer task
            writer_task = Task(
                task_id=str(uuid.uuid4())[:8],
                task_type=TaskType.WRITE,
                lead_id=lead.lead_id,
            )
            writer_task.mark_started()
            if self.dry_run:
                writer_task.mark_done(output=f"[DRY] Subject: Hello {lead.full_name}")
            else:
                # TODO: wire to real Writer Adapter
                writer_task.mark_done(output="")
            lead.email_subject = f"Hello {lead.full_name}" if self.dry_run else ""
            lead.email_body = writer_task.output
            run.tasks.append(writer_task)

            # Scorer task
            scorer_task = Task(
                task_id=str(uuid.uuid4())[:8],
                task_type=TaskType.SCORE,
                lead_id=lead.lead_id,
            )
            scorer_task.mark_started()
            if self.dry_run:
                scorer_task.mark_done(output="7")
            else:
                # TODO: wire to real Scorer Adapter
                scorer_task.mark_done(output="")
            lead.personalization_score = int(scorer_task.output) if scorer_task.output else None
            run.tasks.append(scorer_task)

            lead.status = LeadStatus.DRAFT_READY

        run.status = "completed" if run.is_complete else "running"
        run.finished_at = datetime.utcnow()

        # Write run record to Sheets if adapter is wired
        if self.sheets_adapter is not None:
            run_row = run.to_sheets_run_row(
                workflow="research_cycle", extra={"client": client_name}
            )
            self.sheets_adapter.append_row("runs", run_row)
            for lead in leads:
                lead_row = lead.to_sheets_lead_row(
                    source="workflow" if not self.dry_run else "stub",
                    notes="workflow run" if not self.dry_run else "stub smoke-test row",
                )
                self.sheets_adapter.append_row("leads", lead_row)
                opp_row = lead.to_sheets_opportunity_row(
                    stage="research",
                    next_action="draft outreach",
                    created_at=datetime.utcnow(),
                )
                self.sheets_adapter.append_row("opportunities", opp_row)

        return run

"""Tests for workflow runner module."""

from commission_crowd_agent.domain import Lead, LeadStatus
from commission_crowd_agent.workflow_runner import WorkflowRunner


def test_dry_run_skips_non_new_leads():
    runner = WorkflowRunner(dry_run=True)
    leads = [
        Lead(lead_id="L001", client_name="C", status=LeadStatus.DRAFT_READY),
        Lead(lead_id="L002", client_name="C", status=LeadStatus.NEW),
    ]
    result = runner.run_research_and_draft(client_name="C", leads=leads)
    assert result.status == "completed"
    sheet = leads[1].to_sheet_row()
    assert sheet["Status"] == "Draft Ready"
    assert leads[0].status == LeadStatus.DRAFT_READY  # skipped but unchanged


def test_dry_run_populates_fields():
    runner = WorkflowRunner(dry_run=True)
    leads = [
        Lead(
            lead_id="L001",
            client_name="C",
            full_name="Alice",
            company="Acme",
            email="a@a.com",
        ),
    ]
    runner.run_research_and_draft(client_name="C", leads=leads)
    lead = leads[0]
    assert lead.status == LeadStatus.DRAFT_READY
    assert lead.research_notes.startswith("[DRY]")
    assert lead.email_subject == "Hello Alice"
    assert lead.personalization_score is not None

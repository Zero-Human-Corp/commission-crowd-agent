"""Tests for workflow runner module.

Covers dry-run behaviour, Sheets adapter wiring, and row-format contracts.
"""

from unittest.mock import MagicMock

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


def test_no_sheets_writes_when_adapter_is_none():
    """Backward-compat: without adapter no Sheets calls happen."""
    runner = WorkflowRunner(dry_run=True)
    leads = [Lead(lead_id="L001", client_name="C", status=LeadStatus.NEW)]
    run = runner.run_research_and_draft(client_name="C", leads=leads)
    assert run.status == "completed"
    # No exception = pass


def test_to_sheets_lead_row_format():
    lead = Lead(
        lead_id="L001",
        client_name="C",
        full_name="Alice",
        company="Acme",
        email="a@a.com",
        status=LeadStatus.DRAFT_READY,
    )
    row = lead.to_sheets_lead_row(source="stub", notes="test")
    assert row[0] == "L001"
    assert row[1] == "stub"
    assert row[2] == "Alice"
    assert row[3] == "Acme"
    assert row[5] == "a@a.com"
    assert row[6] == "Draft Ready"
    assert row[8] == "test"


def test_to_sheets_opportunity_row_format():
    lead = Lead(
        lead_id="L002",
        client_name="C",
        full_name="Bob",
        company="Globex",
        email="b@g.com",
        status=LeadStatus.DRAFT_READY,
        personalization_score=8,
    )
    row = lead.to_sheets_opportunity_row(
        opportunity_id="OPP-1", stage="research", next_action="draft"
    )
    assert row[0] == "OPP-1"
    assert row[1] == "L002"
    assert "Globex" in row[2]
    assert row[3] == "8"
    assert row[4] == "research"
    assert row[5] == "draft"


def test_to_sheets_run_row_format():
    from commission_crowd_agent.domain import WorkflowRun

    run = WorkflowRun(run_id="R001", client_name="C")
    row = run.to_sheets_run_row(workflow="research_cycle", extra={"leads": 2})
    assert row[0] == "R001"
    assert row[1] == "research_cycle"
    assert row[2] == "running"  # default before finishing
    # summary JSON in last column
    assert "total" in row[-1]


def test_sheets_adapter_dry_run_writes_no_rows():
    """When adapter is in dry_run mode, append_row returns ok without network."""
    mock_adapter = MagicMock()
    mock_adapter.dry_run = True
    mock_adapter.append_row.return_value = {"ok": True, "rows_changed": 1}

    runner = WorkflowRunner(dry_run=True, sheets_adapter=mock_adapter)
    leads = [Lead(lead_id="L001", client_name="C", status=LeadStatus.NEW)]
    run = runner.run_research_and_draft(client_name="C", leads=leads)
    assert run.status == "completed"
    # adapter.append_row called, but dry_run=True means no real write
    assert mock_adapter.append_row.called is True


def test_sheets_adapter_live_writes_expected_rows():
    """With dry_run=False adapter, append_row is invoked for runs, leads, opps."""
    mock_adapter = MagicMock()
    mock_adapter.dry_run = False
    mock_adapter.append_row.return_value = {"ok": True, "rows_changed": 1}

    runner = WorkflowRunner(dry_run=False, sheets_adapter=mock_adapter)
    leads = [
        Lead(lead_id="L001", client_name="C", full_name="Alice", company="Acme", email="a@a.com"),
    ]
    run = runner.run_research_and_draft(client_name="C", leads=leads)
    assert run.status == "completed"

    calls = mock_adapter.append_row.call_args_list
    tabs = [c[0][0] for c in calls]
    assert "runs" in tabs
    assert "leads" in tabs
    assert "opportunities" in tabs

    # Verify row contents: leads row should have source=workflow (not stub)
    lead_call = [c for c in calls if c[0][0] == "leads"][0]
    row = lead_call[0][1]
    assert row[1] == "workflow"
    assert "workflow run" in row[8]

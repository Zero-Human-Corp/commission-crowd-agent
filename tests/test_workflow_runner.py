"""Tests for workflow runner module.

Covers dry-run behaviour, Sheets adapter wiring, and row-format contracts.
"""

from unittest.mock import MagicMock

from commission_crowd_agent.domain import Lead, LeadStatus, WorkflowRun
from commission_crowd_agent.workflow_runner import WorkflowRunner


def test_dry_run_skips_non_new_leads() -> None:
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


def test_dry_run_populates_fields() -> None:
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


def test_no_sheets_writes_when_adapter_is_none() -> None:
    """Backward-compat: without adapter no Sheets calls happen."""
    runner = WorkflowRunner(dry_run=True)
    leads = [Lead(lead_id="L001", client_name="C", status=LeadStatus.NEW)]
    run = runner.run_research_and_draft(client_name="C", leads=leads)
    assert run.status == "completed"
    # No exception = pass


def test_to_sheets_lead_row_format() -> None:
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


def test_to_sheets_opportunity_row_format() -> None:
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


def test_to_sheets_run_row_format() -> None:
    from commission_crowd_agent.domain import WorkflowRun

    run = WorkflowRun(run_id="R001", client_name="C")
    row = run.to_sheets_run_row(workflow="research_cycle", extra={"leads": 2})
    assert row[0] == "R001"
    assert row[1] == "research_cycle"
    assert row[2] == "running"  # default before finishing
    # summary JSON in last column
    assert "total" in row[-1]


def test_sheets_adapter_dry_run_writes_no_rows() -> None:
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


def test_sheets_adapter_live_writes_expected_rows() -> None:
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


# --- Notification lifecycle tests ---


def test_no_notification_when_notifier_is_none() -> None:
    runner = WorkflowRunner(dry_run=True)
    leads = [Lead(lead_id="L001", client_name="C", status=LeadStatus.NEW)]
    run = runner.run_research_and_draft(client_name="C", leads=leads)
    assert run.status == "completed"


def test_notification_start_and_success_sent_when_enabled() -> None:
    from unittest.mock import MagicMock

    mock_notifier = MagicMock()
    mock_notifier.dry_run = False
    mock_notifier.send_message.return_value = {
        "ok": True,
        "status": 200,
        "message_id": 12345,
    }

    runner = WorkflowRunner(dry_run=True, notifier=mock_notifier)
    leads = [Lead(lead_id="L001", client_name="C", status=LeadStatus.NEW)]
    run = runner.run_research_and_draft(client_name="C", leads=leads)
    assert run.status == "completed"

    # start + success = 2 calls
    assert mock_notifier.send_message.call_count == 2
    texts = [c[1]["text"] for c in mock_notifier.send_message.call_args_list]
    assert any("Started" in t for t in texts)
    assert any("Complete" in t for t in texts)
    # Ensure no secrets appear in message text
    for text in texts:
        assert "token" not in text.lower()
        assert "spreadsheet" not in text.lower()


def test_notification_dry_run_does_not_call_api() -> None:
    from unittest.mock import MagicMock

    mock_notifier = MagicMock()
    mock_notifier.dry_run = True
    mock_notifier.send_message.return_value = {
        "ok": True,
        "status": 0,
        "message_id": None,
    }

    runner = WorkflowRunner(dry_run=True, notifier=mock_notifier)
    leads = [Lead(lead_id="L001", client_name="C", status=LeadStatus.NEW)]
    run = runner.run_research_and_draft(client_name="C", leads=leads)
    assert run.status == "completed"
    # start + success = 2 calls (dry_run handled inside notifier)
    assert mock_notifier.send_message.call_count == 2


def test_notification_failure_path() -> None:
    from unittest.mock import MagicMock

    mock_notifier = MagicMock()
    mock_notifier.dry_run = False
    mock_notifier.send_message.return_value = {
        "ok": True,
        "status": 200,
        "message_id": 99999,
    }

    runner = WorkflowRunner(dry_run=True, notifier=mock_notifier)
    run = WorkflowRun(run_id="R-FAIL", client_name="C")
    result = runner._notify_failure(run, error="Something went wrong")
    assert result["ok"] is True
    text = mock_notifier.send_message.call_args[1]["text"]
    assert "Failed" in text
    assert "Something went wrong" in text


def test_enabling_notifications_does_not_force_sheets_writes() -> None:
    """Having a notifier must not cause Google Sheets writes if adapter is None."""
    from unittest.mock import MagicMock

    mock_notifier = MagicMock()
    mock_notifier.dry_run = True
    mock_notifier.send_message.return_value = {"ok": True, "status": 0}

    runner = WorkflowRunner(dry_run=True, notifier=mock_notifier, sheets_adapter=None)
    leads = [Lead(lead_id="L001", client_name="C", status=LeadStatus.NEW)]
    run = runner.run_research_and_draft(client_name="C", leads=leads)
    assert run.status == "completed"
    # Notifier called but no sheets adapter = no sheet rows
    assert mock_notifier.send_message.call_count == 2

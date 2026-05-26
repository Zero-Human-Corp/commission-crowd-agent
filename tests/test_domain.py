"""Tests for domain models."""

from commission_crowd_agent.domain import Lead, LeadStatus, Task, TaskType, WorkflowRun


def test_lead_defaults():
    lead = Lead(lead_id="L001", client_name="ClientA")
    assert lead.status == LeadStatus.NEW
    assert lead.approved is False
    assert lead.sent_timestamp is None


def test_lead_email_lowercased():
    lead = Lead(lead_id="L001", client_name="ClientA", email="Alice@Example.COM")
    assert lead.email == "alice@example.com"


def test_lead_to_sheet_row():
    lead = Lead(lead_id="L001", client_name="ClientA", personalization_score=8)
    row = lead.to_sheet_row()
    assert row["Lead ID"] == "L001"
    assert row["Status"] == "New"
    assert row["Personalization Score"] == 8


def test_task_lifecycle():
    task = Task(task_id="T1", task_type=TaskType.RESEARCH, lead_id="L001")
    assert task.status == "pending"
    task.mark_started()
    assert task.status == "running"
    task.mark_done("notes")
    assert task.status == "done"
    assert task.output == "notes"


def test_workflow_run_completion():
    run = WorkflowRun(run_id="R1", client_name="ClientA")
    t1 = Task(task_id="T1", task_type=TaskType.RESEARCH, lead_id="L001")
    t1.mark_done("done")
    t2 = Task(task_id="T2", task_type=TaskType.WRITE, lead_id="L001")
    t2.mark_failed("boom")
    run.tasks = [t1, t2]
    assert run.is_complete is True


def test_workflow_run_summary():
    run = WorkflowRun(run_id="R1", client_name="ClientA")
    t1 = Task(task_id="T1", task_type=TaskType.RESEARCH, lead_id="L001")
    t1.mark_done("done")
    run.tasks = [t1]
    summary = run.summary()
    assert summary["total"] == 1
    assert summary["done"] == 1
    assert summary["failed"] == 0

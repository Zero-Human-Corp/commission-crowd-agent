"""Tests for the ApprovalGate service.

Covers creation, Sheet writes, read-backs, guard logic, and Telegram
notification safety.
"""

from unittest.mock import MagicMock

from commission_crowd_agent.approval_gate import ApprovalGate, ApprovalRequest


def test_create_approval_dry_run_no_write():
    """Dry-run must not call append_row on the sheets adapter."""
    mock_adapter = MagicMock()
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    req = gate.create_approval(
        opportunity_id="OPP-001",
        draft_text="Draft outreach to Acme",
        dry_run=True,
    )
    assert req.approval_status == "pending"
    assert req.opportunity_id == "OPP-001"
    mock_adapter.append_row.assert_not_called()


def test_create_approval_write_appends_row():
    """When dry_run=False the approval row must be appended."""
    mock_adapter = MagicMock()
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    req = gate.create_approval(
        opportunity_id="OPP-002",
        draft_text="Draft outreach to Globex",
        dry_run=False,
    )
    assert req.approval_status == "pending"
    mock_adapter.append_row.assert_called_once()
    call_args = mock_adapter.append_row.call_args
    assert call_args[0][0] == "approvals"
    row = call_args[0][1]
    assert row[1] == "OPP-002"
    assert row[2] == "Draft outreach to Globex"
    assert row[3] == "pending"


def test_read_approval_status_found():
    """Reading by approval_id must return the matching status."""
    mock_adapter = MagicMock()
    mock_adapter.read_rows.return_value = {
        "ok": True,
        "rows": [
            ["approval_id", "opportunity_id", "draft_text", "approval_status"],
            ["A001", "OPP-001", "Draft 1", "pending"],
            ["A002", "OPP-002", "Draft 2", "approved"],
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.read_approval_status("A001") == "pending"
    assert gate.read_approval_status("A002") == "approved"


def test_read_approval_status_missing():
    """Reading a non-existent approval_id must return 'missing'."""
    mock_adapter = MagicMock()
    mock_adapter.read_rows.return_value = {
        "ok": True,
        "rows": [
            ["approval_id", "opportunity_id", "draft_text", "approval_status"],
            ["A001", "OPP-001", "Draft 1", "pending"],
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.read_approval_status("A999") == "missing"


def test_is_approved_true_only_for_approved():
    """is_approved must return True only when status == 'approved'."""
    mock_adapter = MagicMock()
    mock_adapter.read_rows.return_value = {
        "ok": True,
        "rows": [
            ["approval_id", "approval_status"],
            ["A001", "pending"],
            ["A002", "approved"],
            ["A003", "rejected"],
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.is_approved("A001") is False
    assert gate.is_approved("A002") is True
    assert gate.is_approved("A003") is False


def test_is_approved_missing_is_false():
    """Missing approval must be treated as not approved."""
    mock_adapter = MagicMock()
    mock_adapter.read_rows.return_value = {"ok": True, "rows": []}
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.is_approved("A999") is False


def test_notify_operator_disabled_by_default():
    """Without a notifier, notify_operator must return sent=False."""
    gate = ApprovalGate()
    req = ApprovalRequest(approval_id="A001", opportunity_id="OPP-001")
    result = gate.notify_operator(req, dry_run=True)
    assert result["sent"] is False
    assert result["ok"] is True


def test_notify_operator_sends_safe_text():
    """When a notifier is wired, the message must contain no secrets."""
    mock_notifier = MagicMock()
    mock_notifier.send_message.return_value = {
        "ok": True,
        "status": 200,
        "message_id": 42,
    }
    gate = ApprovalGate(notifier=mock_notifier)
    req = ApprovalRequest(approval_id="A001", opportunity_id="OPP-001")
    result = gate.notify_operator(req, dry_run=False)
    assert result["ok"] is True
    text = mock_notifier.send_message.call_args[1]["text"]
    assert "Approval Required" in text
    assert "A001" in text
    assert "token" not in text.lower()
    assert "spreadsheet" not in text.lower()
    assert "private" not in text.lower()


def test_downstream_guard_blocks_pending():
    """A simulated downstream action must be blocked when approval is pending."""
    mock_adapter = MagicMock()
    mock_adapter.read_rows.return_value = {
        "ok": True,
        "rows": [
            ["approval_id", "approval_status"],
            ["A001", "pending"],
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)

    def downstream_action(approval_id: str) -> str:
        if not gate.is_approved(approval_id):
            return "BLOCKED"
        return "EXECUTED"

    assert downstream_action("A001") == "BLOCKED"


def test_downstream_guard_allows_approved():
    """A simulated downstream action must execute when approval is approved."""
    mock_adapter = MagicMock()
    mock_adapter.read_rows.return_value = {
        "ok": True,
        "rows": [
            ["approval_id", "approval_status"],
            ["A002", "approved"],
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)

    def downstream_action(approval_id: str) -> str:
        if not gate.is_approved(approval_id):
            return "BLOCKED"
        return "EXECUTED"

    assert downstream_action("A002") == "EXECUTED"

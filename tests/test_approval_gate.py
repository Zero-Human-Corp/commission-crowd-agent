"""Tests for the ApprovalGate service.

Covers creation, Sheet writes, read-backs, guard logic, Telegram
notification safety, and header validation.
"""

from unittest.mock import MagicMock

import pytest
from typing import Any

from commission_crowd_agent.approval_gate import ApprovalGate, ApprovalRequest

_APPROVALS_HEADER = [
    "approval_id",
    "created_at_utc",
    "entity_type",
    "entity_id",
    "requested_action",
    "risk_level",
    "status",
    "operator_decision",
    "decided_at_utc",
    "source_url",
    "notes",
    "entity_name",
    "approval_action",
]


def test_create_approval_dry_run_no_write():
    """Dry-run must not call append_row on the sheets adapter."""
    mock_adapter = MagicMock()
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    req = gate.create_approval(
        entity_type="opportunity",
        entity_id="OPP-001",
        requested_action="Draft outreach to Acme",
        dry_run=True,
    )
    assert req.status == "pending"
    assert req.entity_id == "OPP-001"
    mock_adapter.append_row.assert_not_called()


def test_create_approval_write_appends_row():
    """When dry_run=False the approval row must be appended."""
    mock_adapter = MagicMock()
    mock_adapter.SCHEMA = {"approvals": _APPROVALS_HEADER}
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    req = gate.create_approval(
        entity_type="opportunity",
        entity_id="OPP-002",
        requested_action="Draft outreach to Globex",
        risk_level="medium",
        notes="stub test",
        dry_run=False,
    )
    assert req.status == "pending"
    mock_adapter.append_row.assert_called_once()
    call_args = mock_adapter.append_row.call_args
    assert call_args[0][0] == "approvals"
    row = call_args[0][1]
    assert row[0] == req.approval_id
    assert row[1]  # created_at_utc set
    assert row[2] == "opportunity"
    assert row[3] == "OPP-002"
    assert row[4] == "Draft outreach to Globex"
    assert row[5] == "medium"
    assert row[6] == "pending"
    assert row[7] == ""  # operator_decision
    assert row[8] == ""  # decided_at_utc
    assert row[9] == ""  # source_url
    assert row[10] == "stub test"  # notes


def test_read_approval_status_found():
    """Reading by approval_id must return the matching status."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            _APPROVALS_HEADER,
            [
                "A001",
                "2026-05-27T00:00:00",
                "opportunity",
                "OPP-001",
                "Draft 1",
                "low",
                "pending",
                "",
                "",
                "",
                "",
            ],
            [
                "A002",
                "2026-05-27T00:00:00",
                "opportunity",
                "OPP-002",
                "Draft 2",
                "low",
                "approved",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.read_approval_status("A001") == "pending"
    assert gate.read_approval_status("A002") == "approved"


def test_read_approval_status_missing():
    """Reading a non-existent approval_id must return 'missing'."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            _APPROVALS_HEADER,
            [
                "A001",
                "2026-05-27T00:00:00",
                "opportunity",
                "OPP-001",
                "Draft 1",
                "low",
                "pending",
                "",
                "",
                "",
                "",
            ],
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.read_approval_status("A999") == "missing"


def test_is_approved_true_only_for_approved():
    """is_approved must return True only when status == 'approved'."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            ["approval_id", "status"],
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
    mock_adapter.read_last_rows.return_value = {"ok": True, "rows": []}
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.is_approved("A999") is False


def test_notify_operator_disabled_by_default():
    """Without a notifier, notify_operator must return sent=False."""
    gate = ApprovalGate()
    req = ApprovalRequest(approval_id="A001", entity_id="OPP-001")
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
    req = ApprovalRequest(
        approval_id="A001",
        entity_type="opportunity",
        entity_id="OPP-001",
        requested_action="Draft outreach",
    )
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
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            ["approval_id", "status"],
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
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            ["approval_id", "status"],
            ["A002", "approved"],
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)

    def downstream_action(approval_id: str) -> str:
        if not gate.is_approved(approval_id):
            return "BLOCKED"
        return "EXECUTED"

    assert downstream_action("A002") == "EXECUTED"


def test_validate_header_match():
    """validate_header must pass when live header matches SCHEMA."""
    mock_adapter = MagicMock()
    mock_adapter.SCHEMA = {"approvals": _APPROVALS_HEADER}
    mock_adapter.validate_tab_header.return_value = {
        "ok": True,
        "error": None,
        "live_header": _APPROVALS_HEADER,
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    result = gate.validate_header()
    assert result["ok"] is True
    assert result["live_header"] == _APPROVALS_HEADER


def test_validate_header_mismatch():
    """validate_header must fail when live header differs from SCHEMA."""
    mock_adapter = MagicMock()
    mock_adapter.SCHEMA = {"approvals": _APPROVALS_HEADER}
    mock_adapter.validate_tab_header.return_value = {
        "ok": False,
        "error": "Header mismatch",
        "live_header": ["approval_id", "wrong"],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    result = gate.validate_header()
    assert result["ok"] is False
    assert "mismatch" in result["error"].lower()

# ---- Tests for create_and_write_approval (production path) ----

def test_create_and_write_approval_raises_if_no_adapter():
    """Without a sheets_adapter, create_and_write_approval must refuse."""
    from commission_crowd_agent.approval_gate import ApprovalGate
    gate = ApprovalGate(sheets_adapter=None)
    with pytest.raises(RuntimeError, match="no sheets_adapter wired"):
        gate.create_and_write_approval(
            entity_type="lead",
            entity_id="3bc7c6cc",
            requested_action="Test",
        )

def test_create_and_write_approval_raises_on_header_mismatch():
    """If validate_tab_header fails, create_and_write_approval must abort."""
    from commission_crowd_agent.approval_gate import ApprovalGate
    mock_adapter = MagicMock()
    mock_adapter.validate_tab_header.return_value = {
        "ok": False,
        "error": "Header mismatch",
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    with pytest.raises(RuntimeError, match="Approval write aborted"):
        gate.create_and_write_approval(
            entity_type="lead",
            entity_id="3bc7c6cc",
            requested_action="Test",
        )

def test_create_and_write_approval_raises_on_write_failure():
    """If append_row fails, create_and_write_approval must raise."""
    from commission_crowd_agent.approval_gate import ApprovalGate
    mock_adapter = MagicMock()
    mock_adapter.validate_tab_header.return_value = {"ok": True}
    mock_adapter.append_row.return_value = {
        "ok": False,
        "error": "Quota exceeded",
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    with pytest.raises(RuntimeError, match="Approval write to Sheet failed"):
        gate.create_and_write_approval(
            entity_type="lead",
            entity_id="3bc7c6cc",
            requested_action="Test",
        )

def test_create_and_write_approval_raises_on_readback_missing():
    """If the written row is not found in readback, raise."""
    from commission_crowd_agent.approval_gate import ApprovalGate
    mock_adapter = MagicMock()
    mock_adapter.validate_tab_header.return_value = {"ok": True}
    mock_adapter.append_row.return_value = {"ok": True}
    # Readback returns a different approval_id
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            ["different-id", "2024-01-01", "lead", "other"],
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    with pytest.raises(RuntimeError, match="not found in readback"):
        gate.create_and_write_approval(
            entity_type="lead",
            entity_id="3bc7c6cc",
            requested_action="Test",
        )

def test_create_and_write_approval_succeeds_with_verification():
    """Happy path: write succeeds and readback finds the row."""
    from commission_crowd_agent.approval_gate import ApprovalGate
    mock_adapter = MagicMock()
    mock_adapter.validate_tab_header.return_value = {"ok": True}
    # Capture the row so we can return it in readback
    captured_rows: list[list[str]] = []

    def capture_append(tab: str, row: list[str]) -> dict[str, Any]:
        captured_rows.append(row)
        return {"ok": True}

    mock_adapter.append_row.side_effect = capture_append

    def readback(tab: str, count: int = 10) -> dict[str, Any]:
        # Return the captured row (simulating the Sheet now containing it)
        return {"ok": True, "rows": captured_rows}

    mock_adapter.read_last_rows.side_effect = readback

    gate = ApprovalGate(sheets_adapter=mock_adapter)
    req = gate.create_and_write_approval(
        entity_type="lead",
        entity_id="3bc7c6cc",
        requested_action="Test",
    )
    assert req.status == "pending"
    assert req.entity_id == "3bc7c6cc"
    # Verify write was called
    assert mock_adapter.append_row.call_count == 1
    # Verify readback was called
    assert mock_adapter.read_last_rows.call_count == 1


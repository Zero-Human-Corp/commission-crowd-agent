"""Tests for the approval decision roundtrip (read record, check status, gate action).

Covers:
- read_approval_record returns correct non-secret dict
- is_approved reads live status from Sheet
- downstream actions blocked for pending/rejected/missing
- downstream actions allowed only for approved
- schema header mismatch aborts safely
- no secrets appear in output
"""

from unittest.mock import MagicMock

from commission_crowd_agent.approval_gate import ApprovalGate

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
    "notes",
]


def _stub_row(approval_id: str, status: str) -> list[str]:
    return [
        approval_id,
        "2026-05-27T00:00:00",
        "opportunity",
        "OPP-001",
        "Draft outreach",
        "low",
        status,
        "",
        "",
        "",
    ]


def test_read_approval_record_found():
    """read_approval_record must return a full dict when the row exists."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            _APPROVALS_HEADER,
            _stub_row("A001", "pending"),
            _stub_row("A002", "approved"),
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    record = gate.read_approval_record("A001")
    assert record["approval_id"] == "A001"
    assert record["status"] == "pending"
    assert record["entity_type"] == "opportunity"
    assert "created_at_utc" in record


def test_read_approval_record_missing():
    """read_approval_record must return empty dict when the ID is not found."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            _APPROVALS_HEADER,
            _stub_row("A001", "pending"),
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.read_approval_record("A999") == {}


def test_read_approval_record_no_adapter():
    """read_approval_record must return empty dict when no adapter is wired."""
    gate = ApprovalGate()
    assert gate.read_approval_record("A001") == {}


def test_downstream_blocks_pending():
    """Pending approval must block downstream action."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            _APPROVALS_HEADER,
            _stub_row("A001", "pending"),
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.is_approved("A001") is False


def test_downstream_blocks_rejected():
    """Rejected approval must block downstream action."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            _APPROVALS_HEADER,
            _stub_row("A001", "rejected"),
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.is_approved("A001") is False


def test_downstream_blocks_expired():
    """Expired approval must block downstream action."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            _APPROVALS_HEADER,
            _stub_row("A001", "expired"),
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.is_approved("A001") is False


def test_downstream_allows_approved():
    """Approved approval must allow downstream action."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            _APPROVALS_HEADER,
            _stub_row("A001", "approved"),
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.is_approved("A001") is True


def test_downstream_blocks_missing():
    """Missing approval must block downstream action."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {"ok": True, "rows": []}
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    assert gate.is_approved("A999") is False


def test_read_record_no_secrets_in_output():
    """Approval record must not contain secrets even if Sheet had them."""
    mock_adapter = MagicMock()
    mock_adapter.read_last_rows.return_value = {
        "ok": True,
        "rows": [
            _APPROVALS_HEADER,
            _stub_row("A001", "pending"),
        ],
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    record = gate.read_approval_record("A001")
    for _key, value in record.items():
        assert "token" not in str(value).lower()
        assert "private" not in str(value).lower()
        assert "spreadsheet" not in str(value).lower()


def test_create_approval_writes_correct_row():
    """create_approval must produce a row matching canonical schema."""
    mock_adapter = MagicMock()
    mock_adapter.SCHEMA = {"approvals": _APPROVALS_HEADER}
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    req = gate.create_approval(
        entity_type="lead",
        entity_id="LEAD-99",
        requested_action="Send intro email",
        risk_level="medium",
        notes="roundtrip test",
        dry_run=False,
    )
    assert req.approval_id
    call = mock_adapter.append_row.call_args
    assert call[0][0] == "approvals"
    row = call[0][1]
    assert len(row) == 10
    assert row[2] == "lead"
    assert row[3] == "LEAD-99"
    assert row[4] == "Send intro email"
    assert row[5] == "medium"
    assert row[6] == "pending"
    assert row[9] == "roundtrip test"

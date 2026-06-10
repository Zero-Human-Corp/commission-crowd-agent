"""Tests for schema validation guards during writes.

Covers:
- Header mismatch blocks lead writes
- Header mismatch blocks approval writes
- Dry-run does not validate headers (no network call needed)
- updated_range returned from append_row
"""

from unittest.mock import MagicMock

from commission_crowd_agent.adapters import GoogleSheetsAdapter
from commission_crowd_agent.lead_ingestion import CandidateLead, LeadIngester


def test_write_candidates_blocked_on_header_mismatch() -> None:
    """write_candidates must abort if live header does not match SCHEMA."""
    mock_adapter = MagicMock()
    mock_adapter.validate_tab_header.return_value = {
        "ok": False,
        "error": "Header mismatch for 'leads'",
    }
    ingester = LeadIngester(sheets_adapter=mock_adapter)
    candidates = [CandidateLead(company="X", source="test")]
    result = ingester.write_candidates(candidates, dry_run=False)
    assert result["ok"] is False
    assert "Schema validation failed" in result["error"]
    mock_adapter.append_row.assert_not_called()


def test_write_candidates_passes_on_header_match() -> None:
    """write_candidates must proceed if live header matches SCHEMA."""
    mock_adapter = MagicMock()
    mock_adapter.validate_tab_header.return_value = {"ok": True, "error": None}
    mock_adapter.append_row.return_value = {"ok": True, "updated_range": "leads!A2:O2"}
    ingester = LeadIngester(sheets_adapter=mock_adapter)
    candidates = [CandidateLead(company="X", source="test")]
    result = ingester.write_candidates(candidates, dry_run=False)
    assert result["ok"] is True
    assert result["written"] == 1
    mock_adapter.append_row.assert_called_once()


def test_append_row_returns_updated_range() -> None:
    """append_row result must include updated_range field."""
    adapter = GoogleSheetsAdapter(spreadsheet_id="test", dry_run=True)
    result = adapter.append_row("leads", ["a", "b"])
    assert "updated_range" in result
    assert result["updated_range"] == ""


def test_approval_gate_blocks_on_header_mismatch() -> None:
    """ApprovalGate.create_approval must raise if header mismatch."""
    from commission_crowd_agent.approval_gate import ApprovalGate

    mock_adapter = MagicMock()
    mock_adapter.validate_tab_header.return_value = {
        "ok": False,
        "error": "Header mismatch for 'approvals'",
    }
    gate = ApprovalGate(sheets_adapter=mock_adapter)
    try:
        gate.create_approval(
            entity_type="lead",
            entity_id="L001",
            requested_action="test",
            dry_run=False,
        )
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "Approval write aborted" in str(exc)

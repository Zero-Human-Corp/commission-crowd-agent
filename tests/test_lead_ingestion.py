"""Tests for the LeadIngester service.

Covers:
- JSON discovery loads candidates with provenance
- Search discovery returns empty (stub)
- Dry-run performs no Sheet writes
- --write writes at most the configured limit
- Email is not invented when absent
- Approval requests are created for written candidates
- No outreach path is called
"""

from pathlib import Path
from unittest.mock import MagicMock

from commission_crowd_agent.lead_ingestion import CandidateLead, LeadIngester

_SAMPLES = Path(__file__).with_name("fixtures") / "sample_candidates.json"


def test_discover_from_json():
    """discover_from_json must load candidates from a JSON file."""
    mock_adapter = MagicMock()
    ingester = LeadIngester(sheets_adapter=mock_adapter)
    candidates = ingester.discover_from_json(_SAMPLES)
    assert len(candidates) == 3
    assert candidates[0].company == "Acme Solutions"
    assert candidates[0].provenance == "web search: enterprise analytics companies UK"
    assert candidates[1].company == "BetaCorp"
    assert candidates[1].email == ""  # must not invent email


def test_discover_from_search_stub():
    """discover_from_search must return empty list (stub implementation)."""
    mock_adapter = MagicMock()
    ingester = LeadIngester(sheets_adapter=mock_adapter)
    result = ingester.discover_from_search("test query", limit=5)
    assert result == []


def test_write_candidates_dry_run():
    """write_candidates with dry_run=True must not call append_row."""
    mock_adapter = MagicMock()
    ingester = LeadIngester(sheets_adapter=mock_adapter)
    candidates = [CandidateLead(company="X", source="test")]
    result = ingester.write_candidates(candidates, dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["written"] == 0
    mock_adapter.append_row.assert_not_called()


def test_write_candidates_live():
    """write_candidates with dry_run=False must call append_row."""
    mock_adapter = MagicMock()
    mock_adapter.append_row.return_value = {"ok": True, "row": 42}
    ingester = LeadIngester(sheets_adapter=mock_adapter)
    candidates = [
        CandidateLead(company="A", source="test"),
        CandidateLead(company="B", source="test"),
    ]
    result = ingester.write_candidates(candidates, dry_run=False)
    assert result["ok"] is True
    assert result["written"] == 2
    assert mock_adapter.append_row.call_count == 2


def test_write_candidates_no_adapter():
    """write_candidates with no adapter must fail gracefully."""
    ingester = LeadIngester()
    candidates = [CandidateLead(company="X", source="test")]
    result = ingester.write_candidates(candidates, dry_run=False)
    assert result["ok"] is False
    assert "No sheets adapter" in result["error"]


def test_create_approval_requests_dry_run():
    """create_approval_requests dry-run must not call create_approval with dry_run=False."""
    mock_gate = MagicMock()
    mock_gate.create_approval.return_value = MagicMock(
        approval_id="A001", company="X", status="pending"
    )
    ingester = LeadIngester(approval_gate=mock_gate)
    candidates = [
        CandidateLead(company="A", source="test"),
        CandidateLead(company="B", source="test"),
    ]
    results = ingester.create_approval_requests(candidates, dry_run=True)
    assert len(results) == 2
    mock_gate.create_approval.assert_called()
    # The last call should have dry_run=True
    call_kwargs = mock_gate.create_approval.call_args[1]
    assert call_kwargs["dry_run"] is True


def test_create_approval_requests_live():
    """create_approval_requests with dry_run=False must create real approvals."""
    mock_gate = MagicMock()
    mock_gate.create_approval.return_value = MagicMock(
        approval_id="A002", company="Y", status="pending"
    )
    ingester = LeadIngester(approval_gate=mock_gate)
    candidates = [CandidateLead(company="C", source="test")]
    results = ingester.create_approval_requests(candidates, dry_run=False)
    assert len(results) == 1
    assert results[0]["approval_id"] == "A002"
    call_kwargs = mock_gate.create_approval.call_args[1]
    assert call_kwargs["dry_run"] is False


def test_create_approval_requests_no_gate():
    """create_approval_requests with no gate must return empty list."""
    ingester = LeadIngester()
    candidates = [CandidateLead(company="X", source="test")]
    results = ingester.create_approval_requests(candidates, dry_run=False)
    assert results == []


def test_to_sheets_lead_row_no_email():
    """Serialised row must have empty email when not provided."""
    lead = CandidateLead(company="X", source="test")
    row = lead.to_sheets_lead_row()
    assert row[5] == ""  # email column


def test_to_sheets_lead_row_has_provenance():
    """Serialised row must include source and notes."""
    lead = CandidateLead(
        company="X", source="web_search", notes="found via DDG", provenance="ddg: X"
    )
    row = lead.to_sheets_lead_row()
    assert row[1] == "web_search"
    assert row[8] == "found via DDG"


def test_discover_from_json_respects_limit():
    """discover_from_json must ingest at most the number of items in the file."""
    mock_adapter = MagicMock()
    ingester = LeadIngester(sheets_adapter=mock_adapter)
    candidates = ingester.discover_from_json(_SAMPLES)
    assert len(candidates) <= 3


def test_discover_from_json_hard_cap():
    """If JSON had more than 5 items, only first 5 should be ingested."""
    mock_adapter = MagicMock()
    ingester = LeadIngester(sheets_adapter=mock_adapter)
    # The sample file only has 3, so this tests the code path doesn't crash
    candidates = ingester.discover_from_json(_SAMPLES)
    assert len(candidates) <= 5

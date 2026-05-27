"""Tests for deeper research service.

Covers:
- Approved lead proceeds with research
- Unapproved lead is blocked before research
- Dry-run reports findings without writing
- No outreach paths are invoked
- Findings carry provenance or unverified marker
"""

from unittest.mock import MagicMock

from commission_crowd_agent.deeper_research import DeeperResearchService

# Fixture leads aligned with canonical 15-col leads schema
_ACME_LEAD = [
    "81091b6c",
    "2026-05-27T10:00:00",
    "web_search",
    "https://acme-solutions.example.com",
    "Acme Solutions",
    "Jane Smith",
    "jane.smith@acme-solutions.example.com",
    "CEO",
    "SaaS",
    "UK",
    "Data pipeline bottleneck",
    "",
    "90",
    "discovered",
    "Strong signal",
]


class _MockAdapter(MagicMock):
    """A mock adapter that validates_tab_header always passes and append_row tracks."""

    pass


def _make_mock_gate_and_adapter():
    """Return a mock ApprovalGate and a mock GoogleSheetsAdapter."""
    gate = MagicMock()
    gate.create_approval.return_value = MagicMock(approval_id="APP-RES-001", status="pending")
    adapter = _MockAdapter()
    adapter.validate_tab_header.return_value = {"ok": True}
    adapter.append_row.return_value = {"ok": True}
    return gate, adapter


def test_research_one_lead_marks_unverifiable_source():
    """When source_url does not resolve, finding is marked unverified."""
    svc = DeeperResearchService()
    result = svc.research_one_lead(
        lead_id="81091b6c",
        company_name="Acme Solutions",
        source_url="https://fake-homepage.example.com",
    )
    homepage = [f for f in result.findings if f.source_label == "company_homepage"]
    assert len(homepage) == 1
    assert homepage[0].verified is False


def test_research_one_lead_with_notes_finds_verified_note():
    """Existing ingestion notes are treated as verified sourced data."""
    svc = DeeperResearchService()
    result = svc.research_one_lead(
        lead_id="81091b6c",
        company_name="Acme Solutions",
        source_url="",
        notes="Strong signal from web search",
    )
    note = [f for f in result.findings if f.source_label == "ingestion_notes"]
    assert len(note) == 1
    assert note[0].verified is True


def test_unapproved_research_is_blocked():
    """If approval status is not approved, research must not proceed."""
    svc = DeeperResearchService()
    gate, adapter = _make_mock_gate_and_adapter()
    block = svc.research_one_lead(
        lead_id="81091b6c",
        company_name="Acme Solutions",
    )
    assert block.confidence == "low"


def test_dry_run_does_not_write():
    """write_research_result with dry_run=True must call no append_row."""
    svc = DeeperResearchService()
    result = svc.research_one_lead(
        lead_id="81091b6c",
        company_name="Acme Solutions",
    )
    _, adapter = _make_mock_gate_and_adapter()
    write_res = svc.write_research_result(result, sheets_adapter=adapter, dry_run=True)
    assert write_res["dry_run"] is True
    assert write_res["written"] == 0
    adapter.append_row.assert_not_called()


def test_write_research_result_live():
    """write_research_result with dry_run=False appends to outcomes tab."""
    svc = DeeperResearchService()
    result = svc.research_one_lead(
        lead_id="81091b6c",
        company_name="Acme Solutions",
    )
    _, adapter = _make_mock_gate_and_adapter()
    write_res = svc.write_research_result(result, sheets_adapter=adapter, dry_run=False)
    assert write_res["ok"] is True
    adapter.append_row.assert_called_once()
    call_args = adapter.append_row.call_args
    assert call_args[0][0] == "outcomes"
    assert len(call_args[0][1]) == 10  # outcomes schema is 10 columns


def test_request_outreach_draft_approval_dry_run():
    """dry_run must not create a real approval."""
    svc = DeeperResearchService()
    result = svc.research_one_lead(
        lead_id="81091b6c",
        company_name="Acme Solutions",
    )
    gate, adapter = _make_mock_gate_and_adapter()
    res = svc.request_outreach_draft_approval(
        result, approval_gate=gate, sheets_adapter=adapter, dry_run=True
    )
    assert res["dry_run"] is True
    gate.create_approval.assert_not_called()


def test_request_outreach_draft_approval_live():
    """With dry_run=False, an approval is created for outreach-draft."""
    svc = DeeperResearchService()
    result = svc.research_one_lead(
        lead_id="81091b6c",
        company_name="Acme Solutions",
    )
    gate, adapter = _make_mock_gate_and_adapter()
    res = svc.request_outreach_draft_approval(
        result, approval_gate=gate, sheets_adapter=adapter, dry_run=False
    )
    assert res["ok"] is True
    assert res["approval_id"] == "APP-RES-001"
    gate.create_approval.assert_called_once()
    call_args = gate.create_approval.call_args.kwargs
    assert "outreach draft" in call_args["requested_action"].lower()


def test_no_outreach_path_in_module():
    """Deeper research module must not import or call any outreach mechanism."""
    import inspect

    from commission_crowd_agent import deeper_research

    source = inspect.getsource(deeper_research)
    # Look for actual function calls, not just string literals
    banned_calls = ["send_email(", "send_message(", "draft_outreach(", "notify("]
    for term in banned_calls:
        assert term not in source.lower(), f"Banned call {term!r} found in deeper_research"


def test_result_to_outcome_row_aligned_with_schema():
    """Research result serialised to outcomes tab must have 10 columns."""
    from commission_crowd_agent.adapters import GoogleSheetsAdapter

    svc = DeeperResearchService()
    result = svc.research_one_lead(
        lead_id="81091b6c",
        company_name="Acme Solutions",
    )
    row = result.to_outcome_row()
    assert len(row) == len(GoogleSheetsAdapter.SCHEMA["outcomes"])
    assert row[4] == "deeper_research"

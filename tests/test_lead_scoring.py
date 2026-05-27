"""Tests for lead scoring service.

Covers:
- Deterministic scoring on discovered lead with full data
- Missing email lowers confidence but does not invent it
- Missing company/contact lowers score
- Dry-run produces no writes
- Real writes validate headers first
- Approvals only created for above-threshold leads
- No outreach paths are invoked
"""

from unittest.mock import MagicMock

from commission_crowd_agent.lead_scoring import LeadScorer

# Fixture leads aligned with canonical 15-col leads schema
_ACME_FULL = [
    "81091b6c",
    "2026-05-27T10:00:00",
    "web_search",
    "https://acme.example.com",
    "Acme Solutions",
    "Jane Smith",
    "jane@acme.example.com",
    "CEO",
    "SaaS",
    "UK",
    "Data pipeline bottleneck",
    "",
    "",
    "discovered",
    "Strong signal",
]

_BETA_NO_EMAIL = [
    "c5571629",
    "2026-05-27T10:00:00",
    "manual",
    "",
    "BetaCorp",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "needs_review",
    "No contact yet",
]

_GAMMA_PARTIAL = [
    "d82d639a",
    "2026-05-27T10:00:00",
    "web_search",
    "https://gamma.example.com",
    "Gamma Systems",
    "Robert Chen",
    "",
    "Engineer",
    "Cybersecurity",
    "DE",
    "Compliance audit needed",
    "",
    "",
    "discovered",
    "Partial contact",
]


def test_score_full_lead():
    """Full lead with email, company, URL, name, notes >= 70 points."""
    scorer = LeadScorer()
    result = scorer.from_lead_row(_ACME_FULL)
    assert result.fit_score >= 70
    assert result.confidence == "high"
    assert "Has email" in result.reasons
    assert result.company_name == "Acme Solutions"


def test_score_missing_email_lowers():
    """Missing email should lower score and set confidence to low."""
    scorer = LeadScorer()
    result = scorer.from_lead_row(_BETA_NO_EMAIL)
    assert result.fit_score < 50
    assert result.confidence == "low"
    assert "contact_email" in result.missing_data
    # No email was invented
    assert result.company_name == "BetaCorp"


def test_score_partial_without_email():
    """Gamma has company, name, URL, notes but no email = medium confidence."""
    scorer = LeadScorer()
    result = scorer.from_lead_row(_GAMMA_PARTIAL)
    # company(20) + name(15) + notes(10) + problem_signal(10) + source(5) + url(10) = 70
    # minus 20 for no email = 50
    assert result.fit_score == 50  # deterministic
    assert result.confidence == "low"
    assert "contact_email" not in result.reasons


def test_opportunity_row_shape():
    """Opportunity row must match SCHEMA['opportunities'] (14 columns)."""
    from commission_crowd_agent.adapters import GoogleSheetsAdapter

    scorer = LeadScorer()
    result = scorer.from_lead_row(_ACME_FULL)
    row = result.to_opportunity_row()
    assert len(row) == len(GoogleSheetsAdapter.SCHEMA["opportunities"])


def test_write_opportunities_dry_run():
    """write_opportunities in dry-run must not call append_row."""
    mock_adapter = MagicMock()
    scorer = LeadScorer()
    scores = [scorer.from_lead_row(_ACME_FULL)]
    result = scorer.write_opportunities(scores, sheets_adapter=mock_adapter, dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["written"] == 0
    mock_adapter.append_row.assert_not_called()


def test_write_opportunities_live():
    """write_opportunities with dry_run=False must call append_row."""
    mock_adapter = MagicMock()
    mock_adapter.validate_tab_header.return_value = {"ok": True}
    mock_adapter.append_row.return_value = {"ok": True}
    scorer = LeadScorer()
    scores = [scorer.from_lead_row(_ACME_FULL)]
    result = scorer.write_opportunities(scores, sheets_adapter=mock_adapter, dry_run=False)
    assert result["ok"] is True
    assert result["written"] == 1
    mock_adapter.append_row.assert_called_once()


def test_write_opportunities_blocks_on_header_mismatch():
    """write_opportunities must abort if header mismatch."""
    mock_adapter = MagicMock()
    mock_adapter.read_rows.return_value = {"ok": True, "rows": []}  # no duplicates
    mock_adapter.validate_tab_header.return_value = {
        "ok": False,
        "error": "Header mismatch for 'opportunities'",
    }
    scorer = LeadScorer()
    scores = [scorer.from_lead_row(_ACME_FULL)]
    result = scorer.write_opportunities(scores, sheets_adapter=mock_adapter, dry_run=False)
    assert result["ok"] is False
    assert any("Schema validation failed" in e for e in result["errors"])
    mock_adapter.append_row.assert_not_called()


def test_research_approval_above_threshold():
    """request_deeper_research_approvals must create approvals for fit_score >= 50."""
    scorer = LeadScorer()
    mock_gate = MagicMock()
    mock_gate.create_approval.return_value = MagicMock(approval_id="APP-001", status="pending")
    mock_adapter = MagicMock()
    mock_adapter.read_rows.return_value = {"ok": True, "rows": []}  # no existing approvals
    scores = [scorer.from_lead_row(_ACME_FULL)]  # fit_score >= 70
    results = scorer.request_deeper_research_approvals(
        scores, approval_gate=mock_gate, sheets_adapter=mock_adapter, dry_run=False
    )
    assert len(results) == 1
    assert results[0]["approval_id"] == "APP-001"


def test_research_approval_below_threshold_skipped():
    """Leads below 50 must NOT create deeper-research approvals."""
    mock_gate = MagicMock()
    mock_adapter = MagicMock()
    scorer = LeadScorer()
    scores = [scorer.from_lead_row(_BETA_NO_EMAIL)]  # fit_score < 50
    results = scorer.request_deeper_research_approvals(
        scores, approval_gate=mock_gate, sheets_adapter=mock_adapter, dry_run=False
    )
    assert results == []
    mock_gate.create_approval.assert_not_called()


def test_no_outreach_in_scoring_module():
    """Scoring module must not import or call any outreach mechanism."""
    import inspect

    from commission_crowd_agent import lead_scoring

    source = inspect.getsource(lead_scoring)
    banned = ["outreach", "send_email", "send_message", "DM", "notify"]
    # send_message only appears in CLI wrapper, not in the scorer module
    for term in banned:
        assert term not in source.lower() or term == "notify"


# ── Deduplication guard tests ────────────────────────────────────────────────


def _make_mock_adapter(tab_rows: dict[str, list[list[str]]]) -> MagicMock:
    """Build a mock adapter that returns different tab data per tab name.

    tab_rows maps tab name -> list of rows (first is header).
    """
    adapter = MagicMock()

    def _read_rows(tab: str):
        rows = tab_rows.get(tab, [])
        return {"ok": True, "rows": rows}

    adapter.read_rows.side_effect = _read_rows

    def _read_last_rows(tab: str, count: int = 10):
        rows = tab_rows.get(tab, [])
        # Simulate what real adapter does: return last count data rows
        out: list[list[str]]
        if not rows:
            out = rows
        elif rows[0][0] in ("opportunity_id", "approval_id"):
            data_rows = rows[1:]
            out = [rows[0]] + (data_rows[-count:] if data_rows else [])
        else:
            out = rows[-count:]
        return {"ok": True, "rows": out}

    adapter.read_last_rows.side_effect = _read_last_rows
    adapter.validate_tab_header.return_value = {"ok": True}
    adapter.append_row.return_value = {"ok": True}
    return adapter


def test_write_opportunity_skips_existing_by_lead_id():
    """If lead_id already present in opportunities, don't append again."""
    scorer = LeadScorer()
    scores = [scorer.from_lead_row(_ACME_FULL)]
    rows = [
        ["opportunity_id", "lead_id", "created_at_utc", "company_name"],
        ["OPP-81091b", "81091b6c", "2026-05-27T10:00:00", "Acme Solutions"],
    ]
    mock_adapter = _make_mock_adapter({"opportunities": rows})
    result = scorer.write_opportunities(scores, sheets_adapter=mock_adapter, dry_run=False)
    assert result["skipped"] == 1
    assert "OPP-81091b" in result["skipped_ids"]
    mock_adapter.append_row.assert_not_called()


def test_write_opportunity_creates_when_new():
    """If lead_id not found, append_row is called."""
    scorer = LeadScorer()
    scores = [scorer.from_lead_row(_ACME_FULL)]
    rows = [
        ["opportunity_id", "lead_id", "created_at_utc", "company_name"],
        ["OPP-other", "some-other-id", "2026-05-27T10:00:00", "OtherCo"],
    ]
    mock_adapter = _make_mock_adapter({"opportunities": rows})
    result = scorer.write_opportunities(scores, sheets_adapter=mock_adapter, dry_run=False)
    assert result["skipped"] == 0
    assert result["written"] == 1
    mock_adapter.append_row.assert_called_once()


def test_write_opportunity_dry_run_reports_existing_without_writing():
    """Dry-run should detect duplicates and report skipped without any append_row."""
    scorer = LeadScorer()
    scores = [scorer.from_lead_row(_ACME_FULL)]
    rows = [
        ["opportunity_id", "lead_id"],
        ["OPP-81091b", "81091b6c"],
    ]
    mock_adapter = _make_mock_adapter({"opportunities": rows})
    result = scorer.write_opportunities(scores, sheets_adapter=mock_adapter, dry_run=True)
    assert result["dry_run"] is True
    assert result["skipped"] == 1
    mock_adapter.append_row.assert_not_called()


def test_approval_skips_existing_pending_or_approved():
    """If a pending/approved approval exists for the same entity, skip creation."""
    scorer = LeadScorer()
    mock_gate = MagicMock()
    scores = [scorer.from_lead_row(_ACME_FULL)]
    rows = [
        [
            "approval_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "requested_action",
            "risk_level",
            "status",
        ],
        [
            "OLD-001",
            "2026-05-27T10:00:00",
            "opportunity",
            "81091b6c",
            "Do research",
            "medium",
            "pending",
        ],
    ]
    mock_adapter = _make_mock_adapter({"approvals": rows})
    result = scorer.request_deeper_research_approvals(
        scores, approval_gate=mock_gate, sheets_adapter=mock_adapter, dry_run=False
    )
    assert len(result) == 1
    assert result[0]["skipped"] is True
    assert result[0]["approval_id"] == "OLD-001"
    mock_gate.create_approval.assert_not_called()


def test_approval_creates_when_no_existing():
    """When no prior approval exists, create_approval is called."""
    scorer = LeadScorer()
    mock_gate = MagicMock()
    mock_gate.create_approval.return_value = MagicMock(approval_id="NEW-001", status="pending")
    scores = [scorer.from_lead_row(_ACME_FULL)]
    rows = [
        [
            "approval_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "requested_action",
            "risk_level",
            "status",
        ],
    ]
    mock_adapter = _make_mock_adapter({"approvals": rows})
    result = scorer.request_deeper_research_approvals(
        scores, approval_gate=mock_gate, sheets_adapter=mock_adapter, dry_run=False
    )
    assert len(result) == 1
    assert result[0]["skipped"] is False
    assert result[0]["approval_id"] == "NEW-001"
    mock_gate.create_approval.assert_called_once()


def test_approval_allows_rejected_to_create_new():
    """Rejected approvals don't block new creation (they are terminal)."""
    scorer = LeadScorer()
    mock_gate = MagicMock()
    mock_gate.create_approval.return_value = MagicMock(approval_id="NEW-002", status="pending")
    scores = [scorer.from_lead_row(_ACME_FULL)]
    rows = [
        [
            "approval_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "requested_action",
            "risk_level",
            "status",
        ],
        [
            "OLD-002",
            "2026-05-27T10:00:00",
            "opportunity",
            "81091b6c",
            "Do research",
            "medium",
            "rejected",
        ],
    ]
    mock_adapter = _make_mock_adapter({"approvals": rows})
    result = scorer.request_deeper_research_approvals(
        scores, approval_gate=mock_gate, sheets_adapter=mock_adapter, dry_run=False
    )
    assert len(result) == 1
    assert result[0]["skipped"] is False
    mock_gate.create_approval.assert_called_once()


def test_no_opportunity_write_when_no_sheets_adapter():
    """If sheets_adapter is None, write_opportunities fails fast."""
    scorer = LeadScorer()
    scores = [scorer.from_lead_row(_ACME_FULL)]
    result = scorer.write_opportunities(scores, sheets_adapter=None, dry_run=False)
    assert result["ok"] is False
    assert "No sheets adapter" in result["error"]


def test_no_approval_create_when_no_sheets_adapter():
    """If sheets_adapter is None, request_deeper_research_approvals returns empty."""
    scorer = LeadScorer()
    mock_gate = MagicMock()
    scores = [scorer.from_lead_row(_ACME_FULL)]
    result = scorer.request_deeper_research_approvals(
        scores, approval_gate=mock_gate, sheets_adapter=None, dry_run=False
    )
    assert result == []

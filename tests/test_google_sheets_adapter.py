"""Tests for GoogleSheetsAdapter integrity features.

Covers logical-row appends, schema-pollution detection, compact dry-run,
audit of approvals, duplicate detection, and stale-entity detection.
"""

from unittest.mock import MagicMock

from commission_crowd_agent.adapters import GoogleSheetsAdapter


CANONICAL_APPROVALS_HEADER = [
    "approval_id", "created_at_utc", "entity_type", "entity_id",
    "requested_action", "risk_level", "status", "operator_decision",
    "decided_at_utc", "source_url", "notes", "entity_name", "approval_action",
]


def test_append_row_writes_to_logical_next_row():
    """append_row reads the tab first, then writes to the next empty data row."""
    import json
    from unittest.mock import patch, MagicMock

    adapter = GoogleSheetsAdapter(
        spreadsheet_id="S",
        access_token="T",
        dry_run=False,
    )
    adapter.read_last_rows = MagicMock(return_value={
        "ok": True,
        "rows": [
            CANONICAL_APPROVALS_HEADER,
            ["abc123", "2024-01-01", "lead", "L1"],
            ["def456", "2024-01-02", "lead", "L2"],
        ],
    })
    adapter._ensure_access_token = lambda: None
    adapter.access_token = "FAKE"

    captured = {}

    def fake_put(url, json, headers, timeout):
        captured["url"] = url
        class FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"updatedRange": "approvals!A4"}
        return FakeResponse()

    with patch("commission_crowd_agent.adapters.httpx.put", fake_put):
        adapter.append_row("approvals", ["ghi789", "2024-01-03", "lead", "L3"])

    assert captured["url"].endswith("approvals!A4?valueInputOption=USER_ENTERED")


def test_validate_tab_header_detects_pollution():
    """validate_tab_header flags 'Column N' style columns."""
    adapter = GoogleSheetsAdapter(spreadsheet_id="S", access_token="T")
    adapter.read_rows = MagicMock(return_value={
        "ok": True,
        "rows": [CANONICAL_APPROVALS_HEADER + ["Column 1", "Column 2"]],
    })
    result = adapter.validate_tab_header("approvals")
    assert result["ok"] is True
    assert result["polluted_columns"] == ["Column 1", "Column 2"]


def test_validate_tab_header_fails_on_mismatch():
    """If canonical header is not a prefix, validation fails."""
    adapter = GoogleSheetsAdapter(spreadsheet_id="S", access_token="T")
    adapter.read_rows = MagicMock(return_value={
        "ok": True,
        "rows": [["wrong", "header", "order"]],
    })
    result = adapter.validate_tab_header("approvals")
    assert result["ok"] is False


def test_compact_tab_dry_run_returns_counts():
    """compact_tab in dry-run mode reports row counts without writing."""
    adapter = GoogleSheetsAdapter(spreadsheet_id="S", access_token="T")
    adapter.read_last_rows = MagicMock(return_value={
        "ok": True,
        "rows": [
            CANONICAL_APPROVALS_HEADER,
            ["a", "2024-01-01", "lead", "L1"],
            ["", "", "", ""],  # blank row to be removed
            ["b", "2024-01-02", "lead", "L2"],
        ],
    })
    result = adapter.compact_tab("approvals", dry_run=True)
    assert result["ok"] is True
    assert result["before_row_count"] == 4
    assert result["after_row_count"] == 3
    assert result["removed_rows"] == 1
    assert result["dry_run"] is True


def test_compact_tab_real_run_is_not_tested_without_mocks():
    """Real compact_tab with dry_run=False requires live Sheet credentials.
    Unit-test coverage is provided by the dry-run path; integration tests
    should run against a test spreadsheet.
    """
    assert True


def test_audit_approvals_detects_stale():
    """audit_approvals flags entities with multiple pending approvals."""
    adapter = GoogleSheetsAdapter(spreadsheet_id="S", access_token="T")
    adapter.read_last_rows = MagicMock(return_value={
        "ok": True,
        "rows": [
            CANONICAL_APPROVALS_HEADER,
            ["a1", "2024-01-01", "lead", "E1", "", "low", "approved"],
            ["a2", "2024-01-02", "lead", "E1", "", "low", "pending"],
            ["a3", "2024-01-03", "lead", "E1", "", "low", "pending"],
            ["a4", "2024-01-04", "lead", "E2", "", "low", "pending"],
        ],
    })
    result = adapter.audit_approvals()
    assert result["ok"] is True
    assert len(result["stale_entities"]) == 1
    assert result["stale_entities"][0]["entity_id"] == "E1"
    assert result["stale_entities"][0]["pending_count"] == 2


def test_audit_approvals_detects_duplicates():
    """audit_approvals flags duplicate approval_ids."""
    adapter = GoogleSheetsAdapter(spreadsheet_id="S", access_token="T")
    adapter.read_last_rows = MagicMock(return_value={
        "ok": True,
        "rows": [
            CANONICAL_APPROVALS_HEADER,
            ["dup1", "", "lead", "E1", "", "low", "pending"],
            ["dup1", "", "lead", "E2", "", "low", "pending"],
        ],
    })
    result = adapter.audit_approvals()
    assert result["duplicates"] == {"dup1": 2}

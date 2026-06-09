"""Tests for CRM pipeline module.

All external calls are mocked via MagicMock adapter.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from commission_crowd_agent.crm_pipeline import CRMPipeline, _make_record
from commission_crowd_agent.domain import OpportunityStage


@pytest.fixture
def mock_adapter():
    """Return a mocked GoogleSheetsAdapter."""
    return MagicMock()


@pytest.fixture
def pipeline(mock_adapter):
    """Return a CRMPipeline wired to the mock adapter."""
    return CRMPipeline(sheets_adapter=mock_adapter)


class TestMakeRecord:
    def test_basic(self) -> None:
        header = ["a", "b", "c"]
        row = ["1", "2"]
        record = _make_record(header, row)
        assert record == {"a": "1", "b": "2", "c": ""}


class TestAddLead:
    def test_add_lead_dry_run(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        result = pipeline.add_lead(
            lead_id="L001",
            company_name="Acme Corp",
            contact_name="Alice",
            contact_email="alice@acme.com",
            source="web_search",
            dry_run=True,
        )
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["lead_id"] == "L001"
        mock_adapter.append_row.assert_not_called()

    def test_add_lead_live(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.append_row.return_value = {"ok": True}
        result = pipeline.add_lead(
            lead_id="L001",
            company_name="Acme Corp",
            contact_name="Alice",
            contact_email="alice@acme.com",
            dry_run=False,
        )
        assert result["ok"] is True
        assert result["dry_run"] is False
        assert result["lead_id"] == "L001"
        mock_adapter.append_row.assert_called_once()
        call_args = mock_adapter.append_row.call_args[0]
        assert call_args[0] == "leads"
        assert call_args[1][0] == "L001"
        assert call_args[1][5] == "Alice"
        assert call_args[1][13] == OpportunityStage.SOURCED


class TestUpdateStage:
    def test_update_stage_dry_run(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                [
                    "lead_id",
                    "created_at_utc",
                    "source",
                    "source_url",
                    "company_name",
                    "contact_name",
                    "contact_email",
                    "role_title",
                    "market",
                    "country",
                    "problem_signal",
                    "commission_signal",
                    "fit_score",
                    "status",
                    "notes",
                ],
                [
                    "L001",
                    "2024-01-01",
                    "web_search",
                    "",
                    "Acme",
                    "Alice",
                    "alice@acme.com",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "sourced",
                    "",
                ],
            ],
        }
        result = pipeline.update_stage("L001", OpportunityStage.RESEARCHED, dry_run=True)
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["new_stage"] == OpportunityStage.RESEARCHED
        mock_adapter.upsert_row_by_key.assert_not_called()

    def test_update_stage_live(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                [
                    "lead_id",
                    "created_at_utc",
                    "source",
                    "source_url",
                    "company_name",
                    "contact_name",
                    "contact_email",
                    "role_title",
                    "market",
                    "country",
                    "problem_signal",
                    "commission_signal",
                    "fit_score",
                    "status",
                    "notes",
                ],
                [
                    "L001",
                    "2024-01-01",
                    "web_search",
                    "",
                    "Acme",
                    "Alice",
                    "alice@acme.com",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "sourced",
                    "",
                ],
            ],
        }
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.update_stage("L001", OpportunityStage.RESEARCHED, dry_run=False)
        assert result["ok"] is True
        assert result["dry_run"] is False
        mock_adapter.upsert_row_by_key.assert_called_once()

    def test_update_stage_not_found(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                [
                    "lead_id",
                    "created_at_utc",
                    "source",
                    "source_url",
                    "company_name",
                    "contact_name",
                    "contact_email",
                    "role_title",
                    "market",
                    "country",
                    "problem_signal",
                    "commission_signal",
                    "fit_score",
                    "status",
                    "notes",
                ],
                [
                    "L002",
                    "2024-01-01",
                    "web_search",
                    "",
                    "Acme",
                    "Alice",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "sourced",
                    "",
                ],
            ],
        }
        result = pipeline.update_stage("L001", OpportunityStage.RESEARCHED, dry_run=False)
        assert result["ok"] is False
        assert "not found" in result["error"]


class TestGetPipeline:
    def test_empty_tab(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [],
        }
        result = pipeline.get_pipeline()
        assert result["ok"] is True
        assert result["stages"] == {}

    def test_grouped_stages(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        header = [
            "lead_id",
            "created_at_utc",
            "source",
            "source_url",
            "company_name",
            "contact_name",
            "contact_email",
            "role_title",
            "market",
            "country",
            "problem_signal",
            "commission_signal",
            "fit_score",
            "status",
            "notes",
        ]
        mock_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                header,
                [
                    "L001",
                    "2024-01-01",
                    "",
                    "",
                    "Acme",
                    "Alice",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    OpportunityStage.SOURCED,
                    "",
                ],
                [
                    "L002",
                    "2024-01-02",
                    "",
                    "",
                    "Globex",
                    "Bob",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    OpportunityStage.RESEARCHED,
                    "",
                ],
                [
                    "L003",
                    "2024-01-03",
                    "",
                    "",
                    "Stark",
                    "Carol",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    OpportunityStage.SOURCED,
                    "",
                ],
            ],
        }
        result = pipeline.get_pipeline()
        assert result["ok"] is True
        stages = result["stages"]
        assert len(stages.get(OpportunityStage.SOURCED, [])) == 2
        assert len(stages.get(OpportunityStage.RESEARCHED, [])) == 1
        assert stages[OpportunityStage.SOURCED][0]["company_name"] == "Acme"


class TestGetHotLeads:
    def test_no_sheets_adapter(self) -> None:
        pipeline = CRMPipeline(sheets_adapter=None)  # type: ignore[arg-type]
        result = pipeline.get_hot_leads(min_score=50)
        assert result["ok"] is False
        assert "No sheets adapter" in result["error"]

    def test_hot_leads_filter(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        header = [
            "lead_id",
            "created_at_utc",
            "source",
            "source_url",
            "company_name",
            "contact_name",
            "contact_email",
            "role_title",
            "market",
            "country",
            "problem_signal",
            "commission_signal",
            "fit_score",
            "status",
            "notes",
        ]
        mock_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                header,
                [
                    "L001",
                    "2024-01-01",
                    "",
                    "",
                    "Acme",
                    "Alice",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "sourced",
                    "",
                ],
                [
                    "L002",
                    "2024-01-02",
                    "",
                    "",
                    "Globex",
                    "Bob",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "55",
                    "sourced",
                    "",
                ],
                [
                    "L003",
                    "2024-01-03",
                    "",
                    "",
                    "Stark",
                    "Carol",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "70",
                    "researched",
                    "",
                ],
            ],
        }
        result = pipeline.get_hot_leads(min_score=50)
        assert result["ok"] is True
        assert len(result["leads"]) == 2
        ids = {lead["lead_id"] for lead in result["leads"]}
        assert ids == {"L002", "L003"}


class TestLogTouchpoint:
    def test_log_touchpoint_dry_run(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        result = pipeline.log_touchpoint(
            opportunity_id="OPP001",
            lead_id="L001",
            template_id="cold_intro",
            subject_line="Hello",
            body_preview="Hello...",
            status="draft",
            dry_run=True,
        )
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["tab"] == "outreach_log"
        mock_adapter.append_row.assert_not_called()

    def test_log_touchpoint_live(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.append_row.return_value = {"ok": True}
        result = pipeline.log_touchpoint(
            opportunity_id="OPP001",
            lead_id="L001",
            template_id="cold_intro",
            subject_line="Hello",
            body_preview="Hello...",
            status="draft",
            dry_run=False,
        )
        assert result["ok"] is True
        assert result["dry_run"] is False
        mock_adapter.append_row.assert_called_once()
        call_args = mock_adapter.append_row.call_args[0]
        assert call_args[0] == "outreach_log"
        assert call_args[1][3] == "L001"
        assert call_args[1][5] == "Hello"

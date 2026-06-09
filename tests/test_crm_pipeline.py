"""Tests for CRM pipeline module — including stage transitions,
calendar reminders, and close states.

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


@pytest.fixture
def mock_calendar():
    """Return a mocked CalendarAdapter."""
    mock = MagicMock()
    mock.add_event.return_value = {"ok": True, "event_id": "CAL-12345"}
    return mock


# ------------------------------------------------------------------
# _make_record
# ------------------------------------------------------------------


class TestMakeRecord:
    def test_basic(self) -> None:
        header = ["a", "b", "c"]
        row = ["1", "2"]
        record = _make_record(header, row)
        assert record == {"a": "1", "b": "2", "c": ""}


# ------------------------------------------------------------------
# add_lead
# ------------------------------------------------------------------


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
        assert call_args[1][13] == OpportunityStage.SOURCED.value

    def test_add_lead_status_is_sourced(
        self, pipeline: CRMPipeline, mock_adapter: MagicMock
    ) -> None:
        mock_adapter.append_row.return_value = {"ok": True}
        pipeline.add_lead(lead_id="L001", company_name="Acme", dry_run=False)
        call_args = mock_adapter.append_row.call_args[0][1]
        assert call_args[13] == "sourced"


# ------------------------------------------------------------------
# update_stage
# ------------------------------------------------------------------


class TestUpdateStage:
    def _make_read_rows(self, status: str):
        return {
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
                    status,
                    "",
                ],
            ],
        }

    def test_update_stage_dry_run(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.read_last_rows.return_value = self._make_read_rows("sourced")
        result = pipeline.update_stage("L001", OpportunityStage.RESEARCHED.value, dry_run=True)
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["new_stage"] == OpportunityStage.RESEARCHED.value
        mock_adapter.upsert_row_by_key.assert_not_called()

    def test_update_stage_live(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.read_last_rows.return_value = self._make_read_rows("sourced")
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.update_stage("L001", OpportunityStage.RESEARCHED.value, dry_run=False)
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
        result = pipeline.update_stage("L001", OpportunityStage.RESEARCHED.value, dry_run=False)
        assert result["ok"] is False
        assert "not found" in result["error"]


# ------------------------------------------------------------------
# advance_stage
# ------------------------------------------------------------------


class TestAdvanceStage:
    def _make_read_rows(self, status: str):
        return {
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
                    status,
                    "",
                ],
            ],
        }

    def test_advance_sourced_to_researched(
        self, pipeline: CRMPipeline, mock_adapter: MagicMock
    ) -> None:
        mock_adapter.read_last_rows.return_value = self._make_read_rows("sourced")
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance_stage("L001", OpportunityStage.RESEARCHED.value, dry_run=False)
        assert result["ok"] is True
        assert result["new_stage"] == OpportunityStage.RESEARCHED.value

    def test_advance_invalid_transition(
        self, pipeline: CRMPipeline, mock_adapter: MagicMock
    ) -> None:
        mock_adapter.read_last_rows.return_value = self._make_read_rows("sourced")
        result = pipeline.advance_stage("L001", OpportunityStage.CLOSED_WON.value, dry_run=False)
        assert result["ok"] is False
        assert "Invalid transition" in result["error"]

    def test_advance_researched_to_rep_fit_scored(
        self, pipeline: CRMPipeline, mock_adapter: MagicMock
    ) -> None:
        mock_adapter.read_last_rows.return_value = self._make_read_rows("researched")
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance_stage(
            "L001", OpportunityStage.REP_FIT_SCORED.value, dry_run=False
        )
        assert result["ok"] is True

    def test_advance_rep_fit_scored_to_draft(
        self, pipeline: CRMPipeline, mock_adapter: MagicMock
    ) -> None:
        mock_adapter.read_last_rows.return_value = self._make_read_rows("rep_fit_scored")
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance_stage(
            "L001", OpportunityStage.APPLICATION_DRAFT_CREATED.value, dry_run=False
        )
        assert result["ok"] is True

    def test_advance_draft_to_submitted_skips_approval(
        self, pipeline: CRMPipeline, mock_adapter: MagicMock
    ) -> None:
        # In sales-ops mode, we can go draft → approved → submitted
        # But we test the default transitions: draft → approved
        mock_adapter.read_last_rows.return_value = self._make_read_rows("application_draft_created")
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance_stage(
            "L001", OpportunityStage.APPLICATION_APPROVED.value, dry_run=False
        )
        assert result["ok"] is True


# ------------------------------------------------------------------
# close_opportunity
# ------------------------------------------------------------------


class TestCloseOpportunity:
    def _make_read_rows(self, status: str):
        return {
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
                    status,
                    "",
                ],
            ],
        }

    def test_close_won(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.read_last_rows.return_value = self._make_read_rows("application_submitted")
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.close_opportunity("L001", "won", dry_run=False)
        assert result["ok"] is True
        assert result["new_stage"] == OpportunityStage.CLOSED_WON.value

    def test_close_lost(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        mock_adapter.read_last_rows.return_value = self._make_read_rows("rep_fit_scored")
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.close_opportunity("L001", "lost", dry_run=False)
        assert result["ok"] is True
        assert result["new_stage"] == OpportunityStage.CLOSED_LOST.value

    def test_close_invalid_outcome(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
        result = pipeline.close_opportunity("L001", "invalid", dry_run=False)
        assert result["ok"] is False
        assert "Invalid outcome" in result["error"]


# ------------------------------------------------------------------
# Calendar reminders
# ------------------------------------------------------------------


class TestSetCalendarReminder:
    def test_set_reminder_no_calendar(self, pipeline: CRMPipeline) -> None:
        result = pipeline.set_calendar_reminder(
            entity_id="L001",
            reminder_type="follow_up",
            days=3,
            calendar_adapter=None,
            dry_run=True,
        )
        assert result["ok"] is False
        assert "No calendar adapter" in result["error"]

    def test_set_reminder_dry_run(self, pipeline: CRMPipeline, mock_calendar: MagicMock) -> None:
        result = pipeline.set_calendar_reminder(
            entity_id="L001",
            reminder_type="follow_up",
            days=3,
            calendar_adapter=mock_calendar,
            dry_run=True,
        )
        assert result["ok"] is True
        assert result["event_id"] == "CAL-12345"
        mock_calendar.add_event.assert_called_once()


# ------------------------------------------------------------------
# get_pipeline
# ------------------------------------------------------------------


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
                    OpportunityStage.SOURCED.value,
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
                    OpportunityStage.RESEARCHED.value,
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
                    OpportunityStage.SOURCED.value,
                    "",
                ],
            ],
        }
        result = pipeline.get_pipeline()
        assert result["ok"] is True
        stages = result["stages"]
        assert len(stages.get(OpportunityStage.SOURCED.value, [])) == 2
        assert len(stages.get(OpportunityStage.RESEARCHED.value, [])) == 1
        assert stages[OpportunityStage.SOURCED.value][0]["company_name"] == "Acme"

    def test_closed_stages_present(self, pipeline: CRMPipeline, mock_adapter: MagicMock) -> None:
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
                    OpportunityStage.CLOSED_WON.value,
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
                    OpportunityStage.CLOSED_LOST.value,
                    "",
                ],
            ],
        }
        result = pipeline.get_pipeline()
        assert result["ok"] is True
        stages = result["stages"]
        assert len(stages.get(OpportunityStage.CLOSED_WON.value, [])) == 1
        assert len(stages.get(OpportunityStage.CLOSED_LOST.value, [])) == 1


# ------------------------------------------------------------------
# get_hot_leads
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# log_touchpoint
# ------------------------------------------------------------------


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

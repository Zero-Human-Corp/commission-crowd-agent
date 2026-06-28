"""Tests for the SalesOpsPipeline end-to-end sales operations module.

Mocks all external adapters (Sheets, Calendar, SMTP).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from commission_crowd_agent.domain import OpportunityStage
from commission_crowd_agent.sales_ops import SalesOpsPipeline


@pytest.fixture
def mock_sheets():
    return MagicMock()


@pytest.fixture
def mock_calendar():
    m = MagicMock()
    m.add_event.return_value = {"ok": True, "event_id": "CAL-999"}
    m.list_upcoming_events.return_value = {"ok": True, "events": []}
    return m


@pytest.fixture
def mock_outreach():
    m = MagicMock()
    m.send_email.return_value = {"ok": True, "dry_run": True}
    m.send_from_template.return_value = {"ok": True, "dry_run": True}
    return m


@pytest.fixture
def pipeline(mock_sheets, mock_calendar, mock_outreach):
    return SalesOpsPipeline(
        sheets_adapter=mock_sheets,
        calendar_adapter=mock_calendar,
        outreach_adapter=mock_outreach,
    )


@pytest.fixture
def pipeline_no_outreach(mock_sheets, mock_calendar):
    """Pipeline without SMTP (tests auto-creation)."""
    return SalesOpsPipeline(
        sheets_adapter=mock_sheets,
        calendar_adapter=mock_calendar,
        outreach_adapter=None,
    )


class TestIngestLead:
    def test_ingest_dry_run(self, pipeline, mock_sheets, mock_calendar) -> None:
        mock_sheets.append_row.return_value = {"ok": True}
        result = pipeline.ingest_lead(
            lead_id="L001",
            company_name="Acme",
            dry_run=True,
        )
        assert result["ok"] is True
        mock_sheets.append_row.assert_not_called()

    def test_ingest_live_creates_reminder(self, pipeline, mock_sheets, mock_calendar) -> None:
        mock_sheets.append_row.return_value = {"ok": True}
        mock_sheets.read_last_rows.return_value = {
            "ok": True,
            "rows": [],
        }
        result = pipeline.ingest_lead(
            lead_id="L001",
            company_name="Acme",
            dry_run=False,
        )
        assert result["ok"] is True
        mock_sheets.append_row.assert_called_once()
        mock_calendar.add_event.assert_called_once()
        assert result.get("reminder_event_id") == "CAL-999"


class TestAdvance:
    def _read_rows(self, status: str):
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

    def test_advance_sourced_to_researched(self, pipeline, mock_sheets, mock_calendar) -> None:
        mock_sheets.read_last_rows.return_value = self._read_rows("sourced")
        mock_sheets.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance("L001", OpportunityStage.RESEARCHED.value, dry_run=False)
        assert result["ok"] is True
        assert result["new_stage"] == "researched"
        assert result.get("next_stage") is not None
        assert result.get("stage_description") is not None

    def test_advance_invalid_transition(self, pipeline, mock_sheets) -> None:
        mock_sheets.read_last_rows.return_value = self._read_rows("sourced")
        result = pipeline.advance("L001", OpportunityStage.CLOSED_WON.value, dry_run=False)
        assert result["ok"] is False
        assert "Invalid transition" in result["error"]

    def test_advance_to_submitted(self, pipeline, mock_sheets, mock_calendar) -> None:
        # Wave 3 Track A: application_submitted is identity-gated. Wire a
        # verified+reconciled registry record so the gate passes (mirrors the
        # pattern in tests/test_identity_gate.py::test_verified_and_reconciled_proceeds).
        from commission_crowd_agent.state_registry import (
            IDENTITY_RECONCILED_DISPOSITION,
            IDENTITY_VERIFIED_STATUS,
            OpportunityStateRegistry,
        )

        registry = OpportunityStateRegistry()
        rec = registry._get_or_create("L001")
        rec.record_identity_verification(
            IDENTITY_VERIFIED_STATUS, disposition=IDENTITY_RECONCILED_DISPOSITION
        )
        pipeline.crm.attach_registry(registry)

        mock_sheets.read_last_rows.return_value = self._read_rows("application_approved")
        mock_sheets.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance(
            "L001", OpportunityStage.APPLICATION_SUBMITTED.value, dry_run=False
        )
        assert result["ok"] is True
        assert result["new_stage"] == "application_submitted"


class TestAdvanceToNext:
    def _read_rows(self, status: str):
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

    def test_advance_to_next_sourced(self, pipeline, mock_sheets) -> None:
        mock_sheets.read_last_rows.return_value = self._read_rows("sourced")
        mock_sheets.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance_to_next("L001", dry_run=False)
        assert result["ok"] is True
        assert result["new_stage"] == "researched"

    def test_advance_to_next_not_found(self, pipeline, mock_sheets) -> None:
        mock_sheets.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                ["lead_id", "status"],
                ["L999", "sourced"],
            ],
        }
        result = pipeline.advance_to_next("L001", dry_run=False)
        assert result["ok"] is False
        assert "not found" in result["error"]


class TestCloseOpportunity:
    def _read_rows(self, status: str):
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

    def test_close_won(self, pipeline, mock_sheets) -> None:
        mock_sheets.read_last_rows.return_value = self._read_rows("selling_active")
        mock_sheets.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.close_opportunity("L001", "won", dry_run=False)
        assert result["ok"] is True
        assert result["new_stage"] == OpportunityStage.CLOSED_WON.value

    def test_close_lost(self, pipeline, mock_sheets) -> None:
        mock_sheets.read_last_rows.return_value = self._read_rows("application_submitted")
        mock_sheets.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.close_opportunity("L001", "lost", dry_run=False)
        assert result["ok"] is True
        assert result["new_stage"] == OpportunityStage.CLOSED_LOST.value

    def test_close_invalid(self, pipeline) -> None:
        result = pipeline.close_opportunity("L001", "maybe", dry_run=False)
        assert result["ok"] is False
        assert "Invalid outcome" in result["error"]


class TestDispatchEmail:
    def test_dispatch_with_template(self, pipeline, mock_outreach) -> None:
        result = pipeline.dispatch_email(
            to_address="alice@example.com",
            template_name="outreach",
            context={
                "company_name": "Acme",
                "contact_name": "Alice",
                "sender_name": "Bob",
                "context": "Hello",
            },
            dry_run=True,
        )
        assert result["ok"] is True
        mock_outreach.send_from_template.assert_called_once()

    def test_dispatch_without_template(self, pipeline, mock_outreach) -> None:
        result = pipeline.dispatch_email(
            to_address="alice@example.com",
            subject="Hi",
            body="Hello",
            dry_run=True,
        )
        assert result["ok"] is True
        mock_outreach.send_email.assert_called_once()


class TestPipelineSummary:
    def test_pipeline_summary(self, pipeline, mock_sheets) -> None:
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
        mock_sheets.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                header,
                ["L001", "", "", "", "Acme", "Alice", "", "", "", "", "", "", "", "sourced", ""],
                ["L002", "", "", "", "Globex", "Bob", "", "", "", "", "", "", "", "researched", ""],
                [
                    "L003",
                    "",
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
                    "closed_won",
                    "",
                ],
            ],
        }
        result = pipeline.pipeline_summary()
        assert result["ok"] is True
        assert result["total"] == 3
        assert result["open"] == 2
        assert result["closed_won"] == 1
        assert result["closed_lost"] == 0

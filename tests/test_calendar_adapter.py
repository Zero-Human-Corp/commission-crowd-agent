"""Tests for enhanced CalendarAdapter capabilities.

All external calls are mocked; no live Calendar API usage.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from commission_crowd_agent.calendar_adapter import CalendarAdapter


@pytest.fixture
def adapter():
    return CalendarAdapter(dry_run=True)


@pytest.fixture
def mock_sheets_adapter():
    """Return a mocked GoogleSheetsAdapter."""
    return MagicMock()


class TestCreateEvent:
    def test_create_event_dry_run(
        self, adapter: CalendarAdapter, mock_sheets_adapter: MagicMock
    ) -> None:
        result = adapter.create_event(
            title="Demo call",
            start="2024-06-10T09:00",
            end="2024-06-10T10:00",
            description="Test call",
            attendees=["a@example.com"],
            sheets_adapter=mock_sheets_adapter,
        )
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["title"] == "Demo call"
        assert result["attendees"] == ["a@example.com"]
        mock_sheets_adapter.append_row.assert_called_once()

    def test_create_event_live_success(self, mock_sheets_adapter: MagicMock) -> None:
        adapter = CalendarAdapter(
            calendar_id="test-cal",
            credentials_path="",
            dry_run=False,
        )
        adapter.access_token = "FAKE"

        import httpx

        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                pass

            @staticmethod
            def json():
                return {"id": "gcal-123"}

        real_post = httpx.post
        call_log = {}

        def fake_post(url, **kwargs):
            call_log["url"] = url
            return FakeResp()

        httpx.post = fake_post
        try:
            result = adapter.create_event(
                title="Demo call",
                start="2024-06-10T09:00",
                end="2024-06-10T10:00",
                description="Test call",
                attendees=["a@example.com"],
                sheets_adapter=mock_sheets_adapter,
            )
            assert result["ok"] is True
            assert result["calendar_event_id"] == "gcal-123"
            assert "test-cal" in call_log["url"]
        finally:
            httpx.post = real_post

    def test_create_event_no_token(
        self, adapter: CalendarAdapter, mock_sheets_adapter: MagicMock
    ) -> None:
        adapter.dry_run = False
        adapter.access_token = ""
        result = adapter.create_event(
            title="Demo call",
            start="2024-06-10T09:00",
            end="2024-06-10T10:00",
            sheets_adapter=mock_sheets_adapter,
        )
        assert result["ok"] is False
        assert "Missing Calendar auth token" in result["error"]


class TestListUpcomingEvents:
    def test_empty(self, adapter: CalendarAdapter, mock_sheets_adapter: MagicMock) -> None:
        mock_sheets_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [],
        }
        result = adapter.list_upcoming_events(days=7, sheets_adapter=mock_sheets_adapter)
        assert result["ok"] is True
        assert result["events"] == []

    def test_within_window(self, adapter: CalendarAdapter, mock_sheets_adapter: MagicMock) -> None:
        from datetime import datetime, timedelta

        future = (datetime.utcnow() + timedelta(days=3)).isoformat()
        header = [
            "event_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "event_type",
            "event_date_utc",
            "event_summary",
            "status",
            "notes",
        ]
        mock_sheets_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                header,
                ["E1", "2024-01-01", "", "", "follow_up", future, "Summary", "open", ""],
            ],
        }
        result = adapter.list_upcoming_events(days=7, sheets_adapter=mock_sheets_adapter)
        assert result["ok"] is True
        assert len(result["events"]) == 1
        assert result["events"][0]["event_summary"] == "Summary"

    def test_outside_window(self, adapter: CalendarAdapter, mock_sheets_adapter: MagicMock) -> None:
        from datetime import datetime, timedelta

        far_future = (datetime.utcnow() + timedelta(days=30)).isoformat()
        header = [
            "event_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "event_type",
            "event_date_utc",
            "event_summary",
            "status",
            "notes",
        ]
        mock_sheets_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                header,
                ["E1", "2024-01-01", "", "", "follow_up", far_future, "Summary", "open", ""],
            ],
        }
        result = adapter.list_upcoming_events(days=7, sheets_adapter=mock_sheets_adapter)
        assert result["ok"] is True
        assert len(result["events"]) == 0


class TestFindNextAvailableSlot:
    def test_empty_sheet(self, adapter: CalendarAdapter, mock_sheets_adapter: MagicMock) -> None:
        mock_sheets_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [],
        }
        result = adapter.find_next_available_slot(
            duration_minutes=60,
            sheets_adapter=mock_sheets_adapter,
        )
        assert result["ok"] is True
        assert "slot_start" in result
        assert "T09:00" in result["slot_start"]

    def test_gap_found(self, adapter: CalendarAdapter, mock_sheets_adapter: MagicMock) -> None:
        from datetime import datetime, timedelta

        tomorrow = (datetime.utcnow() + timedelta(days=1)).date()
        slot1 = f"{tomorrow.isoformat()}T10:00"
        slot2 = f"{tomorrow.isoformat()}T14:00"
        header = [
            "event_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "event_type",
            "event_date_utc",
            "event_summary",
            "status",
            "notes",
        ]
        mock_sheets_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                header,
                ["E1", "2024-01-01", "", "", "meeting", slot1, "Call", "open", ""],
                ["E2", "2024-01-01", "", "", "meeting", slot2, "Call", "open", ""],
            ],
        }
        result = adapter.find_next_available_slot(
            duration_minutes=60,
            sheets_adapter=mock_sheets_adapter,
        )
        assert result["ok"] is True
        assert result["slot_start"].startswith(f"{tomorrow.isoformat()}T09:00")
        assert result["slot_end"].startswith(f"{tomorrow.isoformat()}T10:00")

    def test_no_gap(self, adapter: CalendarAdapter, mock_sheets_adapter: MagicMock) -> None:
        from datetime import datetime, timedelta

        tomorrow = (datetime.utcnow() + timedelta(days=1)).date()
        slot = f"{tomorrow.isoformat()}T09:00"
        header = [
            "event_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "event_type",
            "event_date_utc",
            "event_summary",
            "status",
            "notes",
        ]
        mock_sheets_adapter.read_last_rows.return_value = {
            "ok": True,
            "rows": [
                header,
                ["E1", "2024-01-01", "", "", "meeting", slot, "Call", "open", ""],
            ],
        }
        result = adapter.find_next_available_slot(
            duration_minutes=480,
            sheets_adapter=mock_sheets_adapter,
        )
        assert result["ok"] is True
        # fallback to next day 09:00
        assert "T09:00" in result["slot_start"]

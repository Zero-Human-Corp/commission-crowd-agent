"""Google Calendar integration (service-account based) for CCA.

Tracks:
- Follow-up dates per opportunity
- Application deadlines
- Pending approval reminders

Does NOT send real invites without explicit operator opt-in.
Dry-run by default.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx

from .adapters import GoogleSheetsAdapter


class CalendarAdapter:
    """Calendar adapter using Google Calendar API (service account)."""

    API_BASE = "https://www.googleapis.com/calendar/v3"
    SHEETS_TAB = "calendar_events"
    _SCOPES: list[str] = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    def __init__(
        self,
        calendar_id: str = "primary",
        credentials_path: str = "",
        service_account_json: str = "",
        dry_run: bool = True,
    ) -> None:
        self.calendar_id = calendar_id
        self.credentials_path = credentials_path
        self.service_account_json = service_account_json
        self.dry_run = dry_run
        self.access_token: str = ""

    def _ensure_token(self) -> None:
        if self.access_token:
            return
        sa_info: dict[str, Any] | None = None
        if self.credentials_path:
            try:
                with open(self.credentials_path) as fh:
                    sa_info = json.load(fh)
            except Exception:
                return
        elif self.service_account_json:
            try:
                sa_info = json.loads(self.service_account_json)
            except Exception:
                return
        if sa_info is None:
            return
        try:
            from google.auth.transport import requests as _reqs
            from google.oauth2 import service_account as _sa

            credentials = _sa.Credentials.from_service_account_info(sa_info, scopes=self._SCOPES)  # type: ignore[no-untyped-call]
            credentials.refresh(_reqs.Request())
            self.access_token = credentials.token
        except Exception:
            pass

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _to_sheets_row(self, event: dict[str, Any]) -> list[str]:
        return [
            event["event_id"],
            event["created_at_utc"],
            event.get("entity_type", ""),
            event.get("entity_id", ""),
            event["event_type"],
            event["event_date_utc"],
            event["event_summary"],
            event.get("status", "open"),
            event.get("notes", ""),
        ]

    def add_event(
        self,
        entity_type: str,
        entity_id: str,
        event_type: str,
        event_date_utc: str,
        event_summary: str,
        notes: str = "",
        *,
        sheets_adapter: GoogleSheetsAdapter | None = None,
    ) -> dict[str, Any]:
        """Create a calendar event record.

        If this instance is in dry_run mode, return ok without real Calendar API call.
        Also writes to the 'calendar_events' tab in CRM if sheets_adapter is provided.
        """
        event_id = f"CAL-{uuid.uuid4().hex[:8]}"
        created_at = datetime.utcnow().isoformat()
        event_data = {
            "event_id": event_id,
            "created_at_utc": created_at,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "event_type": event_type,
            "event_date_utc": event_date_utc,
            "event_summary": event_summary,
            "status": "open",
            "notes": notes,
        }

        # Always record in CRM if adapter provided
        if sheets_adapter is not None:
            try:
                sheets_adapter.append_row(self.SHEETS_TAB, self._to_sheets_row(event_data))
            except Exception as exc:
                return {"ok": False, "error": f"Sheet write failed: {exc}", "event_id": event_id}

        if self.dry_run:
            return {"ok": True, "dry_run": True, "event_id": event_id}

        self._ensure_token()
        if not self.access_token:
            return {"ok": False, "error": "Missing Calendar auth token", "event_id": event_id}

        url = f"{self.API_BASE}/calendars/{self.calendar_id}/events/quickAdd"
        try:
            resp = httpx.post(
                url,
                params={"text": f"{event_summary} at {event_date_utc}"},
                headers=self._auth_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "event_id": event_id, "calendar_event_id": data.get("id", "")}
        except httpx.HTTPStatusError as exc:
            return {
                "ok": False,
                "error": f"Calendar API HTTP {exc.response.status_code}",
                "event_id": event_id,
            }
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return {
                "ok": False,
                "error": f"Calendar network error: {type(exc).__name__}",
                "event_id": event_id,
            }

    def list_open_events(
        self,
        *,
        sheets_adapter: GoogleSheetsAdapter | None = None,
    ) -> list[dict[str, Any]]:
        """Return open/overdue calendar events from the CRM tab."""
        if sheets_adapter is None:
            return []
        rr = sheets_adapter.read_last_rows(self.SHEETS_TAB, count=200)
        if not rr.get("ok"):
            return []
        rows = rr.get("rows", [])
        if not rows:
            return []
        header = rows[0] if rows else []
        results: list[dict[str, Any]] = []
        for row in rows[1:]:
            record: dict[str, Any] = {}
            for i, h in enumerate(header):
                record[h] = row[i] if i < len(row) else ""
            results.append(record)
        return results

    def schedule_follow_up(
        self,
        entity_type: str,
        entity_id: str,
        days: int = 7,
        *,
        sheets_adapter: GoogleSheetsAdapter | None = None,
    ) -> dict[str, Any]:
        follow_up = (datetime.utcnow() + timedelta(days=days)).isoformat()
        return self.add_event(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type="follow_up",
            event_date_utc=follow_up,
            event_summary=f"Follow-up: {entity_type} {entity_id}",
            notes=f"Auto-scheduled follow-up {days} days from now",
            sheets_adapter=sheets_adapter,
        )

    def schedule_deadline(
        self,
        entity_type: str,
        entity_id: str,
        deadline_utc: str,
        *,
        sheets_adapter: GoogleSheetsAdapter | None = None,
    ) -> dict[str, Any]:
        return self.add_event(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type="deadline",
            event_date_utc=deadline_utc,
            event_summary=f"Deadline: {entity_type} {entity_id}",
            notes="Auto-scheduled application deadline",
            sheets_adapter=sheets_adapter,
        )

    def remind_pending_approval(
        self,
        approval_id: str,
        days: int = 3,
        *,
        sheets_adapter: GoogleSheetsAdapter | None = None,
    ) -> dict[str, Any]:
        remind_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
        return self.add_event(
            entity_type="approval",
            entity_id=approval_id,
            event_type="approval_reminder",
            event_date_utc=remind_at,
            event_summary=f"Approval reminder: {approval_id}",
            notes=f"Remind operator to review approval {approval_id}",
            sheets_adapter=sheets_adapter,
        )

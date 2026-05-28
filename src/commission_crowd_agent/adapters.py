"""Adapters for external systems.

- SourceAdapter: reads/writes leads to Google Sheets.
- ScoringAdapter: calls Ollama.com Cloud for research, writing, and scoring.
- NotifierAdapter: sends Telegram Bot messages (httpx-based, with retries).
- OutreachAdapter: sends emails via Gmail / SMTP.

NotifierAdapter is now real; others remain stubs awaiting future milestones.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .domain import Lead


class SourceAdapter:
    """Stub: read and write leads to Google Sheets."""

    def __init__(self, spreadsheet_id: str = "") -> None:
        self.spreadsheet_id = spreadsheet_id

    def fetch_new_leads(self, client_name: str, limit: int = 30) -> list[Lead]:
        """Return placeholder leads."""
        return []

    def update_lead(self, lead: Lead) -> bool:
        """Write lead state back to Sheets."""
        return True


class ScoringAdapter:
    """Stub: call remote LLM for agent tasks."""

    def __init__(self, base_url: str = "", api_key: str = "", model: str = "") -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def research(self, lead: Lead) -> str:
        """Return structured research notes."""
        return ""

    def write_email(self, lead: Lead) -> tuple[str, str]:
        """Return (subject, body)."""
        return ("", "")

    def score(self, lead: Lead) -> int:
        """Return personalisation score 1–10."""
        return 0


class NotifierAdapter:
    """Telegram Bot notifier adapter with httpx, retries, and dry-run safety."""

    API_BASE = "https://api.telegram.org"
    TIMEOUT_SECONDS = 10
    MAX_RETRIES = 3
    BACKOFF_SECONDS = [1, 2]

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        *,
        dry_run: bool = False,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run = dry_run

    def _api_url(self, method: str) -> str:
        """Build a real Telegram Bot API URL.  Never log or print this value."""
        return f"{self.API_BASE}/bot{self.bot_token}/{method}"

    def _post_with_retry(
        self,
        method: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        """POST to Telegram API with exponential backoff on transient errors.

        Raises on persistent failure so callers can map to a structured result.
        """
        url = self._api_url(method)
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = httpx.post(url, json=payload, timeout=self.TIMEOUT_SECONDS)
                # Retry on 5xx or 429
                if response.status_code >= 500 or response.status_code == 429:
                    last_exc = httpx.HTTPStatusError(
                        "Retryable status",
                        request=response.request,
                        response=response,
                    )
                    if attempt < len(self.BACKOFF_SECONDS):
                        time.sleep(self.BACKOFF_SECONDS[attempt])
                    continue
                return response
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < len(self.BACKOFF_SECONDS):
                    time.sleep(self.BACKOFF_SECONDS[attempt])
                continue
        raise last_exc  # type: ignore[misc]

    def send_message(
        self,
        *,
        chat_id: str | None = None,
        text: str = "",
        parse_mode: str = "Markdown",
    ) -> dict[str, Any]:
        """Send a plain-text message via Telegram Bot API.

        Returns a structured result dict with no secret values:
        {
            "ok": bool,
            "status": int,            # HTTP status or 0 for dry-run
            "message_id": int | None,
            "error": str | None,
        }
        """
        target_chat = chat_id or self.chat_id

        if self.dry_run:
            return {
                "ok": True,
                "status": 0,
                "message_id": None,
                "error": None,
            }

        if not self.bot_token or not target_chat:
            return {
                "ok": False,
                "status": 0,
                "message_id": None,
                "error": "Missing bot_token or chat_id",
            }

        try:
            response = self._post_with_retry(
                "sendMessage",
                {
                    "chat_id": target_chat,
                    "text": text,
                    "parse_mode": parse_mode,
                },
            )
            response.raise_for_status()
            data = response.json()
            if data.get("ok"):
                return {
                    "ok": True,
                    "status": response.status_code,
                    "message_id": data.get("result", {}).get("message_id"),
                    "error": None,
                }
            return {
                "ok": False,
                "status": response.status_code,
                "message_id": None,
                "error": data.get("description", "Telegram API error"),
            }
        except httpx.HTTPStatusError as exc:
            return {
                "ok": False,
                "status": exc.response.status_code,
                "message_id": None,
                "error": f"HTTP error: {exc.response.status_code}",
            }
        except (httpx.NetworkError, httpx.TimeoutException) as exc:
            return {
                "ok": False,
                "status": 0,
                "message_id": None,
                "error": f"Network error: {type(exc).__name__}",
            }

    def send_summary(self, run_summary: dict[str, str | int]) -> dict[str, Any]:
        """Send a formatted pipeline summary."""
        lines = [f"*{key}*: {value}" for key, value in run_summary.items()]
        text = "\n".join(lines)
        return self.send_message(text=text)

    def token_present(self) -> bool:
        """Return whether a token is configured (safe for status checks)."""
        return bool(self.bot_token)


class OutreachAdapter:
    """Stub: dispatch personalised emails via Gmail / SMTP."""

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_pass: str = "",
        from_address: str = "",
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.from_address = from_address

    def send_email(self, lead: Lead) -> bool:
        """Send a personalised email to a lead."""
        return True


class GoogleSheetsAdapter:
    """Google Sheets adapter for reading/writing pipeline state.

    Uses the Google Sheets REST API via httpx. Supports service account
    credentials or an explicit access token for testing.
    """

    API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    TIMEOUT_SECONDS = 15

    _SCOPES: list[str] = ["https://www.googleapis.com/auth/spreadsheets"]

    # Minimal schema for auto-creation
    SCHEMA: dict[str, list[str]] = {
        "leads": [
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
        "opportunities": [
            "opportunity_id",
            "lead_id",
            "created_at_utc",
            "company_name",
            "opportunity_type",
            "offer_summary",
            "estimated_commission_min",
            "estimated_commission_max",
            "currency",
            "probability",
            "priority",
            "status",
            "next_action",
            "notes",
        ],
        "approvals": [
            "approval_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "requested_action",
            "risk_level",
            "status",
            "operator_decision",
            "decided_at_utc",
            "source_url",
            "notes",
            "entity_name",
            "approval_action",
        ],
        "runs": [
            "run_id",
            "created_at_utc",
            "workflow",
            "agent",
            "status",
            "input_ref",
            "output_ref",
            "duration_seconds",
            "error_summary",
            "notes",
        ],
        "outcomes": [
            "outcome_id",
            "created_at_utc",
            "opportunity_id",
            "lead_id",
            "outcome_type",
            "amount",
            "currency",
            "paid_status",
            "payment_ref",
            "notes",
        ],
    }

    def __init__(
        self,
        spreadsheet_id: str = "",
        access_token: str = "",
        *,
        credentials_path: str = "",
        service_account_json: str = "",
        dry_run: bool = False,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.access_token = access_token
        self.credentials_path = credentials_path
        self.service_account_json = service_account_json
        self.dry_run = dry_run

    def _auth_headers(self) -> dict[str, str]:
        """Return Authorization header with current access token."""
        return {"Authorization": f"Bearer {self.access_token}"}

    def _ensure_access_token(self) -> None:
        """Generate an access token from service-account credentials if needed.

        Only called internally; never logs secret values.
        """
        if self.access_token:
            return

        sa_info: dict[str, Any] | None = None
        if self.credentials_path:
            try:
                import json as _json

                with open(self.credentials_path) as fh:
                    sa_info = _json.load(fh)
            except Exception:
                return
        elif self.service_account_json:
            try:
                import json as _json

                sa_info = _json.loads(self.service_account_json)
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
            # silently fail; callers will check access_token and report error
            pass

    def health_check(self) -> dict[str, Any]:
        """Verify the spreadsheet is reachable.

        Returns a structured result dict with no secret values.
        """
        if not self.spreadsheet_id:
            return {
                "ok": False,
                "action": "health_check",
                "tab": "",
                "rows_changed": 0,
                "error": "Missing spreadsheet_id",
            }

        if self.dry_run:
            return {
                "ok": True,
                "action": "health_check",
                "tab": "",
                "rows_changed": 0,
                "error": None,
            }

        self._ensure_access_token()
        if not self.access_token:
            return {
                "ok": False,
                "action": "health_check",
                "tab": "",
                "rows_changed": 0,
                "error": "Missing access_token",
            }

        url = f"{self.API_BASE}/{self.spreadsheet_id}?fields=properties.title"
        try:
            response = httpx.get(url, headers=self._auth_headers(), timeout=self.TIMEOUT_SECONDS)
            response.raise_for_status()
            return {
                "ok": True,
                "action": "health_check",
                "tab": "",
                "rows_changed": 0,
                "error": None,
            }
        except httpx.HTTPStatusError as exc:
            return {
                "ok": False,
                "action": "health_check",
                "tab": "",
                "rows_changed": 0,
                "error": f"HTTP {exc.response.status_code}",
            }
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return {
                "ok": False,
                "action": "health_check",
                "tab": "",
                "rows_changed": 0,
                "error": f"Network: {type(exc).__name__}",
            }

    def read_rows(self, tab: str) -> dict[str, Any]:
        """Read all rows from a tab (including header).

        Returns structured result with rows as list[list[str]].
        """
        if not self.spreadsheet_id:
            return self._error_result("read_rows", tab, "Missing spreadsheet_id")

        if self.dry_run:
            return {
                "ok": True,
                "action": "read_rows",
                "tab": tab,
                "rows": [],
                "rows_changed": 0,
                "error": None,
            }

        self._ensure_access_token()
        if not self.access_token:
            return self._error_result("read_rows", tab, "Missing access_token")

        range_name = f"{tab}!A1:Z1000"
        url = f"{self.API_BASE}/{self.spreadsheet_id}/values/{range_name}?majorDimension=ROWS"
        try:
            response = httpx.get(url, headers=self._auth_headers(), timeout=self.TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            rows = data.get("values", [])
            return {
                "ok": True,
                "action": "read_rows",
                "tab": tab,
                "rows": rows,
                "rows_changed": len(rows),
                "error": None,
            }
        except httpx.HTTPStatusError as exc:
            return self._error_result("read_rows", tab, f"HTTP {exc.response.status_code}")
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return self._error_result("read_rows", tab, f"Network: {type(exc).__name__}")

    def read_last_rows(self, tab: str, count: int = 10) -> dict[str, Any]:
        """Read the last `count` rows from a tab, bounded and safe.

        Reads full tab up to 5000 rows, trims trailing empties, and returns
        the last `count` actual data rows. Never assumes position.
        """
        if not self.spreadsheet_id:
            return self._error_result("read_last_rows", tab, "Missing spreadsheet_id")

        self._ensure_access_token()
        if not self.access_token:
            return self._error_result("read_last_rows", tab, "Missing access_token")

        try:
            range_name = f"{tab}!A1:Z5000"
            url = f"{self.API_BASE}/{self.spreadsheet_id}/values/{range_name}?majorDimension=ROWS"
            response = httpx.get(url, headers=self._auth_headers(), timeout=self.TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            all_rows = data.get("values", [])
            # Trim trailing empty rows
            while all_rows and not any(cell for cell in all_rows[-1] if cell):
                all_rows.pop()
            # Filter to only non-empty rows (handles preallocated blanks in the middle)
            non_empty = [row for row in all_rows if any(cell for cell in row if cell)]
            start = max(0, len(non_empty) - count)
            rows = non_empty[start:]
            return {
                "ok": True,
                "action": "read_last_rows",
                "tab": tab,
                "rows": rows,
                "rows_changed": len(rows),
                "error": None,
            }
        except httpx.HTTPStatusError as exc:
            return self._error_result("read_last_rows", tab, f"HTTP {exc.response.status_code}")
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return self._error_result("read_last_rows", tab, f"Network: {type(exc).__name__}")

    def validate_tab_header(self, tab: str) -> dict[str, Any]:
        """Verify live Sheet header for a tab matches adapter SCHEMA.

        Returns structured result so callers can abort before writing.
        """
        if not self.spreadsheet_id:
            return {"ok": False, "error": "Missing spreadsheet_id", "live_header": []}
        result = self.read_rows(tab)
        if not result.get("ok"):
            return {"ok": False, "error": "Failed to read header", "live_header": []}
        rows = result.get("rows", [])
        if not rows:
            return {"ok": False, "error": f"Empty tab: {tab}", "live_header": []}
        live_header = rows[0]
        expected = self.SCHEMA.get(tab, [])
        if live_header != expected:
            # Allow live header to have extra columns beyond expected, but require
            # all expected columns in strict order at the start.
            if expected and live_header[:len(expected)] == expected:
                return {"ok": True, "error": None, "live_header": live_header}
            return {
                "ok": False,
                "error": (f"Header mismatch for '{tab}': live={live_header} expected={expected}"),
                "live_header": live_header,
            }
        return {"ok": True, "error": None, "live_header": live_header}

    def append_row(self, tab: str, values: list[str]) -> dict[str, Any]:
        """Append a single row to the bottom of a tab.

        Returns structured result with no secret values.
        """
        if not self.spreadsheet_id:
            return self._error_result("append_row", tab, "Missing spreadsheet_id")

        if self.dry_run:
            return {
                "ok": True,
                "action": "append_row",
                "tab": tab,
                "rows_changed": 1,
                "updated_range": "",
                "error": None,
            }

        self._ensure_access_token()
        if not self.access_token:
            return self._error_result("append_row", tab, "Missing access_token")

        url = (
            f"{self.API_BASE}/{self.spreadsheet_id}/values/"
            f"{tab}!A1:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
        )
        payload = {"values": [values]}
        try:
            response = httpx.post(
                url, json=payload, headers=self._auth_headers(), timeout=self.TIMEOUT_SECONDS
            )
            response.raise_for_status()
            data = response.json()
            updates = data.get("updates", {})
            updated_range = updates.get("updatedRange", "")
            return {
                "ok": True,
                "action": "append_row",
                "tab": tab,
                "rows_changed": updates.get("updatedRows", 1),
                "updated_range": updated_range,
                "error": None,
            }
        except httpx.HTTPStatusError as exc:
            return self._error_result("append_row", tab, f"HTTP {exc.response.status_code}")
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return self._error_result("append_row", tab, f"Network: {type(exc).__name__}")

    def upsert_row_by_key(
        self, tab: str, key_column: str, key_value: str, values: list[str]
    ) -> dict[str, Any]:
        """Find a row by key and replace it; append if not found.

        Simplified implementation for MVP.
        """
        if self.dry_run:
            return {
                "ok": True,
                "action": "upsert_row_by_key",
                "tab": tab,
                "rows_changed": 1,
                "error": None,
            }

        read_result = self.read_rows(tab)
        if not read_result["ok"]:
            return read_result

        rows = read_result.get("rows", [])
        if not rows:
            return self.append_row(tab, values)

        headers = rows[0]
        try:
            key_idx = headers.index(key_column)
        except ValueError:
            return self._error_result("upsert_row_by_key", tab, f"Column {key_column} not found")

        for row_idx, row in enumerate(rows[1:], start=2):
            if len(row) > key_idx and row[key_idx] == key_value:
                # Replace this row
                range_name = f"{tab}!A{row_idx}"
                url = (
                    f"{self.API_BASE}/{self.spreadsheet_id}/values/"
                    f"{range_name}?valueInputOption=USER_ENTERED"
                )
                payload = {"values": [values]}
                try:
                    response = httpx.put(
                        url,
                        json=payload,
                        headers=self._auth_headers(),
                        timeout=self.TIMEOUT_SECONDS,
                    )
                    response.raise_for_status()
                    return {
                        "ok": True,
                        "action": "upsert_row_by_key",
                        "tab": tab,
                        "rows_changed": 1,
                        "error": None,
                    }
                except httpx.HTTPStatusError as exc:
                    return self._error_result(
                        "upsert_row_by_key", tab, f"HTTP {exc.response.status_code}"
                    )
                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    return self._error_result(
                        "upsert_row_by_key", tab, f"Network: {type(exc).__name__}"
                    )

        # Not found — append
        return self.append_row(tab, values)

    def ensure_schema(self) -> dict[str, Any]:
        """Ensure all schema tabs exist with headers."""
        if not self.spreadsheet_id:
            return self._error_result("ensure_schema", "", "Missing spreadsheet_id")

        if self.dry_run:
            return {
                "ok": True,
                "action": "ensure_schema",
                "tab": "",
                "rows_changed": len(self.SCHEMA),
                "error": None,
            }

        # Note: Creating tabs requires Drive API scope or specific Sheets batchUpdate.
        # For MVP, we return a dry-run friendly result.
        return {
            "ok": True,
            "action": "ensure_schema",
            "tab": "",
            "rows_changed": 0,
            "error": "Schema creation requires manual setup or Drive API scope",
        }

    @staticmethod
    def _error_result(action: str, tab: str, error: str) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "tab": tab,
            "rows_changed": 0,
            "error": error,
        }

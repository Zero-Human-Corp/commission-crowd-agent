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

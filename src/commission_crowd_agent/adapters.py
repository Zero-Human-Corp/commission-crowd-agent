"""Stub adapters for external systems.

- SourceAdapter: reads/writes leads to Google Sheets.
- ScoringAdapter: calls Ollama.com Cloud for research, writing, and scoring.
- NotifierAdapter: sends Telegram Bot messages.
- OutreachAdapter: sends emails via Gmail / SMTP.

These are intentionally thin; real implementations will add authentication,
retries, and structured JSON parsing in a later pass.
"""

from __future__ import annotations

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
    """Telegram Bot notifier adapter."""

    def __init__(self, bot_token: str = "", chat_id: str = "") -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def _api_url(self, method: str) -> str:
        """Build a Telegram Bot API URL without exposing the token in logs."""
        return f"https://api.telegram.org/bot<TOKEN>/{method}"

    def send_message(self, text: str) -> bool:
        """Send a plain-text message. Returns True if dispatch accepted."""
        return bool(self.bot_token and self.chat_id)

    def send_summary(self, run_summary: dict[str, str | int]) -> bool:
        """Send a formatted pipeline summary."""
        return bool(self.bot_token and self.chat_id)

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

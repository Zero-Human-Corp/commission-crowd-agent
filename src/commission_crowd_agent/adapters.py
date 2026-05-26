"""Stub adapters for external systems.

- SourceAdapter: reads/writes leads to Google Sheets.
- ScoringAdapter: calls Ollama.com Cloud for research, writing, and scoring.

These are intentionally thin; the real implementations will add authentication,
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

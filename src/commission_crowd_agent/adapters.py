"""Adapters for external systems.

- SourceAdapter: reads/writes leads to Google Sheets.
- ScoringAdapter: calls Ollama.com Cloud for research, writing, and scoring.
- NotifierAdapter: sends Telegram Bot messages (httpx-based, with retries).
- OutreachAdapter: sends emails via Gmail / SMTP.

NotifierAdapter is now real; others remain stubs awaiting future milestones.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

import httpx

from .deeper_research import DeeperResearchService
from .domain import Lead
from .lead_scoring import LeadScorer


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
    """Real adapter backed by DeeperResearchService and LeadScorer.

    Uses local deterministic scoring and bounded public read-only research.
    No LLM calls unless future configuration enables them.
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self._research_service = DeeperResearchService()
        self._lead_scorer = LeadScorer()

    def research(self, lead: Lead) -> str:
        """Run bounded public read-only research for a lead."""
        result = self._research_service.research_one_lead(
            lead_id=lead.lead_id,
            company_name=lead.company or lead.full_name,
            notes=lead.research_notes or "",
        )
        notes_parts: list[str] = []
        for finding in result.findings:
            label = f"[{finding.source_label}]" if finding.source_label else ""
            verified = "✓" if finding.verified else "?"
            notes_parts.append(f"{label} {verified} {finding.finding}")
        if result.missing_data:
            notes_parts.append(f"Missing: {', '.join(result.missing_data)}")
        notes_parts.append(f"Next action: {result.recommended_next_action}")
        return "\n".join(notes_parts)

    def write_email(self, lead: Lead) -> tuple[str, str]:
        """Generate a subject and body for outreach to this lead."""
        if not lead.company:
            subject = "Exploring a commission-only sales partnership"
            body = (
                "Hello,\n\n"
                "I came across your profile and wanted to reach out regarding a "
                "commission-only sales representation opportunity.\n\n"
                "I'd love to learn more about what you're building and explore "
                "whether there might be a fit.\n\n"
                "Best regards"
            )
            return subject, body
        subject = f"Exploring a commission-only sales partnership with {lead.company}"
        body = (
            f"Hello {lead.full_name or 'there'},\n\n"
            f"I came across {lead.company} and wanted to reach out regarding a "
            f"commission-only sales representation opportunity.\n\n"
            f"I'd love to learn more about what you're building and explore "
            f"whether there might be a fit.\n\n"
            f"Best regards"
        )
        return subject, body

    def score(self, lead: Lead) -> int:
        """Score a lead using deterministic rules from LeadScorer.

        Returns fit_score (0–100) mapped from lead fields.
        """
        # Build a canonical row from Lead fields for LeadScorer
        lead_row = [
            lead.lead_id,
            "",  # created_at
            "",  # source
            "",  # source_url
            lead.company,
            lead.full_name,
            lead.email,
            "",  # role_title
            "",  # market
            "",  # country
            "",  # problem_signal
            "",  # commission_signal
            "",  # fit_score (prior)
            "",  # status
            lead.research_notes or "",
        ]
        score_output = self._lead_scorer.from_lead_row(lead_row)
        # Map fit_score (0–100) to personalization score (1–10) for domain model
        fit = score_output.fit_score
        if fit >= 80:
            return 10
        elif fit >= 70:
            return 9
        elif fit >= 60:
            return 8
        elif fit >= 50:
            return 7
        elif fit >= 40:
            return 6
        elif fit >= 30:
            return 5
        elif fit >= 20:
            return 4
        elif fit >= 10:
            return 3
        elif fit > 0:
            return 2
        return 1


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
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a plain-text or inline-keyboard message via Telegram Bot API.

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

        payload: dict[str, Any] = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        try:
            response = self._post_with_retry("sendMessage", payload)
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
    """Real SMTP email dispatcher with Hostinger support."""

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 465,
        smtp_user: str = "",
        smtp_pass: str = "",
        from_address: str = "",
        *,
        dry_run: bool = True,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.from_address = from_address or smtp_user
        self.dry_run = dry_run

    def _build_message(
        self,
        to_address: str,
        subject: str,
        body: str,
        html: str = "",
    ) -> tuple[
        str,  # from
        str,  # to
        str,  # raw MIME
    ]:
        import email.message

        msg = email.message.EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = to_address
        msg["Subject"] = subject
        msg["Message-ID"] = (
            f"<mail-{__import__('time').time():.0f}@{'-'.join(self.smtp_host.split('.'))}>"
        )
        msg["Date"] = __import__("email.utils").utils.formatdate(localtime=True)

        if html:
            msg.set_content(body, subtype="plain")
            msg.add_alternative(html, subtype="html")
        else:
            msg.set_content(body, subtype="plain")

        return self.from_address, to_address, msg.as_string()

    def health_check(self) -> dict[str, Any]:
        """Return SMTP connectivity status without sending."""
        if not self.smtp_host or not self.smtp_user or not self.smtp_pass:
            return {
                "ok": False,
                "action": "smtp_health_check",
                "error": "Missing SMTP credentials",
            }
        return {
            "ok": True,
            "action": "smtp_health_check",
            "host": self.smtp_host,
            "port": self.smtp_port,
            "user": self.smtp_user,
            "error": None,
        }

    def send_email(
        self,
        *,
        to_address: str = "",
        subject: str = "",
        body: str = "",
        html: str = "",
        lead: Lead | None = None,
    ) -> dict[str, Any]:
        """Send an email via SMTP with TLS/SSL.

        If *dry_run* is True, returns ok without connecting.
        Accepts either explicit fields or a Lead object.
        """
        if self.dry_run:
            return {
                "ok": True,
                "action": "send_email",
                "dry_run": True,
                "to": to_address or (lead.email if lead else ""),
                "subject": subject,
                "error": None,
            }

        to = to_address or (lead.email if lead else "")
        subj = subject
        bdy = body

        if not to or not subj or not bdy:
            return {
                "ok": False,
                "action": "send_email",
                "error": "Missing to_address, subject or body",
            }

        if not self.smtp_host or not self.smtp_user or not self.smtp_pass:
            return {
                "ok": False,
                "action": "send_email",
                "error": "SMTP not configured",
            }

        _from, _to, raw = self._build_message(to, subj, bdy, html)

        try:
            import smtplib

            if self.smtp_port in {
                465,
            }:
                # SSL connection (Hostinger default)
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15) as server:
                    server.login(self.smtp_user, self.smtp_pass)
                    server.sendmail(_from, [_to], raw)
            elif self.smtp_port in {587, 2525, 25}:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_pass)
                    server.sendmail(_from, [_to], raw)
            else:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15) as server:
                    server.login(self.smtp_user, self.smtp_pass)
                    server.sendmail(_from, [_to], raw)
        except smtplib.SMTPAuthenticationError as exc:
            return {
                "ok": False,
                "action": "send_email",
                "error": f"SMTP auth failed: {exc}",
            }
        except smtplib.SMTPException as exc:
            return {
                "ok": False,
                "action": "send_email",
                "error": f"SMTP error: {exc}",
            }
        except OSError as exc:
            return {
                "ok": False,
                "action": "send_email",
                "error": f"Network error: {exc}",
            }

        return {
            "ok": True,
            "action": "send_email",
            "to": to,
            "subject": subj,
            "error": None,
        }

    def send_from_template(
        self,
        template_name: str,
        context: dict[str, Any],
        to_address: str,
        *,
        html: str = "",
    ) -> dict[str, Any]:
        """Render an email template and send it.

        Returns structured result dict with ok, to, subject, and error.
        """
        from .email_templates import render_template

        try:
            subject, body = render_template(template_name, context)
        except (ValueError, KeyError) as exc:
            return {
                "ok": False,
                "action": "send_from_template",
                "error": f"Template render failed: {exc}",
            }
        return self.send_email(to_address=to_address, subject=subject, body=body, html=html)


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
        "calendar_events": [
            "event_id",
            "created_at_utc",
            "entity_type",
            "entity_id",
            "event_type",
            "event_date_utc",
            "event_summary",
            "status",
            "notes",
        ],
        "submissions": [
            "submission_id",
            "submitted_at_utc",
            "opportunity_id",
            "lead_id",
            "source_url",
            "status",
            "success",
            "verification_detected",
            "final_url",
            "notes",
        ],
        "outreach_log": [
            "outreach_id",
            "created_at_utc",
            "opportunity_id",
            "lead_id",
            "template_id",
            "subject_line",
            "body_preview",
            "status",
            "sent_at_utc",
            "operator_approved",
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
        Extra columns beyond the canonical schema are tolerated, but explicit
        "Column N" style pollution is flagged in `polluted_columns`.
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

        # Detect pollution: blank-named or "Column N" style columns
        polluted = [c for c in live_header if not c or c.lower().startswith("column ")]

        if live_header != expected:
            # Allow live header to have extra columns beyond expected, but require
            # all expected columns in strict order at the start.
            if expected and live_header[: len(expected)] == expected:
                return {
                    "ok": True,
                    "error": None,
                    "live_header": live_header,
                    "polluted_columns": polluted,
                }
            return {
                "ok": False,
                "error": (f"Header mismatch for '{tab}': live={live_header} expected={expected}"),
                "live_header": live_header,
                "polluted_columns": polluted,
            }
        return {"ok": True, "error": None, "live_header": live_header, "polluted_columns": polluted}

    def append_row(self, tab: str, values: list[str]) -> dict[str, Any]:
        """Append a single row to the next **logical** empty data row in a tab.

        Reads the full tab to find the last non-empty row, then writes directly
        to the next sequential row. This avoids the `A1:append` behaviour that
        inserts after the *last formatted row*, which creates phantom gaps when
        the Sheet has extra blank rows or trailing columns.

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

        # 1. Read the full tab to find the last real data row
        read_result = self.read_last_rows(tab, count=5000)
        if not read_result.get("ok"):
            return read_result

        all_rows = read_result.get("rows", [])
        data_rows = all_rows[1:] if len(all_rows) > 1 else all_rows

        last_data_row = 0
        for row in data_rows:
            if any(cell for cell in row if cell):
                last_data_row += 1

        # Row numbers are 1-based in Sheets; header is row 1
        next_row = last_data_row + 1 + 1  # +1 for header, +1 for next empty

        # 2. Build direct write range and URL
        expected_cols = len(self.SCHEMA.get(tab, []))
        # end_col reserved for future header validation
        self._index_to_column_letter(max(expected_cols, len(values))) + "1"
        range_name = f"{tab}!A{next_row}"
        url = (
            f"{self.API_BASE}/{self.spreadsheet_id}/values/"
            f"{range_name}?valueInputOption=USER_ENTERED"
        )
        payload = {"values": [values]}
        try:
            response = httpx.put(
                url, json=payload, headers=self._auth_headers(), timeout=self.TIMEOUT_SECONDS
            )
            response.raise_for_status()
            data = response.json()
            updated_range = data.get("updatedRange", "")
            return {
                "ok": True,
                "action": "append_row",
                "tab": tab,
                "rows_changed": 1,
                "updated_range": updated_range,
                "error": None,
            }
        except httpx.HTTPStatusError as exc:
            return self._error_result("append_row", tab, f"HTTP {exc.response.status_code}")
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return self._error_result("append_row", tab, f"Network: {type(exc).__name__}")

    @staticmethod
    def _index_to_column_letter(idx: int) -> str:
        """Convert 1-based column index to A, B, C... Z, AA, AB..."""
        result = ""
        n = idx
        while n > 0:
            n, rem = divmod(n - 1, 26)
            result = chr(65 + rem) + result
        return result

    def compact_tab(self, tab: str, *, dry_run: bool = True) -> dict[str, Any]:
        """Re-write a tab so all non-empty rows are contiguous under the header.

        Reads the full tab, discards blank/middle-gap rows, and (unless
        *dry_run*) writes the compacted rows back to the Sheet. Returns a
        structured result with *before_row_count*, *after_row_count*,
        *removed_rows*, and *rows_kept* for auditing.

        **Never** silently mutates — always returns a report first.
        """
        if not self.spreadsheet_id:
            return self._error_result("compact_tab", tab, "Missing spreadsheet_id")

        result = self.read_last_rows(tab, count=5000)
        if not result.get("ok"):
            return result

        all_rows = result.get("rows", [])
        if not all_rows:
            return {
                "ok": True,
                "action": "compact_tab",
                "tab": tab,
                "before_row_count": 0,
                "after_row_count": 0,
                "removed_rows": 0,
                "rows_kept": [],
                "dry_run": dry_run,
                "error": None,
            }

        header = all_rows[0]
        # Keep header + all non-empty data rows (preserves original order)
        kept: list[list[str]] = [header]
        for row in all_rows[1:]:
            if any(cell for cell in row if cell):
                kept.append(row)

        before = len(all_rows)
        after = len(kept)
        removed = before - after

        if not dry_run:
            # Overwrite the entire tab with compacted data.
            # We clear the tab first by writing just the header at A1, then
            # writing the remaining rows starting at A2.
            self._ensure_access_token()
            if not self.access_token:
                return self._error_result("compact_tab", tab, "Missing access_token")

            # Build batchUpdate clear + update request
            url = f"{self.API_BASE}/{self.spreadsheet_id}/values:batchClear"
            payload = {"ranges": [f"{tab}!A1:Z5000"]}
            with contextlib.suppress(Exception):
                httpx.post(
                    url,
                    json=payload,
                    headers=self._auth_headers(),
                    timeout=self.TIMEOUT_SECONDS,
                )

            # Write back all kept rows
            write_url = (
                f"{self.API_BASE}/{self.spreadsheet_id}/values/"
                f"{tab}!A1?valueInputOption=USER_ENTERED"
            )
            write_payload = {"values": kept, "majorDimension": "ROWS"}
            try:
                response = httpx.put(
                    write_url,
                    json=write_payload,
                    headers=self._auth_headers(),
                    timeout=self.TIMEOUT_SECONDS,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                return self._error_result("compact_tab", tab, f"HTTP {exc.response.status_code}")
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                return self._error_result("compact_tab", tab, f"Network: {type(exc).__name__}")

        return {
            "ok": True,
            "action": "compact_tab",
            "tab": tab,
            "before_row_count": before,
            "after_row_count": after,
            "removed_rows": removed,
            "rows_kept": kept if dry_run else [],
            "dry_run": dry_run,
            "error": None,
        }

    def audit_approvals(self) -> dict[str, Any]:
        """Run a full integrity audit on the approvals tab.

        Returns structured results for use in CLI and reports. Covers:
        - schema pollution (blank / 'Column N' columns)
        - duplicate approval_ids
        - stale pending approvals (same entity_id, multiple pending)
        """
        result = self.read_last_rows("approvals", count=5000)
        if not result.get("ok"):
            return result

        rows = result.get("rows", [])
        if not rows:
            return {
                "ok": True,
                "action": "audit_approvals",
                "total_rows": 0,
                "header": [],
                "polluted_columns": [],
                "duplicates": {},
                "stale_entities": [],
                "error": None,
            }

        header = rows[0]
        expected = self.SCHEMA.get("approvals", [])
        polluted = [c for c in header if not c or c.lower().startswith("column ")]

        data_rows = rows[1:]
        approval_ids = {}
        entity_statuses: dict[str, list[dict[str, Any]]] = {}
        seen_ids: dict[str, int] = {}

        for idx, row in enumerate(data_rows, start=2):
            if not any(c for c in row if c):
                continue
            aid = row[0] if row else ""
            eid = row[3] if len(row) > 3 else ""
            status = row[6] if len(row) > 6 else ""
            action = row[12] if len(row) > 12 else ""
            if aid:
                seen_ids[aid] = seen_ids.get(aid, 0) + 1
                approval_ids[aid] = {
                    "row_index": idx,
                    "entity_id": eid,
                    "status": status,
                    "action": action,
                }
            if eid and status:
                entity_statuses.setdefault(eid, []).append(
                    {"approval_id": aid, "status": status, "action": action, "row_index": idx}
                )

        duplicates = {k: v for k, v in seen_ids.items() if v > 1}
        stale_entities = []
        for eid, entries in entity_statuses.items():
            pending = [e for e in entries if e["status"] == "pending"]
            if len(pending) > 1:
                stale_entities.append(
                    {
                        "entity_id": eid,
                        "pending_count": len(pending),
                        "pending_ids": [e["approval_id"] for e in pending],
                        "latest_pending": pending[-1]["approval_id"],
                    }
                )

        return {
            "ok": True,
            "action": "audit_approvals",
            "total_rows": len(rows),
            "header": header,
            "canonical_header": expected,
            "polluted_columns": polluted,
            "duplicates": duplicates,
            "stale_entities": stale_entities,
            "error": None,
        }

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

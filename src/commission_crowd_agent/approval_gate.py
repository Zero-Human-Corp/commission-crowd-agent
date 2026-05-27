"""Approval gate service for human-in-the-loop control.

Provides:
- ApprovalRequest dataclass aligned with the Google Sheets approvals tab schema
- ApprovalGate service: create, read, check, notify

All write operations are gated by dry_run.  Real sends require explicit flags.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .adapters import GoogleSheetsAdapter, NotifierAdapter


@dataclass
class ApprovalRequest:
    """A human approval request aligned with the approvals tab schema.

    Schema mapping (adapter SCHEMA["approvals"]):
        approval_id, opportunity_id, draft_text, approval_status,
        approved_by, approved_at, telegram_message_id
    """

    approval_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    opportunity_id: str = ""
    draft_text: str = ""
    approval_status: str = "pending"
    approved_by: str = ""
    approved_at: str = ""
    telegram_message_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_sheets_row(self) -> list[str]:
        """Serialise to ordered list[str] aligned with adapter SCHEMA['approvals']."""
        return [
            self.approval_id,
            self.opportunity_id,
            self.draft_text,
            self.approval_status,
            self.approved_by,
            self.approved_at,
            self.telegram_message_id,
        ]


class ApprovalGate:
    """Service for creating and checking approval requests.

    All writes are gated by dry_run.  Notifications are sent only when a
    notifier is wired and the caller explicitly opts in.
    """

    def __init__(
        self,
        sheets_adapter: GoogleSheetsAdapter | None = None,
        notifier: NotifierAdapter | None = None,
    ) -> None:
        self.sheets_adapter = sheets_adapter
        self.notifier = notifier

    def create_approval(
        self,
        opportunity_id: str,
        draft_text: str,
        *,
        dry_run: bool = True,
    ) -> ApprovalRequest:
        """Create a pending approval request and optionally write to Sheets."""
        req = ApprovalRequest(
            opportunity_id=opportunity_id,
            draft_text=draft_text,
            approval_status="pending",
        )
        if self.sheets_adapter is not None and not dry_run:
            self.sheets_adapter.append_row("approvals", req.to_sheets_row())
        return req

    def read_approval_status(self, approval_id: str) -> str:
        """Read approval status from Sheets by approval_id.

        Returns 'missing' if the row is not found or Sheets is unavailable.
        """
        if self.sheets_adapter is None:
            return "missing"
        result = self.sheets_adapter.read_rows("approvals")
        if not result.get("ok"):
            return "missing"
        rows = result.get("rows", [])
        if not rows:
            return "missing"
        header = rows[0]
        try:
            idx = header.index("approval_id")
            status_idx = header.index("approval_status")
        except ValueError:
            return "missing"
        for row in rows[1:]:
            if len(row) > idx and row[idx] == approval_id:
                return row[status_idx] if len(row) > status_idx else "missing"
        return "missing"

    def is_approved(self, approval_id: str) -> bool:
        """Return True only if the approval status is explicitly 'approved'."""
        return self.read_approval_status(approval_id) == "approved"

    def notify_operator(
        self,
        req: ApprovalRequest,
        *,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Send Telegram approval notification if notifier is wired.

        Message text is safe — no secrets, tokens, or spreadsheet IDs.
        """
        if self.notifier is None:
            return {"ok": True, "status": 0, "sent": False}
        text = (
            f"⏳ *Approval Required*\n"
            f"Approval ID: `{req.approval_id}`\n"
            f"Opportunity: {req.opportunity_id}\n"
            f"Action: {req.draft_text[:100]}\n"
            f"Status: {req.approval_status}\n"
            f"\n"
            f"To approve, update the 'approvals' tab in the Sheet to 'approved'."
        )
        return self.notifier.send_message(text=text)

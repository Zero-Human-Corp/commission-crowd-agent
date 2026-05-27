"""Approval gate service for human-in-the-loop control.

Provides:
- ApprovalRequest dataclass aligned with the live Google Sheets approvals tab schema
- ApprovalGate service: create, read, check, notify

Canonical approvals schema (live Sheet):
    approval_id, created_at_utc, entity_type, entity_id,
    requested_action, risk_level, status,
    operator_decision, decided_at_utc, notes

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
    """A human approval request aligned with the live approvals tab schema.

    Canonical columns:
        approval_id, created_at_utc, entity_type, entity_id,
        requested_action, risk_level, status,
        operator_decision, decided_at_utc, notes
    """

    approval_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at_utc: str = ""
    entity_type: str = ""
    entity_id: str = ""
    requested_action: str = ""
    risk_level: str = ""
    status: str = "pending"
    operator_decision: str = ""
    decided_at_utc: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        """Set created_at_utc if not provided."""
        if not self.created_at_utc:
            self.created_at_utc = datetime.utcnow().isoformat()

    def to_sheets_row(self) -> list[str]:
        """Serialise to ordered list[str] aligned with adapter SCHEMA['approvals']."""
        return [
            self.approval_id,
            self.created_at_utc,
            self.entity_type,
            self.entity_id,
            self.requested_action,
            self.risk_level,
            self.status,
            self.operator_decision,
            self.decided_at_utc,
            self.notes,
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
        entity_type: str,
        entity_id: str,
        requested_action: str,
        *,
        risk_level: str = "low",
        notes: str = "",
        dry_run: bool = True,
    ) -> ApprovalRequest:
        """Create a pending approval request and optionally write to Sheets."""
        req = ApprovalRequest(
            entity_type=entity_type,
            entity_id=entity_id,
            requested_action=requested_action,
            risk_level=risk_level,
            notes=notes,
            status="pending",
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
            status_idx = header.index("status")
        except ValueError:
            return "missing"
        for row in rows[1:]:
            if len(row) > idx and row[idx] == approval_id:
                return row[status_idx] if len(row) > status_idx else "missing"
        return "missing"

    def read_approval_record(self, approval_id: str) -> dict[str, Any]:
        """Read a full approval record from Sheets by approval_id.

        Returns a dict with non-secret fields.  Returns empty dict on
        missing/unavailable data.
        """
        if self.sheets_adapter is None:
            return {}
        result = self.sheets_adapter.read_rows("approvals")
        if not result.get("ok"):
            return {}
        rows = result.get("rows", [])
        if not rows:
            return {}
        header = rows[0]
        try:
            idx = header.index("approval_id")
        except ValueError:
            return {}
        for row in rows[1:]:
            if len(row) > idx and row[idx] == approval_id:
                record: dict[str, Any] = {}
                for i, col in enumerate(header):
                    record[col] = row[i] if i < len(row) else ""
                return record
        return {}

    def is_approved(self, approval_id: str) -> bool:
        """Return True only if the approval status is explicitly 'approved'."""
        return self.read_approval_status(approval_id) == "approved"

    def validate_header(self) -> dict[str, Any]:
        """Check whether the live Sheet approvals header matches SCHEMA.

        Returns a structured result so callers can decide to abort.
        """
        if self.sheets_adapter is None:
            return {"ok": False, "error": "No sheets adapter", "live_header": []}
        return self.sheets_adapter.validate_tab_header("approvals")

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
            f"Entity: {req.entity_type} — {req.entity_id}\n"
            f"Action: {req.requested_action[:100]}\n"
            f"Risk: {req.risk_level}\n"
            f"Status: {req.status}\n"
            f"\n"
            f"To approve, update the 'approvals' tab status to 'approved'."
        )
        return self.notifier.send_message(text=text)

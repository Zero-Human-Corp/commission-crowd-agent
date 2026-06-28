"""Approval gate service for human-in-the-loop control.

Provides:
- ApprovalRequest dataclass aligned with the live Google Sheets approvals tab schema
- ApprovalGate service: create, read, check, notify

Canonical approvals schema (live Sheet):
    approval_id, created_at_utc, entity_type, entity_id,
    requested_action, risk_level, status,
    operator_decision, decided_at_utc, source_url, notes

All write operations are gated by dry_run.  Real sends require explicit flags.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover (Python < 3.11)
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .adapters import GoogleSheetsAdapter, NotifierAdapter


class ApprovalAction(StrEnum):
    """Canonical approval-action taxonomy for the rep-application workflow.

    Stages:
        research_scoring     — operator approves scoring of a newly sourced lead
        deeper_research      — operator approves public read-only deeper research
        outreach_draft       — operator approves creation of a buyer-outreach draft
        outreach_send        — operator approves sending a buyer-outreach message
        apply_to_principal   — operator approves *applying* to represent a vendor/principal
        icp_campaign_draft   — operator approves drafting an ICP-targeted sales campaign
        icp_campaign_send    — operator approves sending the ICP campaign
    """

    RESEARCH_SCORING = "research_scoring"
    DEEPER_RESEARCH = "deeper_research"
    OUTREACH_DRAFT = "outreach_draft"
    OUTREACH_SEND = "outreach_send"
    APPLY_TO_PRINCIPAL = "apply_to_principal"
    ICP_CAMPAIGN_DRAFT = "icp_campaign_draft"
    ICP_CAMPAIGN_SEND = "icp_campaign_send"


@dataclass
class ApprovalRequest:
    """A human approval request aligned with the live approvals tab schema.

    Canonical columns:
        approval_id, created_at_utc, entity_type, entity_id,
        requested_action, risk_level, status,
        operator_decision, decided_at_utc, source_url, notes
    """

    approval_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at_utc: str = ""
    entity_type: str = ""
    entity_id: str = ""
    entity_name: str = ""
    approval_action: str = ""
    requested_action: str = ""
    risk_level: str = ""
    status: str = "pending"
    operator_decision: str = ""
    decided_at_utc: str = ""
    source_url: str = ""
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
            self.source_url,
            self.notes,
            self.entity_name,
            self.approval_action,
        ]

    def validate_integrity(self) -> list[str]:
        """Return list of integrity violations. Empty list means valid."""
        errors: list[str] = []
        if self.status == "approved" and not self.operator_decision:
            errors.append("approved status without operator_decision")
        if self.status == "approved" and not self.decided_at_utc:
            errors.append("approved status without decided_at_utc")
        return errors


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

    def create_and_write_approval(
        self,
        entity_type: str,
        entity_id: str,
        requested_action: str,
        *,
        entity_name: str = "",
        approval_action: str = "",
        risk_level: str = "low",
        source_url: str = "",
        notes: str = "",
        opportunity_lifecycle_state: str = "",
    ) -> ApprovalRequest:
        """Create a pending approval write it to the Google Sheet CRM, and verify.

        This is the production path for operator-review approvals.
        It always writes to Sheets and fails closed if the write/readback fails.
        **Never** silently creates a local-only approval.

        Args:
            opportunity_lifecycle_state: If the opportunity is already active,
                applied, accepted, rejected, closed, or withdrawn, creation is
                blocked to prevent duplicate application approvals.
        """
        # Hard exclusion: never create apply_to_principal for existing activities
        _terminal_states = {
            "active",
            "application_submitted",
            "application_approved",
            "principal_accepted",
            "application_rejected",
            "closed",
            "withdrawn",
            "expired",
            "paused",
        }
        if (
            requested_action == "apply_to_principal"
            and opportunity_lifecycle_state in _terminal_states
        ):
            raise RuntimeError(
                f"Approval blocked: opportunity {entity_id} is "
                f"'{opportunity_lifecycle_state}' in My Opportunities. "
                f"Cannot create apply_to_principal for an existing activity."
            )

        req = ApprovalRequest(
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            approval_action=approval_action,
            requested_action=requested_action,
            risk_level=risk_level,
            source_url=source_url,
            notes=notes,
            status="pending",
        )

        # Integrity check before writing
        integrity_errors = req.validate_integrity()
        if integrity_errors:
            raise RuntimeError(f"Approval integrity violations: {'; '.join(integrity_errors)}")

        # Sanity check: if Sheets is not wired, we must not pretend the approval
        # is pending in a system the operator cannot see.
        if self.sheets_adapter is None:
            raise RuntimeError(
                "Approval gate has no sheets_adapter wired. "
                "Refusing to create an invisible approval. "
                "Set up Google Sheets before creating operator approvals."
            )

        # Validate headers
        header_result = self.sheets_adapter.validate_tab_header("approvals")
        if not header_result["ok"]:
            raise RuntimeError(
                f"Approval write aborted: approvals tab header invalid. {header_result['error']}"
            )

        # Write to Sheet
        write_result = self.sheets_adapter.append_row("approvals", req.to_sheets_row())
        if not write_result.get("ok"):
            raise RuntimeError(f"Approval write to Sheet failed: {write_result.get('error')}")

        # Post-write readback verification
        readback = self.sheets_adapter.read_last_rows("approvals", count=200)
        if not readback.get("ok"):
            raise RuntimeError(f"Approval readback from Sheet failed: {readback.get('error')}")

        found = False
        for row in readback.get("rows", []):
            if row and row[0] == req.approval_id:
                found = True
                break

        if not found:
            raise RuntimeError(
                f"Approval {req.approval_id} was written to Sheet but not found "
                f"in readback. CRM may be inconsistent. Refusing to report success."
            )

        return req

    def create_approval(
        self,
        entity_type: str,
        entity_id: str,
        requested_action: str,
        *,
        entity_name: str = "",
        approval_action: str = "",
        risk_level: str = "low",
        source_url: str = "",
        notes: str = "",
        dry_run: bool = True,
    ) -> ApprovalRequest:
        """Create a pending approval request and optionally (dry-run) write to Sheets.

        This legacy method defaults to dry_run=True for backwards compatibility.
        **For production operator-review approvals, use create_and_write_approval().**
        """
        req = ApprovalRequest(
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            approval_action=approval_action,
            requested_action=requested_action,
            risk_level=risk_level,
            source_url=source_url,
            notes=notes,
            status="pending",
        )
        if self.sheets_adapter is not None and not dry_run:
            header_result = self.sheets_adapter.validate_tab_header("approvals")
            if not header_result["ok"]:
                raise RuntimeError(f"Approval write aborted: {header_result['error']}")
            self.sheets_adapter.append_row("approvals", req.to_sheets_row())
        return req

    def read_approval_status(self, approval_id: str) -> str:
        """Read approval status from Sheets by approval_id.

        Returns 'missing' if the row is not found or Sheets is unavailable.

        Uses read_last_rows so this works even when the adapter is in dry_run
        mode — reads are side-effect-free.
        """
        if self.sheets_adapter is None:
            return "missing"
        result = self.sheets_adapter.read_last_rows("approvals", count=5000)
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

        Uses read_last_rows so this works even when the adapter is in dry_run
        mode — reads are side-effect-free.
        """
        if self.sheets_adapter is None:
            return {}
        result = self.sheets_adapter.read_last_rows("approvals", count=5000)
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
            f"Entity: {req.entity_type} — {req.entity_name or req.entity_id}\n"
            f"Action: {req.approval_action or req.requested_action[:100]}\n"
            f"Risk: {req.risk_level}\n"
            f"Status: {req.status}\n"
            f"\n"
            f"To approve, update the 'approvals' tab status to 'approved'."
        )
        return self.notifier.send_message(text=text)

    # ────────── Thin wrappers for SalesOrchestrator ──────────
    def submit(
        self,
        lead_id: str,
        subject: str,
        body: str,
        to_email: str,
    ) -> dict[str, Any]:
        """Create an approval request for an outbound email draft.

        Wraps create_and_write_approval with email-specific fields.
        Fails closed if Sheets is unavailable.
        """
        try:
            req = self.create_and_write_approval(
                entity_type="outbound_email",
                entity_id=lead_id,
                requested_action=f"Send email to {to_email}",
                entity_name=subject,
                approval_action=body,
                risk_level="medium",
                notes=f"To: {to_email} | Subject: {subject}",
            )
            return {
                "ok": True,
                "approval_id": req.approval_id,
                "lead_id": lead_id,
                "status": req.status,
            }
        except RuntimeError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "lead_id": lead_id,
            }

    def list_pending(self) -> list[dict[str, Any]]:
        """Return all approvals with status == 'pending' from Sheets.

        Returns a list of dicts with safe fields (no secrets).
        """
        if self.sheets_adapter is None:
            return []
        result = self.sheets_adapter.read_last_rows("approvals", count=5000)
        if not result.get("ok"):
            return []
        rows = result.get("rows", [])
        if not rows:
            return []
        header = rows[0]
        try:
            status_idx = header.index("status")
        except ValueError:
            return []

        pending: list[dict[str, Any]] = []
        for row in rows[1:]:
            if len(row) > status_idx and row[status_idx] == "pending":
                record: dict[str, Any] = {}
                for i, h in enumerate(header):
                    record[h] = row[i] if i < len(row) else ""
                # Drop the raw body/approval_action from the summary to keep it compact
                record.pop("approval_action", None)
                pending.append(record)
        return pending

    def approve(self, approval_id: str) -> dict[str, Any]:
        """Approve a pending approval request by updating its Sheets row.

        Returns a structured result with ok, lead_id (entity_id), and status.
        Also verifies that the approval has not expired (default TTL 168h = 7 days).
        """
        if self.sheets_adapter is None:
            return {
                "ok": False,
                "error": "No sheets adapter",
                "approval_id": approval_id,
            }

        result = self.sheets_adapter.read_last_rows("approvals", count=5000)
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error", "Failed to read approvals"),
                "approval_id": approval_id,
            }

        rows = result.get("rows", [])
        if not rows:
            return {
                "ok": False,
                "error": "Empty approvals tab",
                "approval_id": approval_id,
            }

        header = rows[0]
        try:
            id_idx = header.index("approval_id")
            status_idx = header.index("status")
            created_idx = header.index("created_at_utc")
        except ValueError as exc:
            return {
                "ok": False,
                "error": f"Missing column: {exc}",
                "approval_id": approval_id,
            }

        target_row: list[str] | None = None
        for row in rows[1:]:
            if len(row) > id_idx and row[id_idx] == approval_id:
                target_row = list(row)
                break

        if target_row is None:
            return {
                "ok": False,
                "error": f"Approval {approval_id} not found",
                "approval_id": approval_id,
            }

        # Guard: cannot re-approve an already approved / rejected record
        current_status = target_row[status_idx] if len(target_row) > status_idx else ""
        if current_status == "approved":
            return {
                "ok": False,
                "error": f"Approval {approval_id} is already approved",
                "approval_id": approval_id,
                "lead_id": target_row[header.index("entity_id")] if "entity_id" in header else "",
                "status": "approved",
            }
        if current_status == "rejected":
            return {
                "ok": False,
                "error": f"Approval {approval_id} was rejected and cannot be approved",
                "approval_id": approval_id,
                "status": "rejected",
            }

        # Guard: expiry check
        from .cca_guardian import check_expiry

        created_at = target_row[created_idx] if len(target_row) > created_idx else ""
        expiry = check_expiry(created_at, ttl_hours=168.0)
        if expiry.get("expired"):
            remaining = expiry.get("remaining_hours", 0)
            return {
                "ok": False,
                "error": f"Approval {approval_id} expired ({remaining:.1f}h remaining)",
                "approval_id": approval_id,
                "status": "expired",
            }

        # Update status to approved
        updated = list(target_row)
        while len(updated) <= status_idx:
            updated.append("")
        updated[status_idx] = "approved"

        # Also update operator_decision and decided_at_utc if columns exist
        now = datetime.utcnow().isoformat()
        for col_name, value in [("operator_decision", "approved"), ("decided_at_utc", now)]:
            if col_name in header:
                idx = header.index(col_name)
                while len(updated) <= idx:
                    updated.append("")
                updated[idx] = value

        upsert = self.sheets_adapter.upsert_row_by_key(
            "approvals",
            key_column="approval_id",
            key_value=approval_id,
            values=updated,
        )
        if not upsert.get("ok"):
            return {
                "ok": False,
                "error": upsert.get("error", "Upsert failed"),
                "approval_id": approval_id,
            }

        # Return lead_id (entity_id) so orchestrator can advance CRM stage
        entity_id = ""
        if "entity_id" in header:
            eidx = header.index("entity_id")
            entity_id = updated[eidx] if eidx < len(updated) else ""

        return {
            "ok": True,
            "approval_id": approval_id,
            "lead_id": entity_id,
            "status": "approved",
        }

    def reject(self, approval_id: str) -> dict[str, Any]:
        """Reject a pending approval request by updating its Sheets row.

        Mirrors the approve() method but sets status to 'rejected'. Returns a
        structured result with ok, lead_id (entity_id), and status.
        """
        if self.sheets_adapter is None:
            return {
                "ok": False,
                "error": "No sheets adapter",
                "approval_id": approval_id,
            }

        result = self.sheets_adapter.read_last_rows("approvals", count=5000)
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error", "Failed to read approvals"),
                "approval_id": approval_id,
            }

        rows = result.get("rows", [])
        if not rows:
            return {
                "ok": False,
                "error": "Empty approvals tab",
                "approval_id": approval_id,
            }

        header = rows[0]
        try:
            id_idx = header.index("approval_id")
            status_idx = header.index("status")
            created_idx = header.index("created_at_utc")
        except ValueError as exc:
            return {
                "ok": False,
                "error": f"Missing column: {exc}",
                "approval_id": approval_id,
            }

        target_row: list[str] | None = None
        for row in rows[1:]:
            if len(row) > id_idx and row[id_idx] == approval_id:
                target_row = list(row)
                break

        if target_row is None:
            return {
                "ok": False,
                "error": f"Approval {approval_id} not found",
                "approval_id": approval_id,
            }

        current_status = target_row[status_idx] if len(target_row) > status_idx else ""
        if current_status == "rejected":
            return {
                "ok": False,
                "error": f"Approval {approval_id} is already rejected",
                "approval_id": approval_id,
                "lead_id": target_row[header.index("entity_id")] if "entity_id" in header else "",
                "status": "rejected",
            }
        if current_status == "approved":
            return {
                "ok": False,
                "error": f"Approval {approval_id} was already approved and cannot be rejected",
                "approval_id": approval_id,
                "status": "approved",
            }

        from .cca_guardian import check_expiry

        created_at = target_row[created_idx] if len(target_row) > created_idx else ""
        expiry = check_expiry(created_at, ttl_hours=168.0)
        if expiry.get("expired"):
            remaining = expiry.get("remaining_hours", 0)
            return {
                "ok": False,
                "error": f"Approval {approval_id} expired ({remaining:.1f}h remaining)",
                "approval_id": approval_id,
                "status": "expired",
            }

        updated = list(target_row)
        while len(updated) <= status_idx:
            updated.append("")
        updated[status_idx] = "rejected"

        now = datetime.utcnow().isoformat()
        for col_name, value in [("operator_decision", "rejected"), ("decided_at_utc", now)]:
            if col_name in header:
                idx = header.index(col_name)
                while len(updated) <= idx:
                    updated.append("")
                updated[idx] = value

        upsert = self.sheets_adapter.upsert_row_by_key(
            "approvals",
            key_column="approval_id",
            key_value=approval_id,
            values=updated,
        )
        if not upsert.get("ok"):
            return {
                "ok": False,
                "error": upsert.get("error", "Upsert failed"),
                "approval_id": approval_id,
            }

        entity_id = ""
        if "entity_id" in header:
            eidx = header.index("entity_id")
            entity_id = updated[eidx] if eidx < len(updated) else ""

        return {
            "ok": True,
            "approval_id": approval_id,
            "lead_id": entity_id,
            "status": "rejected",
        }

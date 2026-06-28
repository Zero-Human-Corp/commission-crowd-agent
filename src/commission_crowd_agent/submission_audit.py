"""Submission audit module — immutable log of form-submission attempts.

Provides an append-only newline-delimited JSON ledger at
``/home/ubuntu/hermes-control/runtime/cca_submission_audit.jsonl``.
Every submission attempt, success, failure, abort, and dry-run is recorded
to support idempotency, daily volume limits, compliance, and dispute resolution.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_AUDIT_PATH = Path("/home/ubuntu/hermes-control/runtime/cca_submission_audit.jsonl")


@dataclass
class SubmissionAuditRecord:
    """Single immutable entry in the submission audit log.

    Fields:
        audit_id: UUIDv4 primary key for the audit entry.
        timestamp: ISO-8601 UTC timestamp of the event.
        opportunity_id: Target opportunity identifier.
        approval_id: Linked human-approval identifier from approval_gate.py.
        action: Canonical action name (e.g. ``apply_to_principal``).
        status: ``attempted``, ``success``, ``failed``, ``aborted``, or ``dry_run``.
        payload_hash: SHA-256 of the submitted/canonical payload.
        supervisor_checkpoint: Structured supervisor relay result.
        shadow_validation: Structured form shadow validator result.
        error: Error message on failure or abort.
        operator_notified: Whether a Telegram confirmation was dispatched.
        dry_run: True if this was a simulated submission.
    """

    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    opportunity_id: str = ""
    approval_id: str = ""
    action: str = "apply_to_principal"
    status: str = "attempted"
    payload_hash: str = ""
    supervisor_checkpoint: dict[str, Any] = field(default_factory=dict)
    shadow_validation: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    operator_notified: bool = False
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for JSONL storage."""
        return asdict(self)

    def to_jsonl(self) -> str:
        """Return a compact JSON line with deterministic key ordering."""
        return json.dumps(self.to_dict(), sort_keys=True, default=str)


class SubmissionAuditModule:
    """Append-only JSONL audit store for submission events."""

    def __init__(self, audit_path: Path | str | None = None) -> None:
        self.audit_path = Path(audit_path or DEFAULT_AUDIT_PATH)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: SubmissionAuditRecord) -> SubmissionAuditRecord:
        """Append a single record to the audit log.

        The write is atomic at the line level: each record occupies exactly
        one newline-terminated JSON line. The file is created if missing.
        """
        line = record.to_jsonl()
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return record

    def _read_records(self) -> list[SubmissionAuditRecord]:
        """Read all records from disk."""
        records: list[SubmissionAuditRecord] = []
        if not self.audit_path.exists():
            return records
        with self.audit_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(SubmissionAuditRecord(**json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    # Corrupted or partial lines are skipped rather than
                    # crashing the audit reader.
                    continue
        return records

    def has_submission(
        self,
        opportunity_id: str,
        action: str,
        payload_hash: str,
        *,
        window_days: int = 7,
    ) -> SubmissionAuditRecord | None:
        """Return the most recent matching audit record within the window.

        A matching record has the same opportunity_id, action, and payload_hash
        and a status in ``success`` or ``dry_run``. Returns ``None`` if no match.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        matches: list[SubmissionAuditRecord] = []
        for record in self._read_records():
            if record.opportunity_id != opportunity_id:
                continue
            if record.action != action:
                continue
            if record.payload_hash != payload_hash:
                continue
            if record.status not in {"success", "dry_run"}:
                continue
            try:
                ts = datetime.fromisoformat(record.timestamp)
            except ValueError:
                continue
            if ts < cutoff:
                continue
            matches.append(record)
        if not matches:
            return None
        matches.sort(key=lambda r: r.timestamp, reverse=True)
        return matches[0]

    def count_today(self, action: str) -> int:
        """Count submission records for the action on the current UTC day.

        Only statuses ``success`` and ``attempted`` are counted toward the
        daily volume limit.
        """
        today = datetime.now(timezone.utc).date()
        count = 0
        for record in self._read_records():
            if record.action != action:
                continue
            if record.status not in {"success", "attempted"}:
                continue
            try:
                ts = datetime.fromisoformat(record.timestamp)
            except ValueError:
                continue
            if ts.date() != today:
                continue
            count += 1
        return count

    def list_recent(self, limit: int = 100, action: str | None = None) -> list[SubmissionAuditRecord]:
        """Return the most recent audit records, newest first.

        Args:
            limit: Maximum number of records to return.
            action: Optional filter for a specific action.
        """
        records = self._read_records()
        if action:
            records = [r for r in records if r.action == action]
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records[:limit]


def hash_payload(payload: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hash for a payload dict."""
    normalised = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

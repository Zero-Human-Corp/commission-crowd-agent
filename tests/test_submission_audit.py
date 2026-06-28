"""Tests for the Sprint 3 submission audit module.

Covers:
- SubmissionAuditRecord serialisation
- Append-only JSONL storage
- Idempotency lookup within window
- Daily volume counting
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from commission_crowd_agent.submission_audit import (
    SubmissionAuditModule,
    SubmissionAuditRecord,
    hash_payload,
)


@pytest.fixture
def audit_module() -> Iterator[SubmissionAuditModule]:
    with tempfile.TemporaryDirectory() as tmp:
        yield SubmissionAuditModule(audit_path=Path(tmp) / "audit.jsonl")


class TestHashPayload:
    def test_hash_is_stable(self) -> None:
        payload = {"opportunity_id": "opp-1", "action": "apply_to_principal"}
        assert hash_payload(payload) == hash_payload(payload)

    def test_hash_changes_with_payload(self) -> None:
        a = hash_payload({"opportunity_id": "opp-1"})
        b = hash_payload({"opportunity_id": "opp-2"})
        assert a != b


class TestSubmissionAuditModule:
    def test_append_creates_file(self, audit_module: SubmissionAuditModule) -> None:
        record = SubmissionAuditRecord(
            opportunity_id="opp-1", approval_id="A001", status="dry_run"
        )
        audit_module.append(record)
        assert audit_module.audit_path.exists()
        lines = audit_module.audit_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = __import__("json").loads(lines[0])
        assert data["opportunity_id"] == "opp-1"

    def test_has_submission_finds_recent_match(self, audit_module: SubmissionAuditModule) -> None:
        payload_hash = hash_payload({"opportunity_id": "opp-1"})
        record = SubmissionAuditRecord(
            opportunity_id="opp-1",
            approval_id="A001",
            action="apply_to_principal",
            status="dry_run",
            payload_hash=payload_hash,
        )
        audit_module.append(record)
        found = audit_module.has_submission("opp-1", "apply_to_principal", payload_hash)
        assert found is not None
        assert found.approval_id == "A001"

    def test_has_submission_ignores_old_records(self, audit_module: SubmissionAuditModule) -> None:
        payload_hash = hash_payload({"opportunity_id": "opp-1"})
        old = SubmissionAuditRecord(
            opportunity_id="opp-1",
            approval_id="A001",
            action="apply_to_principal",
            status="dry_run",
            payload_hash=payload_hash,
            timestamp=(datetime.now(timezone.utc) - __import__("datetime").timedelta(days=8)).isoformat(),
        )
        audit_module.append(old)
        found = audit_module.has_submission("opp-1", "apply_to_principal", payload_hash)
        assert found is None

    def test_count_today(self, audit_module: SubmissionAuditModule) -> None:
        audit_module.append(
            SubmissionAuditRecord(
                opportunity_id="opp-1",
                action="apply_to_principal",
                status="success",
            )
        )
        audit_module.append(
            SubmissionAuditRecord(
                opportunity_id="opp-2",
                action="apply_to_principal",
                status="attempted",
            )
        )
        audit_module.append(
            SubmissionAuditRecord(
                opportunity_id="opp-3",
                action="other_action",
                status="success",
            )
        )
        assert audit_module.count_today("apply_to_principal") == 2
        assert audit_module.count_today("other_action") == 1

"""Identity verification gate — gates production CRM writes / form submissions.

Covers T-044 (code-doable part): the path to a production CRM write or form
submission must REJECT any candidate whose verification status is not
IDENTITY_VERIFIED + RECONCILED. Block (never default-allow) when verification
has not been run, when ``verify_candidate_identity`` returns MISMATCH / EMPTY /
UNREACHABLE, or when ``flag_identity_conflict`` returns QUARANTINED / STALE.

The real ``commission_crowd_agent.candidate_identity`` functions are exercised
against constructed inputs (fake Playwright pages, constructed historical /
current records). No internal modules are mocked. Test doubles are limited to
external service boundaries (browser page, Sheets adapter, supervisor relay,
approval gate).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from commission_crowd_agent.candidate_identity import (
    IdentityVerificationResult,
    flag_identity_conflict,
    verify_candidate_identity,
)
from commission_crowd_agent.config import CcaSettings
from commission_crowd_agent.crm_pipeline import CRMPipeline
from commission_crowd_agent.domain import OpportunityStage
from commission_crowd_agent.form_submission_engine import FormSubmissionEngine
from commission_crowd_agent.state_registry import (
    IDENTITY_RECONCILED_DISPOSITION,
    IDENTITY_VERIFIED_STATUS,
    LIFECYCLE_APPLICATION_APPROVED,
    OpportunityStateRecord,
    OpportunityStateRegistry,
    evaluate_identity_gate,
)
from commission_crowd_agent.submission_audit import (
    SubmissionAuditModule,
    SubmissionAuditRecord,
)
from commission_crowd_agent.supervisor_relay import SupervisorResponse


# ---------------------------------------------------------------------------
# Fakes for external service boundaries (browser page, approval gate,
# supervisor relay). The internal candidate_identity module is never mocked.
# ---------------------------------------------------------------------------


class IdentityFakePage:
    """Minimal Playwright page double for ``verify_candidate_identity``.

    ``evaluate`` handles the hash-navigation script (returns None) and the
    body-innerText script (returns the configured body text). When
    ``nav_raises`` is set the navigation script raises, simulating an
    unreachable page.
    """

    def __init__(self, body_text: str = "", *, nav_raises: bool = False) -> None:
        self._body = body_text
        self._nav_raises = nav_raises

    def evaluate(self, script: str) -> Any:
        if "window.location.hash" in script:
            if self._nav_raises:
                raise RuntimeError("navigation failed")
            return None
        if "document.body.innerText" in script:
            return self._body
        return None

    def wait_for_timeout(self, _ms: int) -> None:
        return None


class FakeApprovalGate:
    def __init__(self, approved_ids: set[str] | None = None) -> None:
        self._approved = approved_ids or set()

    def is_approved(self, approval_id: str) -> bool:
        return approval_id in self._approved


class FakeSupervisorRelay:
    def __init__(self, response: SupervisorResponse | None = None) -> None:
        self._response = response or SupervisorResponse(
            approved=True,
            reason="fake approve",
            recommended_action="proceed",
            risk_level="low",
            human_approval_required=False,
        )

    @property
    def enabled(self) -> bool:
        return True

    def route(self, _task_type: Any, _prompt: str, system: str | None = None) -> SupervisorResponse:
        return self._response


class FakeBrowser:
    """Browser adapter double with no live page (dry-run structural mode)."""

    @property
    def _page(self) -> None:
        return None


def _make_settings(**overrides: Any) -> CcaSettings:
    defaults: dict[str, Any] = {
        "supervisor_mode": "local",
        "supervisor_base_url": "http://localhost:9999/v1",
        "supervisor_api_key": "",
        "supervisor_primary_model": "glm-5.1",
        "supervisor_code_review_model": "qwen3-coder-next",
        "supervisor_reasoning_fallback_model": "deepseek-v3.2",
        "supervisor_draft_review_model": "kimi-k2-thinking",
        "supervisor_long_context_model": "nemotron-3-super:cloud",
        "supervisor_emergency_fallback_model": "kimi-k2.6:cloud",
        "supervisor_allow_fallback": False,
        "supervisor_fallback_model": "",
        "supervisor_telegram_notify": False,
        "smtp_port": 587,
        "cca_daily_volume_limit": 50,
    }
    defaults.update(overrides)
    return CcaSettings(**defaults)


def _approved_supervisor_response() -> SupervisorResponse:
    return SupervisorResponse(
        approved=True,
        reason="fake approve",
        recommended_action="proceed",
        risk_level="low",
        human_approval_required=False,
    )


# ---------------------------------------------------------------------------
# Constructed page bodies + records for the real candidate_identity functions.
# ---------------------------------------------------------------------------


_BODY_COMMISSION_SIGNAL = (
    "Cybersecurity SaaS - Acme Corp is a leading provider of security software. "
    "Earn 25% commission on first-year revenue. We are looking for independent "
    "sales representatives. Territory: UK & Ireland. Residual income available. "
    "Deal opportunities for sales agents. " + ("padding content. " * 20)
)


def _verified_result() -> IdentityVerificationResult:
    """Real IDENTITY_VERIFIED result from verify_candidate_identity."""
    page = IdentityFakePage(body_text=_BODY_COMMISSION_SIGNAL)
    return verify_candidate_identity(
        page,
        target_id="OPP-1",
        expected_title_fragments=["Cybersecurity SaaS"],
        expected_vendor_fragments=["Acme Corp"],
        settle_ms=0,
    )


def _mismatch_result() -> IdentityVerificationResult:
    """Real IDENTITY_MISMATCH result from verify_candidate_identity."""
    page = IdentityFakePage(body_text=_BODY_COMMISSION_SIGNAL)
    return verify_candidate_identity(
        page,
        target_id="OPP-1",
        expected_title_fragments=["Nonexistent Title XYZ"],
        expected_vendor_fragments=["Nonexistent Vendor ABC"],
        settle_ms=0,
    )


def _empty_result() -> IdentityVerificationResult:
    """Real PAGE_EMPTY result from verify_candidate_identity (body too short)."""
    page = IdentityFakePage(body_text="short generic shell")
    return verify_candidate_identity(
        page,
        target_id="OPP-1",
        expected_title_fragments=["Cybersecurity SaaS"],
        settle_ms=0,
    )


def _unreachable_result() -> IdentityVerificationResult:
    """Real PAGE_UNREACHABLE result from verify_candidate_identity (nav error)."""
    page = IdentityFakePage(body_text="", nav_raises=True)
    return verify_candidate_identity(
        page,
        target_id="OPP-1",
        expected_title_fragments=["Cybersecurity SaaS"],
        settle_ms=0,
    )


def _reconciled_disposition() -> str:
    """Real RECONCILED disposition from flag_identity_conflict (matching records)."""
    historical = {"opportunity_id": "OPP-1", "title": "Cybersecurity SaaS",
                  "vendor_or_principal_name": "Acme Corp"}
    current = {"opportunity_id": "OPP-1", "title": "Cybersecurity SaaS",
               "vendor_or_principal_name": "Acme Corp"}
    return flag_identity_conflict(historical, current)["disposition"]


def _quarantined_disposition() -> str:
    """Real QUARANTINED disposition from flag_identity_conflict (conflicting records)."""
    historical = {"opportunity_id": "OPP-1", "title": "Cybersecurity SaaS",
                  "vendor_or_principal_name": "Acme Corp"}
    current = {"opportunity_id": "OPP-1", "title": "Totally Different Title",
               "vendor_or_principal_name": "Different Vendor"}
    return flag_identity_conflict(historical, current)["disposition"]


# ---------------------------------------------------------------------------
# Unit tests: evaluate_identity_gate
# ---------------------------------------------------------------------------


class TestEvaluateIdentityGate:
    def test_verified_and_reconciled_proceeds(self) -> None:
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        rec.record_identity_verification(
            _verified_result().status,
            disposition=_reconciled_disposition(),
        )
        gate = evaluate_identity_gate(rec)
        assert gate["allowed"] is True
        assert gate["reason"] == ""
        assert gate["status"] == IDENTITY_VERIFIED_STATUS
        assert gate["disposition"] == IDENTITY_RECONCILED_DISPOSITION

    def test_mismatch_blocks(self) -> None:
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        rec.record_identity_verification(
            _mismatch_result().status,
            disposition=_reconciled_disposition(),
        )
        gate = evaluate_identity_gate(rec)
        assert gate["allowed"] is False
        assert "IDENTITY_MISMATCH" in gate["reason"]
        assert gate["status"] == IdentityVerificationResult.MISMATCH

    def test_empty_blocks(self) -> None:
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        rec.record_identity_verification(
            _empty_result().status,
            disposition=_reconciled_disposition(),
        )
        gate = evaluate_identity_gate(rec)
        assert gate["allowed"] is False
        assert "PAGE_EMPTY" in gate["reason"]
        assert gate["status"] == IdentityVerificationResult.EMPTY

    def test_unreachable_blocks(self) -> None:
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        rec.record_identity_verification(
            _unreachable_result().status,
            disposition=_reconciled_disposition(),
        )
        gate = evaluate_identity_gate(rec)
        assert gate["allowed"] is False
        assert "PAGE_UNREACHABLE" in gate["reason"]
        assert gate["status"] == IdentityVerificationResult.UNREACHABLE

    def test_quarantined_disposition_blocks(self) -> None:
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        rec.record_identity_verification(
            _verified_result().status,
            disposition=_quarantined_disposition(),
        )
        gate = evaluate_identity_gate(rec)
        assert gate["allowed"] is False
        assert "QUARANTINED" in gate["reason"]
        assert gate["disposition"] == "QUARANTINED"

    def test_stale_disposition_blocks(self) -> None:
        # flag_identity_conflict never produces STALE in the current
        # implementation, but the gate must still block it when a caller
        # records it (constructed input).
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        rec.record_identity_verification(
            _verified_result().status,
            disposition="STALE",
        )
        gate = evaluate_identity_gate(rec)
        assert gate["allowed"] is False
        assert "STALE" in gate["reason"]
        assert gate["disposition"] == "STALE"

    def test_no_verification_blocks(self) -> None:
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        gate = evaluate_identity_gate(rec)
        assert gate["allowed"] is False
        assert "has not been run" in gate["reason"]
        assert gate["status"] == ""

    def test_verified_with_empty_disposition_blocks(self) -> None:
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        rec.record_identity_verification(
            _verified_result().status,
            disposition="",
        )
        gate = evaluate_identity_gate(rec)
        assert gate["allowed"] is False
        assert "not been reconciled" in gate["reason"]

    def test_none_record_blocks(self) -> None:
        gate = evaluate_identity_gate(None)
        assert gate["allowed"] is False
        assert "not found" in gate["reason"]


# ---------------------------------------------------------------------------
# Integration tests: FormSubmissionEngine.submit_application
# ---------------------------------------------------------------------------


def _engine(tmp_path: Path, registry: OpportunityStateRegistry) -> FormSubmissionEngine:
    engine = FormSubmissionEngine(
        browser=FakeBrowser(),
        gate=FakeApprovalGate(approved_ids={"A42"}),
        supervisor=FakeSupervisorRelay(response=_approved_supervisor_response()),
        audit=SubmissionAuditModule(audit_path=tmp_path / "audit.jsonl"),
        settings=_make_settings(),
    )
    engine.attach_registry(registry)
    return engine


def _registry_with_identity(
    opportunity_id: str,
    status: str,
    disposition: str,
) -> OpportunityStateRegistry:
    registry = OpportunityStateRegistry()
    record = registry._get_or_create(opportunity_id)
    record.title = "Cybersecurity SaaS"
    record.principal_name = "Acme Corp"
    record.lifecycle_state = LIFECYCLE_APPLICATION_APPROVED
    record.record_identity_verification(status, disposition=disposition)
    return registry


class TestFormSubmissionEngineIdentityGate:
    def test_verified_and_reconciled_proceeds(self, tmp_path: Path) -> None:
        registry = _registry_with_identity(
            "OPP-1", _verified_result().status, _reconciled_disposition()
        )
        engine = _engine(tmp_path, registry)
        result = engine.submit_application("OPP-1", "A42", dry_run=True)
        assert result.ok is True
        assert result.error == ""
        assert result.identity_gate["allowed"] is True
        records = engine.audit._read_records()
        assert any(r.status == "dry_run" for r in records)

    def test_mismatch_blocks_and_audits(self, tmp_path: Path) -> None:
        registry = _registry_with_identity(
            "OPP-1", _mismatch_result().status, _reconciled_disposition()
        )
        engine = _engine(tmp_path, registry)
        result = engine.submit_application("OPP-1", "A42", dry_run=True)
        assert result.ok is False
        assert "Identity gate blocked" in result.error
        assert "IDENTITY_MISMATCH" in result.error
        records = engine.audit._read_records()
        assert any(r.status == "aborted" for r in records)
        aborted = next(r for r in records if r.status == "aborted")
        assert aborted.identity_gate["allowed"] is False
        assert aborted.identity_gate["status"] == IdentityVerificationResult.MISMATCH

    def test_empty_blocks_and_audits(self, tmp_path: Path) -> None:
        registry = _registry_with_identity(
            "OPP-1", _empty_result().status, _reconciled_disposition()
        )
        engine = _engine(tmp_path, registry)
        result = engine.submit_application("OPP-1", "A42", dry_run=True)
        assert result.ok is False
        assert "PAGE_EMPTY" in result.error
        records = engine.audit._read_records()
        assert any(r.status == "aborted" for r in records)
        assert next(r for r in records if r.status == "aborted").identity_gate["status"] == (
            IdentityVerificationResult.EMPTY
        )

    def test_unreachable_blocks_and_audits(self, tmp_path: Path) -> None:
        registry = _registry_with_identity(
            "OPP-1", _unreachable_result().status, _reconciled_disposition()
        )
        engine = _engine(tmp_path, registry)
        result = engine.submit_application("OPP-1", "A42", dry_run=True)
        assert result.ok is False
        assert "PAGE_UNREACHABLE" in result.error
        records = engine.audit._read_records()
        assert any(r.status == "aborted" for r in records)

    def test_quarantined_blocks_and_audits(self, tmp_path: Path) -> None:
        registry = _registry_with_identity(
            "OPP-1", _verified_result().status, _quarantined_disposition()
        )
        engine = _engine(tmp_path, registry)
        result = engine.submit_application("OPP-1", "A42", dry_run=True)
        assert result.ok is False
        assert "QUARANTINED" in result.error
        records = engine.audit._read_records()
        assert any(r.status == "aborted" for r in records)
        assert next(r for r in records if r.status == "aborted").identity_gate["disposition"] == (
            "QUARANTINED"
        )

    def test_stale_blocks_and_audits(self, tmp_path: Path) -> None:
        registry = _registry_with_identity(
            "OPP-1", _verified_result().status, "STALE"
        )
        engine = _engine(tmp_path, registry)
        result = engine.submit_application("OPP-1", "A42", dry_run=True)
        assert result.ok is False
        assert "STALE" in result.error
        records = engine.audit._read_records()
        assert any(r.status == "aborted" for r in records)

    def test_no_verification_blocks_and_audits(self, tmp_path: Path) -> None:
        registry = OpportunityStateRegistry()
        record = registry._get_or_create("OPP-1")
        record.title = "Cybersecurity SaaS"
        record.principal_name = "Acme Corp"
        record.lifecycle_state = LIFECYCLE_APPLICATION_APPROVED
        engine = _engine(tmp_path, registry)
        result = engine.submit_application("OPP-1", "A42", dry_run=True)
        assert result.ok is False
        assert "has not been run" in result.error
        records = engine.audit._read_records()
        assert any(r.status == "aborted" for r in records)
        assert next(r for r in records if r.status == "aborted").identity_gate["status"] == ""


# ---------------------------------------------------------------------------
# Integration tests: CRMPipeline application_submitted write gate
# ---------------------------------------------------------------------------


def _make_read_rows(status: str) -> dict[str, Any]:
    header = [
        "lead_id", "created_at_utc", "source", "source_url", "company_name",
        "contact_name", "contact_email", "role_title", "market", "country",
        "problem_signal", "commission_signal", "fit_score", "status", "notes",
    ]
    return {
        "ok": True,
        "rows": [header, ["OPP-1", "2024-01-01", "", "", "Acme", "Alice", "", "",
                          "", "", "", "", "", status, ""]],
    }


class TestCRMPipelineIdentityGate:
    def test_unverified_blocks_application_submitted(self) -> None:
        mock_adapter = MagicMock()
        registry = OpportunityStateRegistry()
        registry._get_or_create("OPP-1")
        pipeline = CRMPipeline(sheets_adapter=mock_adapter)
        pipeline.attach_registry(registry)
        mock_adapter.read_last_rows.return_value = _make_read_rows(
            OpportunityStage.APPLICATION_APPROVED.value
        )
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance_stage(
            "OPP-1", OpportunityStage.APPLICATION_SUBMITTED.value, dry_run=False
        )
        assert result["ok"] is False
        assert "Identity gate blocked" in result["error"]
        assert "has not been run" in result["error"]
        mock_adapter.upsert_row_by_key.assert_not_called()

    def test_verified_and_reconciled_proceeds(self) -> None:
        mock_adapter = MagicMock()
        registry = OpportunityStateRegistry()
        rec = registry._get_or_create("OPP-1")
        rec.record_identity_verification(
            _verified_result().status, disposition=_reconciled_disposition()
        )
        pipeline = CRMPipeline(sheets_adapter=mock_adapter)
        pipeline.attach_registry(registry)
        mock_adapter.read_last_rows.return_value = _make_read_rows(
            OpportunityStage.APPLICATION_APPROVED.value
        )
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance_stage(
            "OPP-1", OpportunityStage.APPLICATION_SUBMITTED.value, dry_run=False
        )
        assert result["ok"] is True
        assert result["new_stage"] == OpportunityStage.APPLICATION_SUBMITTED.value
        mock_adapter.upsert_row_by_key.assert_called_once()

    def test_quarantined_blocks_and_records_on_registry(self) -> None:
        mock_adapter = MagicMock()
        registry = OpportunityStateRegistry()
        rec = registry._get_or_create("OPP-1")
        rec.record_identity_verification(
            _verified_result().status, disposition=_quarantined_disposition()
        )
        pipeline = CRMPipeline(sheets_adapter=mock_adapter)
        pipeline.attach_registry(registry)
        mock_adapter.read_last_rows.return_value = _make_read_rows(
            OpportunityStage.APPLICATION_APPROVED.value
        )
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance_stage(
            "OPP-1", OpportunityStage.APPLICATION_SUBMITTED.value, dry_run=False
        )
        assert result["ok"] is False
        assert "QUARANTINED" in result["error"]
        # Block is recorded on the registry record for auditability.
        assert any("identity_gate_blocked" in c for c in rec.conflicts)
        mock_adapter.upsert_row_by_key.assert_not_called()

    def test_no_registry_blocks_application_submitted(self) -> None:
        mock_adapter = MagicMock()
        pipeline = CRMPipeline(sheets_adapter=mock_adapter)
        mock_adapter.read_last_rows.return_value = _make_read_rows(
            OpportunityStage.APPLICATION_APPROVED.value
        )
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        result = pipeline.advance_stage(
            "OPP-1", OpportunityStage.APPLICATION_SUBMITTED.value, dry_run=False
        )
        assert result["ok"] is False
        assert "no state registry wired" in result["error"]
        mock_adapter.upsert_row_by_key.assert_not_called()

    def test_non_application_stages_not_gated(self) -> None:
        mock_adapter = MagicMock()
        pipeline = CRMPipeline(sheets_adapter=mock_adapter)
        mock_adapter.read_last_rows.return_value = _make_read_rows(
            OpportunityStage.SOURCED.value
        )
        mock_adapter.upsert_row_by_key.return_value = {"ok": True}
        # Sourced -> researched is not identity-sensitive; no registry wired.
        result = pipeline.advance_stage(
            "OPP-1", OpportunityStage.RESEARCHED.value, dry_run=False
        )
        assert result["ok"] is True
        mock_adapter.upsert_row_by_key.assert_called_once()
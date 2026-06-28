"""Regression tests for Wave 3 Track A hardening (R1 / R2 / L1 / L2 + dry-run gate parity).

Each test pins one confirmed fix from the code-quality / security-hardening sweep:

- R1: ``FormSubmissionEngine._write_audit`` wraps ``audit.append`` in
  ``except OSError`` so an I/O failure on an abort path degrades to
  ``SubmissionResult(ok=False)`` instead of propagating ``OSError`` out of
  every abort path (form_submission_engine.py:519-531).
- R2: ``CommissionCrowdApiAdapter`` defaults to TLS verification ON; the only
  way to disable is an explicit ``insecure_skip_verify=True`` constructor arg
  or the ``commissioncrowd_insecure_skip_verify`` setting (commissioncrowd_adapter.py:90-108).
- L1: ``CRMPipeline.advance_stage`` dry-run missing-lead surfaces as ok:False
  (crm_pipeline.py:300-314) and ``advance_stage`` / ``update_stage`` dry-run
  paths now evaluate the identity gate for ``application_submitted`` so
  dry-run/live parity holds (crm_pipeline.py:292-324, 466-484).
- L2: ``OpportunityStateRecord.to_canonical_opportunity`` narrows from
  ``except Exception`` to ``except (TypeError, ValueError)`` and logs
  (state_registry.py:187-198) — pydantic ``ValidationError`` inherits from
  ``ValueError`` so malformed records still degrade to None instead of raising.

The internal modules under test are never mocked; only external service
boundaries (httpx, the audit JSONL store path) are intercepted, matching the
``tests/test_identity_gate.py`` convention.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from commission_crowd_agent.candidate_identity import IdentityVerificationResult
from commission_crowd_agent.commissioncrowd_adapter import CommissionCrowdApiAdapter
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
)
from commission_crowd_agent.submission_audit import SubmissionAuditModule
from commission_crowd_agent.supervisor_relay import SupervisorResponse

# ---------------------------------------------------------------------------
# Shared fakes (mirrors tests/test_identity_gate.py).
# ---------------------------------------------------------------------------


class FakeBrowser:
    @property
    def _page(self) -> None:
        return None


class FakeApprovalGate:
    def __init__(self, approved_ids: set[str] | None = None) -> None:
        self._approved = approved_ids or set()

    def is_approved(self, approval_id: str) -> bool:
        return approval_id in self._approved


class FakeSupervisorRelay:
    def __init__(self) -> None:
        self._response = SupervisorResponse(
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


def _engine(tmp_path: Path, registry: OpportunityStateRegistry) -> FormSubmissionEngine:
    engine = FormSubmissionEngine(
        browser=FakeBrowser(),
        gate=FakeApprovalGate(approved_ids={"A42"}),
        supervisor=FakeSupervisorRelay(),
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


# ---------------------------------------------------------------------------
# R1: audit-write OSError degrades abort paths to SubmissionResult(ok=False).
# ---------------------------------------------------------------------------


class TestAuditWriteOSErrorDegrades:
    def test_identity_gate_abort_survives_audit_oserror(self, tmp_path: Path) -> None:
        """An OSError on the audit append must not propagate out of an abort path.

        The identity-gate block at form_submission_engine.py:340-345 calls
        ``_write_audit(result, status="aborted")``. When ``audit.append``
        raises OSError (disk full / read-only FS), the abort path must still
        return ``SubmissionResult(ok=False)`` with the identity-gate error
        rather than propagating the OSError.
        """
        registry = _registry_with_identity(
            "OPP-1",
            IdentityVerificationResult.MISMATCH,
            IDENTITY_RECONCILED_DISPOSITION,
        )
        engine = _engine(tmp_path, registry)
        # Sabotage the audit path so the next append raises NotADirectoryError
        # (a subclass of OSError) — a real I/O failure, not a mock.
        engine.audit.audit_path = Path("/dev/null/audit.jsonl")

        # Must not raise; the OSError is caught and the abort result is returned.
        result = engine.submit_application("OPP-1", "A42", dry_run=True)
        assert result.ok is False
        assert "Identity gate blocked" in (result.error or "")
        # The audit_id is the SubmissionResult default (None) — the abort path
        # ignores _write_audit's return value, so no phantom audit_id is set
        # even when the audit write failed.
        assert result.audit_id is None

    def test_state_guard_abort_survives_audit_oserror(self, tmp_path: Path) -> None:
        """The first abort path (opportunity not in registry) also survives."""
        # Registry has no record for OPP-MISSING.
        registry = OpportunityStateRegistry()
        engine = _engine(tmp_path, registry)
        engine.audit.audit_path = Path("/dev/null/audit.jsonl")

        result = engine.submit_application("OPP-MISSING", "A42", dry_run=True)
        assert result.ok is False
        assert "not found in state registry" in (result.error or "")


# ---------------------------------------------------------------------------
# R2: CommissionCrowdApiAdapter TLS verification gating.
# ---------------------------------------------------------------------------


class TestTLSVerificationGating:
    def test_default_is_verify_true(self) -> None:
        """With no settings and no explicit arg, verify is ON (production-safe)."""
        adapter = CommissionCrowdApiAdapter(api_key="k")
        assert adapter._insecure_skip_verify is False

    def test_explicit_insecure_skip_verify_true(self) -> None:
        adapter = CommissionCrowdApiAdapter(api_key="k", insecure_skip_verify=True)
        assert adapter._insecure_skip_verify is True

    def test_explicit_insecure_skip_verify_false_wins_over_settings(self) -> None:
        """An explicit constructor arg wins over the settings flag."""
        settings = _make_settings(commissioncrowd_insecure_skip_verify=True)
        adapter = CommissionCrowdApiAdapter(
            api_key="k", settings=settings, insecure_skip_verify=False
        )
        assert adapter._insecure_skip_verify is False

    def test_settings_insecure_skip_verify_true(self) -> None:
        settings = _make_settings(commissioncrowd_insecure_skip_verify=True)
        adapter = CommissionCrowdApiAdapter(api_key="k", settings=settings)
        assert adapter._insecure_skip_verify is True

    @patch("httpx.Client")
    def test_verify_arg_passed_to_httpx_is_true_by_default(
        self, mock_client_cls: MagicMock
    ) -> None:
        """The httpx.Client is constructed with verify=True by default."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.request.return_value = MagicMock(
            status_code=200, json=lambda: {"opportunities": "url", "agents": "url"}
        )
        adapter = CommissionCrowdApiAdapter(api_key="k")
        adapter.health_check()
        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["verify"] is True

    @patch("httpx.Client")
    def test_verify_arg_passed_to_httpx_is_false_when_insecure(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.request.return_value = MagicMock(
            status_code=200, json=lambda: {"opportunities": "url", "agents": "url"}
        )
        adapter = CommissionCrowdApiAdapter(api_key="k", insecure_skip_verify=True)
        adapter.health_check()
        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["verify"] is False


# ---------------------------------------------------------------------------
# L1: advance_stage dry-run missing-lead surfaces ok:False + dry-run gate parity.
# ---------------------------------------------------------------------------


class TestDryRunParity:
    def test_dry_run_missing_lead_surfaces_ok_false(self) -> None:
        """L1: a missing lead in dry-run returns ok:False (not silent ok:True)."""
        pipeline = CRMPipeline(sheets_adapter=MagicMock())
        result = pipeline.advance_stage(
            "L-MISSING", OpportunityStage.RESEARCHED.value, dry_run=True
        )
        assert result["ok"] is False
        assert result["dry_run"] is True
        assert "not found in dry-run cache" in result["error"]

    def test_dry_run_application_submitted_blocked_without_registry(self) -> None:
        """Dry-run/live parity: a dry-run application_submitted with no registry
        wired surfaces the same 'no state registry wired' block the live write
        would (Track A L1 principle extended to the identity gate)."""
        pipeline = CRMPipeline(sheets_adapter=MagicMock())
        # Add the lead to the dry-run cache so the missing-lead branch is NOT
        # what triggers the block — the identity gate is.
        pipeline._dry_run_cache["leads"].append({"lead_id": "L1", "status": "sourced"})
        result = pipeline.advance_stage(
            "L1", OpportunityStage.APPLICATION_SUBMITTED.value, dry_run=True
        )
        assert result["ok"] is False
        assert result["dry_run"] is True
        assert "no state registry wired" in result["error"]

    def test_dry_run_application_submitted_blocked_for_unverified(self) -> None:
        """Dry-run/live parity: a dry-run application_submitted for an unverified
        candidate surfaces the same 'has not been run' block the live write would."""
        registry = OpportunityStateRegistry()
        registry._get_or_create("L1")
        pipeline = CRMPipeline(sheets_adapter=MagicMock())
        pipeline.attach_registry(registry)
        pipeline._dry_run_cache["leads"].append({"lead_id": "L1", "status": "sourced"})
        result = pipeline.advance_stage(
            "L1", OpportunityStage.APPLICATION_SUBMITTED.value, dry_run=True
        )
        assert result["ok"] is False
        assert result["dry_run"] is True
        assert "has not been run" in result["error"]

    def test_dry_run_application_submitted_proceeds_when_verified(self) -> None:
        """Dry-run/live parity: a verified+reconciled candidate proceeds in dry-run
        too (the gate returns None and the cache hit returns ok:True)."""
        registry = OpportunityStateRegistry()
        rec = registry._get_or_create("L1")
        rec.record_identity_verification(
            IDENTITY_VERIFIED_STATUS,
            disposition=IDENTITY_RECONCILED_DISPOSITION,
        )
        pipeline = CRMPipeline(sheets_adapter=MagicMock())
        pipeline.attach_registry(registry)
        pipeline._dry_run_cache["leads"].append({"lead_id": "L1", "status": "sourced"})
        result = pipeline.advance_stage(
            "L1", OpportunityStage.APPLICATION_SUBMITTED.value, dry_run=True
        )
        assert result["ok"] is True
        assert result["dry_run"] is True

    def test_dry_run_non_identity_stage_not_gated(self) -> None:
        """Non-application_submitted stages are not identity-sensitive: a dry-run
        sourced->researched transition proceeds without any registry wired."""
        pipeline = CRMPipeline(sheets_adapter=MagicMock())
        pipeline._dry_run_cache["leads"].append({"lead_id": "L1", "status": "sourced"})
        result = pipeline.advance_stage(
            "L1", OpportunityStage.RESEARCHED.value, dry_run=True
        )
        assert result["ok"] is True
        assert result["new_stage"] == OpportunityStage.RESEARCHED.value

    def test_update_stage_dry_run_application_submitted_blocked(self) -> None:
        """update_stage dry-run path also gates application_submitted (parity)."""
        pipeline = CRMPipeline(sheets_adapter=MagicMock())
        result = pipeline.update_stage(
            "L1", OpportunityStage.APPLICATION_SUBMITTED.value, dry_run=True
        )
        assert result["ok"] is False
        assert "no state registry wired" in result["error"]


# ---------------------------------------------------------------------------
# L2: to_canonical_opportunity narrows except and logs malformed records.
# ---------------------------------------------------------------------------


class TestToCanonicalOpportunityNarrowExcept:
    def test_malformed_record_returns_none_not_raise(self) -> None:
        """A record with a non-coercible commission_percent degrades to None
        instead of raising. Pydantic ValidationError inherits ValueError, so
        the narrowed ``except (TypeError, ValueError)`` still catches it."""
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        rec.title = "Title"
        rec.principal_name = "Acme"
        # Non-coercible: pydantic raises ValidationError (a ValueError subclass).
        rec.commission_percent = "not-a-number"  # type: ignore[assignment]
        result = rec.to_canonical_opportunity()
        assert result is None

    def test_valid_record_returns_canonical(self) -> None:
        rec = OpportunityStateRecord(opportunity_id="OPP-1")
        rec.title = "Title"
        rec.principal_name = "Acme"
        rec.commission_percent = 25.0
        result = rec.to_canonical_opportunity()
        assert result is not None
        assert result.source_opportunity_id == "OPP-1"
        assert result.commission_percent == 25.0

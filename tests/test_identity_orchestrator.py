"""Regression tests for ``identity_orchestrator.verify_and_record_identity``.

Wave 3 Track A. The orchestrator wires discovery -> verify -> record: it calls
the real ``verify_candidate_identity`` / ``flag_identity_conflict`` /
``OpportunityStateRecord.record_identity_verification`` in sequence so
``evaluate_identity_gate`` receives input that came from discovery rather than a
hand-stamped ID.

The internal ``candidate_identity`` functions are exercised against constructed
inputs (the ``IdentityFakePage`` pattern from ``tests/test_identity_gate.py``).
No internal module is mocked — only the external browser page boundary.

Covers the edge cases the sweep target calls out:
- missing identity fields (record.title / principal_name empty)
- opportunity_id absent from the registry (ok:False, no crash)
- verify_candidate_identity returning MISMATCH / EMPTY / UNREACHABLE
- flag_identity_conflict divergence (real title change -> QUARANTINED)
- partial failure (verified-but-not-recorded is impossible: record is mutated
  in place and evaluate_identity_gate reads the same object)
"""

from __future__ import annotations

from typing import Any

from commission_crowd_agent.candidate_identity import (
    IdentityVerificationResult,
)
from commission_crowd_agent.identity_orchestrator import verify_and_record_identity
from commission_crowd_agent.state_registry import (
    IDENTITY_RECONCILED_DISPOSITION,
    IDENTITY_VERIFIED_STATUS,
    OpportunityStateRegistry,
    evaluate_identity_gate,
)


class IdentityFakePage:
    """Minimal Playwright page double for ``verify_candidate_identity``."""

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


_BODY_VERIFIED = (
    "Cybersecurity SaaS - Acme Corp\n"
    "Acme Corp is a leading provider of security software. "
    "Earn 25% commission on first-year revenue. "
    "We are Acme Corp, a modern security vendor. "
    "Territory: UK & Ireland. Residual income available. "
    "Deal opportunities for sales agents. " + ("padding content. " * 20)
)


def _registry_with_record(
    opp_id: str = "OPP-1",
    *,
    title: str = "Cybersecurity SaaS - Acme Corp",
    principal_name: str = "Acme Corp",
) -> tuple[OpportunityStateRegistry, Any]:
    registry = OpportunityStateRegistry()
    rec = registry._get_or_create(opp_id)
    rec.title = title
    rec.principal_name = principal_name
    return registry, rec


class TestVerifyAndRecordIdentity:
    def test_verified_and_reconciled_proceeds(self) -> None:
        registry, rec = _registry_with_record()
        page = IdentityFakePage(body_text=_BODY_VERIFIED)
        result = verify_and_record_identity(
            registry,
            "OPP-1",
            page,
            expected_title_fragments=["Cybersecurity SaaS"],
            expected_vendor_fragments=["Acme Corp"],
            settle_ms=0,
        )
        assert result["ok"] is True
        assert result["status"] == IdentityVerificationResult.VERIFIED
        assert result["disposition"] == IDENTITY_RECONCILED_DISPOSITION
        assert result["identity_gate"]["allowed"] is True
        # The registry record is mutated in place: status + disposition recorded.
        assert rec.identity_verification_status == IDENTITY_VERIFIED_STATUS
        assert rec.identity_conflict_disposition == IDENTITY_RECONCILED_DISPOSITION
        assert rec.identity_verified_at != ""

    def test_missing_opportunity_returns_ok_false(self) -> None:
        registry = OpportunityStateRegistry()
        page = IdentityFakePage(body_text=_BODY_VERIFIED)
        result = verify_and_record_identity(
            registry, "DOES-NOT-EXIST", page, settle_ms=0
        )
        assert result["ok"] is False
        assert "not found in registry" in result["error"]
        assert result["identity_gate"]["allowed"] is False
        # No verification was attempted, so the gate reason reflects the miss.
        assert result["identity_gate"]["reason"] == "Opportunity not found in state registry"

    def test_mismatch_verification_still_records_and_blocks(self) -> None:
        registry, rec = _registry_with_record()
        page = IdentityFakePage(body_text=_BODY_VERIFIED)
        result = verify_and_record_identity(
            registry,
            "OPP-1",
            page,
            expected_title_fragments=["Nonexistent Title XYZ"],
            expected_vendor_fragments=["Nonexistent Vendor ABC"],
            settle_ms=0,
        )
        # The orchestrator never swallows a verification failure: MISMATCH is
        # recorded on the registry record and surfaced via the gate.
        assert result["ok"] is True  # the hop ran; the *gate* blocks the write
        assert result["status"] == IdentityVerificationResult.MISMATCH
        assert result["identity_gate"]["allowed"] is False
        assert rec.identity_verification_status == IdentityVerificationResult.MISMATCH

    def test_unreachable_navigation_records_and_blocks(self) -> None:
        registry, rec = _registry_with_record()
        page = IdentityFakePage(body_text=_BODY_VERIFIED, nav_raises=True)
        result = verify_and_record_identity(registry, "OPP-1", page, settle_ms=0)
        assert result["ok"] is True
        assert result["status"] == IdentityVerificationResult.UNREACHABLE
        assert result["identity_gate"]["allowed"] is False
        assert rec.identity_verification_status == IdentityVerificationResult.UNREACHABLE

    def test_empty_page_records_and_blocks(self) -> None:
        registry, rec = _registry_with_record()
        page = IdentityFakePage(body_text="short")
        result = verify_and_record_identity(
            registry,
            "OPP-1",
            page,
            expected_title_fragments=["Cybersecurity SaaS"],
            settle_ms=0,
        )
        assert result["ok"] is True
        assert result["status"] == IdentityVerificationResult.EMPTY
        assert result["identity_gate"]["allowed"] is False
        assert rec.identity_verification_status == IdentityVerificationResult.EMPTY

    def test_real_title_change_quarantines(self) -> None:
        """A genuine title change between registry and live page -> QUARANTINED.

        The orchestrator builds ``current`` from ``verification.extracted_title
        or record.title``. When extraction succeeds and the title differs from
        the registry, ``flag_identity_conflict`` returns QUARANTINED and the
        gate blocks on disposition.
        """
        # Registry holds the OLD title; the live page advertises a different one.
        registry, rec = _registry_with_record(title="OLD TITLE - Acme Corp")
        # Body whose first line is the new title (so _extract_title_from_detail_page
        # returns just that line, not the whole body).
        body = (
            "NEW TITLE - Acme Corp\n"
            "Acme Corp is a leading provider of security software. "
            "Earn 25% commission on first-year revenue. "
            "We are looking for independent sales representatives. "
            "Territory: UK & Ireland. " + ("padding content. " * 20)
        )
        page = IdentityFakePage(body_text=body)
        result = verify_and_record_identity(
            registry,
            "OPP-1",
            page,
            # No fragments -> verified=True (any commission signal accepts), so
            # status is VERIFIED and the gate decision turns on disposition.
            settle_ms=0,
        )
        assert result["ok"] is True
        assert result["status"] == IdentityVerificationResult.VERIFIED
        assert result["disposition"] == "QUARANTINED"
        assert result["identity_gate"]["allowed"] is False
        assert rec.identity_conflict_disposition == "QUARANTINED"

    def test_missing_identity_fields_falls_back_to_registry(self) -> None:
        """A record with empty title/principal_name does not crash the hop.

        ``flag_identity_conflict`` treats empty historical fields as "no
        constraint" (its ``if hist_title and ...`` guard), so an empty record
        + a verified page still proceeds (RECONCILED).
        """
        registry, rec = _registry_with_record(title="", principal_name="")
        page = IdentityFakePage(body_text=_BODY_VERIFIED)
        result = verify_and_record_identity(
            registry, "OPP-1", page, settle_ms=0
        )
        assert result["ok"] is True
        assert result["status"] == IdentityVerificationResult.VERIFIED
        assert result["disposition"] == IDENTITY_RECONCILED_DISPOSITION
        assert result["identity_gate"]["allowed"] is True

    def test_result_dict_carries_extracted_fields(self) -> None:
        """The structured result exposes extracted title/vendor + conflict dict."""
        registry, _ = _registry_with_record()
        page = IdentityFakePage(body_text=_BODY_VERIFIED)
        result = verify_and_record_identity(
            registry,
            "OPP-1",
            page,
            expected_title_fragments=["Cybersecurity SaaS"],
            settle_ms=0,
        )
        assert result["ok"] is True
        assert result["opportunity_id"] == "OPP-1"
        assert isinstance(result["conflict"], dict)
        assert "conflict_detected" in result["conflict"]
        assert "detail" in result
        # The post-record gate decision is the same object evaluate_identity_gate
        # returns when called directly on the mutated record.
        rec = registry.get_by_id("OPP-1")
        assert result["identity_gate"] == evaluate_identity_gate(rec)

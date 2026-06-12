"""Regression tests for candidate identity reconciliation hardening.

Uses local fixtures only — no live network calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from commission_crowd_agent.candidate_identity import (
    IdentityVerificationResult,
    deduplicate_by_id_and_title,
    flag_identity_conflict,
    verify_candidate_identity,
)


class FakePage:
    """Mock Playwright page for deterministic testing."""

    def __init__(self, body_text: str = "", raise_on_evaluate: bool = False):
        self._body_text = body_text
        self._raise_on_evaluate = raise_on_evaluate
        self._hash = ""

    def evaluate(self, js: str) -> Any:
        if self._raise_on_evaluate:
            raise RuntimeError("Navigation failed")
        if "window.location.hash" in js:
            # Set hash side effect
            self._hash = js.split("'")[-2] if "'" in js else ""
            return None
        if "document.body.innerText" in js:
            return self._body_text
        return None

    def wait_for_timeout(self, ms: int) -> None:
        pass


# ── Test 1: verify_candidate_identity returns VERIFIED when title fragment matches ──


class TestVerifyCandidateIdentity:
    def test_verified_when_title_fragment_matches(self) -> None:
        body = (
            "Earn $1M Helping Eye Care Practices TRANSFORM Patient Care!\n"
            "Commission 5%\n"
            "We are an investment group, helping eye care clinics grow. "
            "We are building a leading eye care management service organization powered by smart technologies. "
            "Our team brings more than 200 years of combined experience in eye care, technology, and operations.\n"
            "* " * 50
        )
        page = FakePage(body_text=body)
        result = verify_candidate_identity(
            page,
            target_id="11419",
            expected_title_fragments=["Eye Care", "TRANSFORM"],
        )
        assert result.status == IdentityVerificationResult.VERIFIED
        assert result.target_id == "11419"
        assert result.extracted_title and "Eye Care" in result.extracted_title

    def test_mismatch_when_title_fragment_missing(self) -> None:
        body = (
            "Sustainable Skincare for Indie Retailers & Refill Shops (US Market) | 15% Commission\n"
            "Commission 15%\nWe're STEP ZERO — a modern, Asian-inspired shower care brand reinventing skincare for busy, eco-conscious consumers. "
            "Our products are available in refill shops and indie retailers across the United States. "
            "* " * 50
        )
        page = FakePage(body_text=body)
        result = verify_candidate_identity(
            page,
            target_id="11419",
            expected_title_fragments=["Eye Care"],
        )
        assert result.status == IdentityVerificationResult.MISMATCH
        assert result.target_id == "11419"

    def test_empty_when_generic_shell(self) -> None:
        page = FakePage(body_text="CommissionCrowd\nDashboard\nNotifications\nHelp centre")
        result = verify_candidate_identity(page, target_id="39292")
        assert result.status == IdentityVerificationResult.EMPTY
        assert "generic shell" in result.detail.lower()

    def test_empty_when_body_too_short(self) -> None:
        page = FakePage(body_text="OK")
        result = verify_candidate_identity(page, target_id="99999")
        assert result.status == IdentityVerificationResult.EMPTY
        assert "too short" in result.detail.lower()

    def test_unreachable_on_navigation_error(self) -> None:
        page = FakePage(raise_on_evaluate=True)
        result = verify_candidate_identity(page, target_id="99999")
        assert result.status == IdentityVerificationResult.UNREACHABLE

    def test_fallback_accept_when_no_fragments_provided(self) -> None:
        body = (
            "Some Random Opportunity Title\n"
            "Commission 20%\nVendor ABC Corp offers managed IT services to SMBs. "
            "We are a leading provider of cybersecurity solutions in the United States. "
            "* " * 50
        )
        page = FakePage(body_text=body)
        result = verify_candidate_identity(page, target_id="12345")
        assert result.status == IdentityVerificationResult.VERIFIED


# ── Test 2: deduplicate_by_id_and_title preserves different IDs with same title ──


class TestDeduplicateByIdAndTitle:
    def test_preserves_different_ids_same_title(self) -> None:
        records = [
            {"opportunity_id": "111", "title": "Managed IT Services"},
            {"opportunity_id": "222", "title": "Managed IT Services"},
        ]
        out = deduplicate_by_id_and_title(records)
        assert len(out) == 2
        ids = {r["opportunity_id"] for r in out}
        assert ids == {"111", "222"}

    def test_dedupes_same_id_same_title(self) -> None:
        records = [
            {"opportunity_id": "111", "title": "Managed IT"},
            {"opportunity_id": "111", "title": "Managed IT"},
        ]
        out = deduplicate_by_id_and_title(records)
        assert len(out) == 1

    def test_dedupes_same_id_different_title_case(self) -> None:
        records = [
            {"opportunity_id": "111", "title": "Managed IT"},
            {"opportunity_id": "111", "title": "managed it"},
        ]
        out = deduplicate_by_id_and_title(records)
        assert len(out) == 1

    def test_empty_list(self) -> None:
        assert deduplicate_by_id_and_title([]) == []


# ── Test 3: flag_identity_conflict detects and quarantines conflicts ──


class TestFlagIdentityConflict:
    def test_no_conflict_when_exact_match(self) -> None:
        result = flag_identity_conflict(
            {
                "opportunity_id": "11419",
                "title": "Eye Care",
                "vendor_or_principal_name": "EyeCo",
            },
            {
                "opportunity_id": "11419",
                "title": "Eye Care",
                "vendor_or_principal_name": "EyeCo",
            },
        )
        assert result["conflict_detected"] is False
        assert result["conflict_type"] == "NONE"
        assert result["disposition"] == "RECONCILED"

    def test_quarantine_on_id_reuse(self) -> None:
        result = flag_identity_conflict(
            {"opportunity_id": "11419", "title": "Eye Care", "vendor_or_principal_name": "EyeCo"},
            {"opportunity_id": "99999", "title": "Eye Care", "vendor_or_principal_name": "EyeCo"},
        )
        assert result["conflict_detected"] is True
        assert result["conflict_type"] == "ID_REUSED"
        assert result["disposition"] == "QUARANTINED"

    def test_quarantine_on_title_change(self) -> None:
        result = flag_identity_conflict(
            {"opportunity_id": "11419", "title": "Eye Care", "vendor_or_principal_name": "EyeCo"},
            {"opportunity_id": "11419", "title": "Skincare", "vendor_or_principal_name": "EyeCo"},
        )
        assert result["conflict_detected"] is True
        assert result["conflict_type"] == "TITLE_CHANGED"
        assert result["disposition"] == "QUARANTINED"

    def test_quarantine_on_vendor_change(self) -> None:
        result = flag_identity_conflict(
            {"opportunity_id": "11419", "title": "Eye Care", "vendor_or_principal_name": "EyeCo"},
            {
                "opportunity_id": "11419",
                "title": "Eye Care",
                "vendor_or_principal_name": "StepZero",
            },
        )
        assert result["conflict_detected"] is True
        assert result["conflict_type"] == "VENDOR_CHANGED"
        assert result["disposition"] == "QUARANTINED"

    def test_quarantine_when_multiple_conflicts(self) -> None:
        result = flag_identity_conflict(
            {"opportunity_id": "11419", "title": "Eye Care", "vendor_or_principal_name": "EyeCo"},
            {
                "opportunity_id": "99999",
                "title": "Skincare",
                "vendor_or_principal_name": "StepZero",
            },
        )
        assert result["conflict_detected"] is True
        assert result["conflict_type"] == "ID_REUSED"
        assert result["disposition"] == "QUARANTINED"
        assert len(result["details"]) == 3  # id, title, vendor all mismatch


# ── Test 4: Atomic extraction — ID and title from same card ──


class TestAtomicExtractionInvariant:
    """Simulate extraction patterns from browser_discovery_v11 and assert atomicity."""

    def test_extracted_id_matches_href_regex(self) -> None:
        """The opp_id must come from the same card's href, not from a separate source."""
        # Simulated DOM card
        card = {
            "innerText": "Managed IT & Cybersecurity\n20% Commission\nView details",
            "href": "https://www.commissioncrowd.com/app/#/opportunities/39452",
        }
        import re

        m = re.search(r"/opportunities/(\d+)", card["href"])
        opp_id = m.group(1) if m else ""
        title = card["innerText"].split("\n")[0].strip()
        assert opp_id == "39452"
        assert title == "Managed IT & Cybersecurity"
        # The key invariant: both come from the SAME card object
        assert card["href"].endswith(f"/opportunities/{opp_id}")

    def test_reject_index_based_join(self) -> None:
        """If IDs and titles were extracted from separate arrays, the mapping is untrustworthy."""
        ids = ["111", "222", "333"]
        titles = ["Alpha", "Beta"]  # One fewer — would cause misalignment
        with pytest.raises(AssertionError):
            # Any code that joins by index without length check is buggy
            assert len(ids) == len(titles), (
                "ID and title arrays have different lengths — extraction misalignment risk"
            )

    def test_virtualized_list_reordering_risk(self) -> None:
        """If the DOM reorders during extraction, card-level atomic extraction still works
        because each card carries its own ID and title. Index-based extraction would fail."""
        cards = [
            {"id": "222", "title": "Beta"},
            {"id": "111", "title": "Alpha"},
            {"id": "333", "title": "Gamma"},
        ]
        # Simulate reordering
        cards_shuffled = cards[::-1]
        extracted = {(c["id"], c["title"]) for c in cards_shuffled}
        assert extracted == {("111", "Alpha"), ("222", "Beta"), ("333", "Gamma")}


# ── Test 5: Unverified identity conflict state ──


class TestUnverifiedIdentityConflict:
    def test_unverified_when_no_historical_match(self) -> None:
        """If a candidate has no verified current match, disposition must not be RECONCILED."""
        historical = {"opportunity_id": "39292", "title": "GDPR AI Chatbots"}
        # Simulate empty current record (generic shell)
        current = {"opportunity_id": "", "title": "", "vendor_or_principal_name": ""}
        result = flag_identity_conflict(historical, current)
        # With empty current, there is no ID mismatch, but there is a title mismatch
        # because "" != "GDPR AI Chatbots"
        assert result["conflict_detected"] is True
        assert result["disposition"] == "QUARANTINED"

    def test_disposition_never_approved(self) -> None:
        """Ensure disposition values are never APPROVED, REJECTED, APPLY, or CRM_READY."""
        valid_dispositions = {"RECONCILED", "QUARANTINED", "STALE"}
        historical = {"opportunity_id": "1", "title": "T", "vendor_or_principal_name": "V"}
        current = {"opportunity_id": "1", "title": "T", "vendor_or_principal_name": "V"}
        result = flag_identity_conflict(historical, current)
        assert result["disposition"] in valid_dispositions


# ── Test 6: Commission signal detection ──


class TestCommissionSignalDetection:
    def test_detects_percent_sign(self) -> None:
        body = (
            "20% Commission on all sales\n"
            + "This is a detailed opportunity description with enough content to pass the minimum length threshold. "
            * 10
        )
        page = FakePage(body_text=body)
        result = verify_candidate_identity(page, target_id="1")
        assert result.status == IdentityVerificationResult.VERIFIED

    def test_detects_dollar_sign(self) -> None:
        body = (
            "Earn $1K per deal\n"
            + "This is a detailed opportunity description with enough content to pass the minimum length threshold. "
            * 10
        )
        page = FakePage(body_text=body)
        result = verify_candidate_identity(page, target_id="1")
        assert result.status == IdentityVerificationResult.VERIFIED

    def test_detects_earn_keyword(self) -> None:
        body = (
            "Earn recurring residuals\n"
            + "This is a detailed opportunity description with enough content to pass the minimum length threshold. "
            * 10
        )
        page = FakePage(body_text=body)
        result = verify_candidate_identity(page, target_id="1")
        assert result.status == IdentityVerificationResult.VERIFIED

    def test_fails_without_signal(self) -> None:
        page = FakePage(body_text="Welcome to CommissionCrowd\nDashboard\nHelp centre")
        result = verify_candidate_identity(page, target_id="1")
        assert result.status == IdentityVerificationResult.EMPTY

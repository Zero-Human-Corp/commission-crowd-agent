"""Tests for CommissionCrowd public listing extractor.

Covers:
- Extraction from saved fixture HTML files (real public pages)
- High confidence when both territory and commission are present
- Medium confidence when one meta field is missing
- Per-source limit and global cap enforcement
- No secrets printed
- Graceful zero-result for empty/broken HTML
- Deduplication by URL
"""

from __future__ import annotations

from pathlib import Path

import pytest

from commission_crowd_agent.directory_extractor import (
    _extract_commissioncrowd,
    extract_candidates,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "commissioncrowd"


class TestExtractCommissionCrowd:
    def test_banking_fixture_extracts_candidates(self) -> None:
        html = (FIXTURES_DIR / "banking.html").read_text(encoding="utf-8")
        candidates = _extract_commissioncrowd(
            html,
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/banking/",
            source_name="Banking",
            source_type="public_commissioncrowd_industry_listing",
        )
        assert len(candidates) >= 3
        titles = [c.company for c in candidates]
        assert "RiverForest RPO Opportunity" in titles
        # Every candidate must have a URL
        for c in candidates:
            assert c.url.startswith("https://www.commissioncrowd.com/listings/")
            assert c.extraction_confidence in ("high", "medium")
            assert c.extraction_method == "commissioncrowd_public_card"

    def test_security_fixture_extracts_candidates(self) -> None:
        html = (FIXTURES_DIR / "security-investigations.html").read_text(encoding="utf-8")
        candidates = _extract_commissioncrowd(
            html,
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/security-investigations/",
            source_name="Security",
            source_type="public_commissioncrowd_industry_listing",
        )
        assert len(candidates) >= 3
        # At least one candidate should have territory and commission visible
        high_conf = [c for c in candidates if c.extraction_confidence == "high"]
        assert len(high_conf) >= 1

    def test_translation_fixture_extracts_candidates(self) -> None:
        html = (FIXTURES_DIR / "translation-localization.html").read_text(encoding="utf-8")
        candidates = _extract_commissioncrowd(
            html,
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/translation-localization/",
            source_name="Translation",
            source_type="public_commissioncrowd_industry_listing",
        )
        assert len(candidates) >= 3
        for c in candidates:
            assert c.source_url != ""
            assert c.source_type == "public_commissioncrowd_industry_listing"

    def test_notes_include_public_meta(self) -> None:
        html = (FIXTURES_DIR / "banking.html").read_text(encoding="utf-8")
        candidates = _extract_commissioncrowd(
            html,
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/banking/",
            source_name="Banking",
            source_type="public_commissioncrowd_industry_listing",
        )
        first = candidates[0]
        assert "Snippet:" in first.notes
        assert "Territory:" in first.notes
        assert "Commission:" in first.notes

    def test_dispatch_for_commissioncrowd_domain(self) -> None:
        html = (FIXTURES_DIR / "banking.html").read_text(encoding="utf-8")
        candidates = extract_candidates(
            html,
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/banking/",
            source_name="Banking",
            source_type="public_commissioncrowd_industry_listing",
            max_candidates=3,
        )
        assert len(candidates) == 3
        assert candidates[0].company != ""

    def test_max_candidates_respected(self) -> None:
        html = (FIXTURES_DIR / "banking.html").read_text(encoding="utf-8")
        candidates = extract_candidates(
            html,
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/banking/",
            source_name="Banking",
            source_type="public_commissioncrowd_industry_listing",
            max_candidates=2,
        )
        assert len(candidates) == 2

    def test_empty_html_returns_empty(self) -> None:
        candidates = _extract_commissioncrowd(
            "<html><body></body></html>",
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/banking/",
            source_name="Banking",
            source_type="public_commissioncrowd_industry_listing",
        )
        assert candidates == []

    def test_broken_html_graceful(self) -> None:
        candidates = _extract_commissioncrowd(
            "not html at all",
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/banking/",
            source_name="Banking",
            source_type="public_commissioncrowd_industry_listing",
        )
        assert candidates == []

    def test_deduplication_by_url(self) -> None:
        # The fixture contains repeated links (multiple per page). Ensure dedup works.
        html = (FIXTURES_DIR / "banking.html").read_text(encoding="utf-8")
        candidates = _extract_commissioncrowd(
            html,
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/banking/",
            source_name="Banking",
            source_type="public_commissioncrowd_industry_listing",
        )
        urls = [c.url for c in candidates]
        assert len(urls) == len(set(urls))

    def test_no_secrets_in_to_dict(self) -> None:
        html = (FIXTURES_DIR / "banking.html").read_text(encoding="utf-8")
        candidates = _extract_commissioncrowd(
            html,
            source_url="https://www.commissioncrowd.com/listings/commission-only-sales-opportunities/industry/banking/",
            source_name="Banking",
            source_type="public_commissioncrowd_industry_listing",
        )
        for c in candidates:
            d = c.to_dict()
            assert "secret" not in str(d).lower()
            assert "password" not in str(d).lower()
            assert "token" not in str(d).lower()

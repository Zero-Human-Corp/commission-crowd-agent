"""Tests for the enriched scoring workflow.

Covers fallback heuristics for sparse listings, ICP overrides, and manual
valuation overrides from Sheet rows.
"""

from __future__ import annotations

from commission_crowd_agent.canonical import CanonicalOpportunity
from commission_crowd_agent.workflows.scoring import (
    _apply_manual_override,
    _normalise,
    _parse_usd_value,
    _phrase_set,
    _token_overlap,
    score_opportunities,
    score_with_enrichment,
)


class TestManualOverrideParsing:
    def test_parse_usd_value_variants(self) -> None:
        assert _parse_usd_value("$5,000") == 5000
        assert _parse_usd_value("2500") == 2500
        assert _parse_usd_value("USD 12,500 / year") == 12500
        assert _parse_usd_value("") is None
        assert _parse_usd_value("unknown") is None

    def test_apply_manual_override_from_header(self) -> None:
        header = ["opportunity_id", "company_name", "manual_override"]
        row = ["OPP-1", "Acme", "$9,000"]
        value, applied, reasons = _apply_manual_override(None, header, row)  # type: ignore[arg-type]
        assert applied is True
        assert value == 9000
        assert "manual_override" in reasons[0]

    def test_apply_manual_override_no_value(self) -> None:
        header = ["opportunity_id", "manual_override"]
        row = ["OPP-1", ""]
        value, applied, _ = _apply_manual_override(None, header, row)  # type: ignore[arg-type]
        assert applied is False
        assert value is None


class TestTokenOverlap:
    def test_phrase_and_word_match(self) -> None:
        seen, matched = _token_overlap(["B2B SaaS"], ["B2B SaaS", "Artificial Intelligence"])
        # A full phrase match is counted once so we do not double-score words.
        assert seen == 1
        assert matched == ["B2B SaaS"]

    def test_word_match_without_full_phrase(self) -> None:
        seen, matched = _token_overlap(["B2B", "SaaS"], ["B2B SaaS", "Artificial Intelligence"])
        assert seen == 2
        assert sorted(matched) == ["B2B", "SaaS"]


class TestFallbackEnrichment:
    def test_sparse_icp_override_passes(self) -> None:
        opp = CanonicalOpportunity(
            source="test",
            source_opportunity_id="SPARSE-1",
            title="B2B SaaS opportunity in North America",
            company_name="Sparse Principal",
            category="B2B SaaS",
            territory="North America",
            active=True,
            completeness=85,
            view_count=250,
            application_count=12,
            data_quality_flags=["missing_commission_text", "unclear_commission_rate"],
        )
        result = score_with_enrichment(opp)
        assert result.passed is True
        assert result.icp_score >= 70
        assert result.monetary_score == 0

    def test_icp_override_lift_below_threshold(self) -> None:
        opp = CanonicalOpportunity(
            source="test",
            source_opportunity_id="SPARSE-LOW",
            title="Aligned but low activity",
            company_name="Borderline Principal",
            category="B2B SaaS",
            territory="North America",
            active=True,
            completeness=20,
            view_count=5,
            data_quality_flags=["missing_commission_text"],
        )
        result = score_with_enrichment(opp, research_threshold=80, icp_threshold=50)
        assert result.fit_score < 80
        assert result.passed is True
        assert any("ICP override" in r for r in result.reasons)

    def test_manual_override_lifts_sparse_lock(self) -> None:
        opp = CanonicalOpportunity(
            source="test",
            source_opportunity_id="SPARSE-2",
            title="Unknown industry no territory",
            company_name="Locked Principal",
            active=True,
            completeness=30,
            data_quality_flags=["missing_commission_text"],
        )
        result = score_with_enrichment(opp, manual_value_usd=15000)
        assert result.passed is True
        assert result.manual_override_applied is True
        assert result.manual_value_usd == 15000

    def test_clear_monetary_profile_passes(self) -> None:
        opp = CanonicalOpportunity(
            source="test",
            source_opportunity_id="CLEAR-1",
            title="Cybersecurity — 20% recurring",
            company_name="Clear Principal",
            category="Cybersecurity",
            territory="Global",
            active=True,
            commission_text="20% recurring commission",
            commission_percent=20.0,
            residual_terms=True,
            deal_value_usd=25000,
        )
        result = score_with_enrichment(opp)
        assert result.passed is True
        assert result.monetary_score >= 20


class TestScoreOpportunitiesDryRun:
    def test_dry_run_sample_opportunities(self) -> None:
        opps = [
            CanonicalOpportunity(
                source="sample",
                source_opportunity_id="S-1",
                title="SaaS",
                category="B2B SaaS",
                active=True,
            )
        ]
        result = score_opportunities(opps, dry_run=True)
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["total"] == 1
        assert result["manual_overrides_found"] == 0

    def test_opportunity_row_shape(self) -> None:
        opp = CanonicalOpportunity(
            source="test",
            source_opportunity_id="ROW-1",
            title="Row test",
            company_name="Row Co",
            active=True,
            completeness=90,
            category="B2B SaaS",
            territory="Global",
        )
        score = score_with_enrichment(opp)
        row = score.to_opportunity_row()
        assert row[0] == "ROW-1"
        assert row[3] == "Row Co"
        assert row[11] == "passed"
        assert row[13]  # reasons column is non-empty

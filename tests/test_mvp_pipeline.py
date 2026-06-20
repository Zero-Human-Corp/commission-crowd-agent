"""Tests for MVP pipeline scoring, filtering, and draft generation.

Covers:
- score_opportunities excludes below-threshold records
- missing email surfaces a warning flag without fabricating contact
- vague income text reduces confidence (score impact)
- filter_qualified returns only passing records
- generate_draft contains no fabricated achievements
"""

from __future__ import annotations

import pytest

from commission_crowd_agent.canonical import CanonicalOpportunity
from commission_crowd_agent.mvp_pipeline import (
    filter_qualified,
    generate_application_draft,
    score_opportunities,
)


@pytest.fixture
def _base_opp() -> CanonicalOpportunity:
    return CanonicalOpportunity(
        source_opportunity_id="OPP-1",
        title="Test Opportunity",
        commission_text="20% recurring",
        commission_percent=20.0,
        territory="North America",
        territory_details="North America",
        contact_email="contact@example.com",
        completeness=80,
        view_count=100,
        application_count=10,
        residual_terms=True,
        deal_value_usd=75000,
    )


class TestScoreThreshold:
    def test_score_excludes_below_threshold(self, _base_opp: CanonicalOpportunity) -> None:
        # 15% is below default 20% threshold
        low = _base_opp.model_copy(update={"commission_percent": 15.0})
        scored = score_opportunities([low], min_commission_pct=20.0)
        assert len(scored) == 1
        assert scored[0]["passes_threshold"] is False
        assert scored[0]["recommended"] == "reject_below_threshold"

    def test_score_includes_at_threshold(self, _base_opp: CanonicalOpportunity) -> None:
        at = _base_opp.model_copy(update={"commission_percent": 20.0})
        scored = score_opportunities([at], min_commission_pct=20.0)
        assert scored[0]["passes_threshold"] is True
        assert scored[0]["recommended"] != "reject_below_threshold"

    def test_score_warns_missing_email(self, _base_opp: CanonicalOpportunity) -> None:
        no_email = _base_opp.model_copy(
            update={"contact_email": None, "data_quality_flags": ["missing_contact_email"]}
        )
        scored = score_opportunities([no_email])
        flags = scored[0]["flags"]
        assert "missing_contact_email" in flags
        # Score should still compute, not crash
        assert isinstance(scored[0]["score"], int)

    def test_score_reduces_confidence_for_vague_income(
        self, _base_opp: CanonicalOpportunity
    ) -> None:
        vague = _base_opp.model_copy(
            update={"commission_text": "unlimited potential", "commission_percent": None}
        )
        scored = score_opportunities([vague])
        # unclear commission means lower points in commission category
        reasons = scored[0]["reasons"]
        assert any("unclear" in r.lower() for r in reasons)
        assert scored[0]["passes_threshold"] is False


class TestFilterQualified:
    def test_filter_qualified_returns_only_passing(self, _base_opp: CanonicalOpportunity) -> None:
        good = _base_opp.model_copy(update={"commission_percent": 25.0, "deal_value_usd": 100000})
        bad = _base_opp.model_copy(update={"commission_percent": 15.0, "deal_value_usd": 100000})
        scored = score_opportunities([good, bad], min_commission_pct=20.0)
        qualified = filter_qualified(scored)
        assert len(qualified) == 1
        assert qualified[0]["opportunity"].source_opportunity_id == "OPP-1"
        assert qualified[0]["passes_threshold"] is True


class TestGenerateDraft:
    def test_generate_draft_no_fabricated_achievements(
        self, _base_opp: CanonicalOpportunity
    ) -> None:
        class FakeSettings:
            operator_name = "Operator Name"
            operator_email = "op@example.com"
            operator_phone = ""

        draft = generate_application_draft(_base_opp, FakeSettings())
        body = draft["body"]
        # Should not contain made-up metrics or awards
        assert "award" not in body.lower()
        assert "years of experience" not in body.lower()
        assert "million" not in body.lower()
        assert "closed" not in body.lower() or "closed_won" not in body.lower()
        # Should contain real data references
        assert _base_opp.title in draft["subject"]
        assert "20%" in body or "recurring" in body

    def test_generate_draft_asks_questions_for_unknowns(
        self, _base_opp: CanonicalOpportunity
    ) -> None:
        incomplete = _base_opp.model_copy(
            update={
                "commission_percent": None,
                "residual_terms": False,
                "contact_email": None,
                "deal_value_usd": None,
            }
        )

        class FakeSettings:
            operator_name = "Operator Name"
            operator_email = ""
            operator_phone = ""

        draft = generate_application_draft(incomplete, FakeSettings())
        body = draft["body"]
        assert "exact commission percentage" in body.lower()
        assert "residual" in body.lower()
        assert "best direct contact" in body.lower()
        assert "deal size" in body.lower() or "acv" in body.lower()

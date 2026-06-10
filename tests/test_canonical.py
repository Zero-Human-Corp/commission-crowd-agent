"""Tests for CanonicalOpportunity model.

Covers:
- Deterministic mapping from CommissionCrowd API dict
- Quality flags (missing email, phone, commission)
- Null company name preservation (no synthetic injection)
- Payload hash determinism and sensitivity
- Sample mode rejection of non-sample mode
- Commission percent parsing from decimal and textual forms
"""

from __future__ import annotations

from typing import Any

import pytest

from commission_crowd_agent.canonical import CanonicalOpportunity

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def sample_api_raw() -> dict[str, Any]:
    """A realistic CommissionCrowd API dict."""
    return {
        "id": 30130,
        "ref": "REF-30130",
        "name": "Cybersecurity SaaS — North America",
        "latest_slug": "cybersecurity-saas-na",
        "description": "<p>Leading cybersecurity platform.</p>",
        "commission": "20% recurring on annual contracts ($5,000–$25,000 ACV)",
        "commission_pc": "22.5",
        "territory_details": "North America",
        "global_territory": False,
        "active": True,
        "view_count": 120,
        "application_count": 8,
        "agent_count": 3,
        "invitation_count": 2,
        "completeness": 85,
        "email": "apply@cybersec.example.com",
        "phone": "+1-555-0199",
        "company": 42,
        "countries": [1, 2],
        "world_regions": [],
        "industries": [10],
        "target_industries": [],
        "products": [],
        "short_summary": "Top-rated cybersecurity SaaS.",
        "usp": "AI-driven threat detection.",
        "payment_terms": "Net 30",
    }


# ------------------------------------------------------------------
# from_commissioncrowd_api
# ------------------------------------------------------------------

class TestFromCommissionCrowdApi:
    def test_from_commissioncrowd_api_maps_fields(self, sample_api_raw: dict[str, Any]) -> None:
        opp = CanonicalOpportunity.from_commissioncrowd_api(sample_api_raw)
        assert opp.source == "commissioncrowd"
        assert opp.source_opportunity_id == "30130"
        assert opp.ref == "REF-30130"
        assert opp.title == "Cybersecurity SaaS — North America"
        assert opp.slug == "cybersecurity-saas-na"
        assert opp.commission_text == "20% recurring on annual contracts ($5,000–$25,000 ACV)"
        assert opp.commission_percent == 22.5
        assert opp.territory == "North America"
        assert opp.active is True
        assert opp.view_count == 120
        assert opp.application_count == 8
        assert opp.agent_count == 3
        assert opp.invitation_count == 2
        assert opp.completeness == 85
        assert opp.contact_email == "apply@cybersec.example.com"
        assert opp.contact_phone == "+1-555-0199"
        assert opp.company_id == 42
        assert opp.countries == [1, 2]
        assert opp.world_regions == []
        assert opp.industries == [10]
        assert opp.description == "Leading cybersecurity platform."
        assert opp.short_summary == "Top-rated cybersecurity SaaS."
        assert opp.usp == "AI-driven threat detection."
        assert opp.payment_terms == "Net 30"

    def test_missing_email_creates_flag(self, sample_api_raw: dict[str, Any]) -> None:
        raw = dict(sample_api_raw)
        raw["email"] = ""
        opp = CanonicalOpportunity.from_commissioncrowd_api(raw)
        assert "missing_contact_email" in opp.data_quality_flags

    def test_preserve_null_company_name(self, sample_api_raw: dict[str, Any]) -> None:
        opp = CanonicalOpportunity.from_commissioncrowd_api(sample_api_raw)
        # CommissionCrowd returns company as int FK; we must not fabricate a name
        assert opp.company_name is None

    def test_html_stripping(self, sample_api_raw: dict[str, Any]) -> None:
        opp = CanonicalOpportunity.from_commissioncrowd_api(sample_api_raw)
        assert "<" not in opp.description
        assert ">" not in opp.description


# ------------------------------------------------------------------
# payload_hash
# ------------------------------------------------------------------

class TestPayloadHash:
    def test_payload_hash_deterministic(self, sample_api_raw: dict[str, Any]) -> None:
        opp = CanonicalOpportunity.from_commissioncrowd_api(sample_api_raw)
        h1 = opp.payload_hash("apply", "CommissionCrowd", "Hello")
        h2 = opp.payload_hash("apply", "CommissionCrowd", "Hello")
        assert h1 == h2
        # SHA-256 hex string
        assert len(h1) == 64
        int(h1, 16)  # valid hex

    def test_payload_hash_changes_with_body(self, sample_api_raw: dict[str, Any]) -> None:
        opp = CanonicalOpportunity.from_commissioncrowd_api(sample_api_raw)
        h1 = opp.payload_hash("apply", "CommissionCrowd", "Hello")
        h2 = opp.payload_hash("apply", "CommissionCrowd", "World")
        assert h1 != h2

    def test_payload_hash_includes_action_and_target(self, sample_api_raw: dict[str, Any]) -> None:
        opp = CanonicalOpportunity.from_commissioncrowd_api(sample_api_raw)
        h1 = opp.payload_hash("apply", "CommissionCrowd", "Body")
        h2 = opp.payload_hash("review", "CommissionCrowd", "Body")
        h3 = opp.payload_hash("apply", "Other", "Body")
        assert h1 != h2
        assert h1 != h3


# ------------------------------------------------------------------
# sample_opportunities
# ------------------------------------------------------------------

class TestSampleOpportunities:
    def test_sample_mode_explicit_only(self) -> None:
        with pytest.raises(ValueError, match="sample"):
            CanonicalOpportunity.sample_opportunities(mode="live")

    def test_sample_returns_expected_shape(self) -> None:
        opps = CanonicalOpportunity.sample_opportunities(mode="sample", limit=1)
        assert len(opps) == 1
        assert opps[0].source == "sample"
        assert opps[0].source_opportunity_id.startswith("SAMPLE-")


# ------------------------------------------------------------------
# Commission percent parsing via helper
# ------------------------------------------------------------------

class TestCommissionPercentParsing:
    def test_commission_percent_parsing_decimal(self) -> None:
        raw: dict[str, Any] = {"commission_pc": "22.5", "commission": "", "name": ""}
        opp = CanonicalOpportunity.from_commissioncrowd_api(raw)
        assert opp.commission_percent == 22.5

    def test_commission_percent_parsing_textual(self) -> None:
        raw: dict[str, Any] = {"commission_pc": "", "commission": "20 percent recurring", "name": ""}
        opp = CanonicalOpportunity.from_commissioncrowd_api(raw)
        assert opp.commission_percent == 20.0

    def test_commission_percent_from_title_percent_sign(self) -> None:
        raw: dict[str, Any] = {"commission_pc": "", "commission": "", "name": "15% lifetime deals"}
        opp = CanonicalOpportunity.from_commissioncrowd_api(raw)
        assert opp.commission_percent == 15.0

    def test_commission_percent_none_when_unclear(self) -> None:
        raw: dict[str, Any] = {"commission_pc": "", "commission": "generous", "name": ""}
        opp = CanonicalOpportunity.from_commissioncrowd_api(raw)
        assert opp.commission_percent is None
        assert "unclear_commission_rate" in opp.data_quality_flags

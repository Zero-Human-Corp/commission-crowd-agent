"""Tests for AutonomousProspector.

All external calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from commission_crowd_agent.autonomous_prospector import CommissionCrowdProspector
from commission_crowd_agent.domain import OpportunityStage


@pytest.fixture
def prospector():
    return CommissionCrowdProspector(api_key="FAKE", dry_run=True)


class TestScoringHelpers:
    def test_extract_commission_pct(self, prospector: CommissionCrowdProspector) -> None:
        assert prospector._extract_commission_pct("20% commission") == 20
        assert prospector._extract_commission_pct("Up to 30%") == 30
        assert prospector._extract_commission_pct("flat fee") == 0

    def test_extract_deal_value(self, prospector: CommissionCrowdProspector) -> None:
        assert prospector._extract_deal_value("$2,500 per deal") == 2500
        assert prospector._extract_deal_value("$7,500–$15,000") == 15000
        assert prospector._extract_deal_value("$500") == 500
        assert prospector._extract_deal_value("no money") == 0

    def test_has_short_cycle(self, prospector: CommissionCrowdProspector) -> None:
        assert prospector._has_short_cycle("Short sales cycle") is True
        assert prospector._has_short_cycle("warm leads") is True
        assert prospector._has_short_cycle("12 months onboarding") is False

    def test_has_email_phone(self, prospector: CommissionCrowdProspector) -> None:
        assert prospector._has_email_phone("email or phone") is True
        assert prospector._has_email_phone("only LinkedIn") is False


class TestRunCycle:
    def test_dry_run_no_writes(self, prospector: CommissionCrowdProspector) -> None:
        result = prospector.run_cycle()
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["total_discovered"] == 0

    def test_mocked_list(self) -> None:
        prospector = CommissionCrowdProspector(api_key="FAKE", dry_run=True)

        class FakeModel:
            def model_dump(self):
                return {
                    "id": 1,
                    "title": "20% Commission | AI Product | Email/Phone",
                    "slug": "ai-product",
                    "description": "High deal value, short sales cycle, email preferred",
                    "commission": "20%",
                    "url": "https://example.com/opp/1",
                    "industry": "AI",
                    "status": "active",
                    "created_at": None,
                }

        fake_model = FakeModel()

        class FakeAdapter:
            def list_opportunities(self, *, page=1, limit=20):
                return {
                    "ok": True,
                    "opportunities": [fake_model],
                    "using_fallback": False,
                    "raw_listings": [],
                }

        prospector.adapter = FakeAdapter()  # type: ignore[assignment]

        result = prospector.run_cycle()
        assert result["ok"] is True
        assert result["scored_and_qualified"] == 1
        assert result["records"][0]["comm_pct"] == 20

    def test_mocked_fallback(self) -> None:
        prospector = CommissionCrowdProspector(api_key="FAKE", dry_run=True)

        class FakeAdapterFallback:
            def list_opportunities(self, *, page=1, limit=20):
                return {
                    "ok": True,
                    "opportunities": [],
                    "using_fallback": True,
                    "raw_listings": [
                        {"title": "$5,000 Per Deal | Short Cycle | Phone Sales", "url": "x"}
                    ],
                }

        prospector.adapter = FakeAdapterFallback()  # type: ignore[assignment]
        result = prospector.run_cycle()
        assert result["ok"] is True
        assert result["scored_and_qualified"] == 1

    def test_crm_pipeline_calls(self) -> None:
        prospector = CommissionCrowdProspector(api_key="FAKE", dry_run=False)

        class FakeModel:
            def model_dump(self):
                return {
                    "id": 1,
                    "title": "20% Commission | AI | Fast Cycle | Email",
                    "slug": "ai",
                    "description": "email outreach preferred",
                    "commission": "",
                    "url": "https://x.com/1",
                    "industry": "AI",
                    "status": "active",
                    "created_at": None,
                }

        class FakeAdapter:
            def list_opportunities(self, *, page=1, limit=20):
                return {
                    "ok": True,
                    "opportunities": [FakeModel()],
                    "using_fallback": False,
                    "raw_listings": [],
                }

        prospector.adapter = FakeAdapter()  # type: ignore[assignment]
        prospector.dry_run = False

        mock_crm = MagicMock()
        result = prospector.run_cycle(crm_pipeline=mock_crm, write=True)
        assert result["dry_run"] is False
        mock_crm.add_lead.assert_called_once()

"""Integration-style tests for live-shadow mode.

Uses a mocked CommissionCrowd API response matching real schema.
Verifies zero writes, no synthetic contamination, lineage, threshold
rejection, and report file creation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from commission_crowd_agent.mvp_pipeline import (
    fetch_live_opportunities,
    filter_qualified,
    generate_application_draft,
    run_live_shadow,
    score_opportunities,
)
from commission_crowd_agent.mvp_reports import (
    build_stage_lineage,
    build_telegram_digest,
    write_live_shadow_report,
)


@pytest.fixture
def mock_api_response() -> dict[str, Any]:
    """A mocked CommissionCrowd list_opportunities response with two items."""
    return {
        "ok": True,
        "status": 200,
        "error": None,
        "data": {
            "items": [
                {
                    "id": 9001,
                    "ref": "REF-9001",
                    "name": "SaaS Analytics — UK",
                    "latest_slug": "saas-analytics-uk",
                    "description": "<p>Analytics platform.</p>",
                    "commission": "22% on first year revenue",
                    "commission_pc": "22.00",
                    "territory_details": "UK & Ireland",
                    "global_territory": False,
                    "active": True,
                    "view_count": 150,
                    "application_count": 12,
                    "agent_count": 4,
                    "invitation_count": 3,
                    "completeness": 88,
                    "email": "sales@saas.example.com",
                    "phone": "+44-555-0100",
                    "company": 99,
                    "countries": [826],
                    "world_regions": [],
                    "industries": [5],
                    "target_industries": [],
                    "products": [],
                    "short_summary": "AI analytics SaaS.",
                    "usp": "Real-time dashboards.",
                    "payment_terms": "Net 15",
                },
                {
                    "id": 9002,
                    "ref": "REF-9002",
                    "name": "Legacy Hardware — Global",
                    "latest_slug": "legacy-hardware-global",
                    "description": "<p>Old but reliable.</p>",
                    "commission": "15% flat",
                    "commission_pc": "15.00",
                    "territory_details": "Global",
                    "global_territory": True,
                    "active": True,
                    "view_count": 30,
                    "application_count": 2,
                    "agent_count": 1,
                    "invitation_count": 0,
                    "completeness": 45,
                    "email": "",
                    "phone": "",
                    "company": 100,
                    "countries": [],
                    "world_regions": [1],
                    "industries": [20],
                    "target_industries": [],
                    "products": [],
                    "short_summary": "Hardware reseller.",
                    "usp": "Long warranty.",
                    "payment_terms": "Net 60",
                },
            ],
            "next": None,
            "count": 2,
        },
    }


class TestLiveShadowZeroWrites:
    @patch("commission_crowd_agent.mvp_pipeline.CommissionCrowdApiAdapter")
    def test_live_shadow_zero_writes(
        self, mock_adapter_cls: MagicMock, mock_api_response: dict[str, Any]
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_opportunities.return_value = mock_api_response
        mock_adapter_cls.return_value = mock_adapter

        result = run_live_shadow(limit=2, min_commission=20.0)

        assert result["ok"] is True
        assert result["mode"] == "live-shadow"
        assert result["sheets_written"] == 0
        assert result["approvals_created"] == 0
        assert result["emails_sent"] == 0
        assert result["calendars_created"] == 0

    @patch("commission_crowd_agent.mvp_pipeline.CommissionCrowdApiAdapter")
    def test_live_shadow_total_counts(
        self, mock_adapter_cls: MagicMock, mock_api_response: dict[str, Any]
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_opportunities.return_value = mock_api_response
        mock_adapter_cls.return_value = mock_adapter

        result = run_live_shadow(limit=2, min_commission=20.0)
        assert result["total_fetched"] == 2
        assert result["scored"] == 2
        # One qualifies (22%), one rejects (15%)
        assert result["qualified"] == 1
        assert result["rejected"] == 1


class TestLiveShadowNoSyntheticContamination:
    @patch("commission_crowd_agent.mvp_pipeline.CommissionCrowdApiAdapter")
    def test_live_shadow_no_synthetic_contamination(
        self, mock_adapter_cls: MagicMock, mock_api_response: dict[str, Any]
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_opportunities.return_value = mock_api_response
        mock_adapter_cls.return_value = mock_adapter

        result = run_live_shadow(limit=2, min_commission=20.0)
        assert result["ok"] is True
        # Ensure none of the fixture sample IDs leaked in
        all_ids = result["source_ids"]
        for sid in all_ids:
            assert "SAMPLE" not in sid
        for draft in result.get("drafts", []):
            assert "SAMPLE" not in draft["opportunity_id"]

    @patch("commission_crowd_agent.mvp_pipeline.CommissionCrowdApiAdapter")
    def test_fixture_names_absent(
        self, mock_adapter_cls: MagicMock, mock_api_response: dict[str, Any]
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_opportunities.return_value = mock_api_response
        mock_adapter_cls.return_value = mock_adapter

        result = run_live_shadow(limit=2, min_commission=20.0)
        synthetic_names = {
            "SecureFlow Technologies",
            "IntellectAI",
            "NimbusWatch",
            "PeopleFirst",
        }
        for draft in result.get("drafts", []):
            title = draft.get("title", "")
            for name in synthetic_names:
                assert name not in title


class TestLiveShadowLineage:
    @patch("commission_crowd_agent.mvp_pipeline.CommissionCrowdApiAdapter")
    def test_live_shadow_lineage_traces_to_source(
        self, mock_adapter_cls: MagicMock, mock_api_response: dict[str, Any]
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_opportunities.return_value = mock_api_response
        mock_adapter_cls.return_value = mock_adapter

        result = run_live_shadow(limit=2, min_commission=20.0)
        source_ids = set(result["source_ids"])
        for draft in result.get("drafts", []):
            assert draft["opportunity_id"] in source_ids

    @patch("commission_crowd_agent.mvp_pipeline.CommissionCrowdApiAdapter")
    def test_lineage_helper_matches(
        self, mock_adapter_cls: MagicMock, mock_api_response: dict[str, Any]
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_opportunities.return_value = mock_api_response
        mock_adapter_cls.return_value = mock_adapter

        opps = fetch_live_opportunities(limit=2)
        scored = score_opportunities(opps, min_commission_pct=20.0)
        qualified = filter_qualified(scored)
        drafts: list[dict[str, Any]] = []
        for q in qualified[:2]:
            draft = generate_application_draft(q["opportunity"], object())
            payload_hash = q["opportunity"].payload_hash(
                action_type="apply_to_principal",
                target="CommissionCrowd",
                body=draft["body"],
            )
            drafts.append(
                {
                    "opportunity_id": q["opportunity"].source_opportunity_id,
                    "draft": draft,
                    "payload_hash": payload_hash,
                }
            )
        lineage = build_stage_lineage(opps, scored, qualified, drafts)
        assert lineage["lineage_valid"] is True
        assert lineage["counts"]["source"] == 2
        assert lineage["counts"]["scored"] == 2
        assert lineage["counts"]["qualified"] == 1
        assert lineage["counts"]["drafts"] == 1


class TestLiveShadowRejectsBelowThreshold:
    @patch("commission_crowd_agent.mvp_pipeline.CommissionCrowdApiAdapter")
    def test_live_shadow_rejects_below_threshold(
        self, mock_adapter_cls: MagicMock, mock_api_response: dict[str, Any]
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_opportunities.return_value = mock_api_response
        mock_adapter_cls.return_value = mock_adapter

        result = run_live_shadow(limit=2, min_commission=20.0)
        assert result["ok"] is True
        # 15% opportunity is excluded
        qualified_ids = {d["opportunity_id"] for d in result.get("drafts", [])}
        assert "9002" not in qualified_ids
        assert "9001" in qualified_ids


class TestLiveShadowReportFiles:
    @patch("commission_crowd_agent.mvp_pipeline.CommissionCrowdApiAdapter")
    def test_live_shadow_report_files_created(
        self, mock_adapter_cls: MagicMock, mock_api_response: dict[str, Any], tmp_path: Any
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_opportunities.return_value = mock_api_response
        mock_adapter_cls.return_value = mock_adapter

        result = run_live_shadow(limit=2, min_commission=20.0)
        path = write_live_shadow_report(result, run_id="RUN-001", reports_dir=tmp_path)
        assert path.exists()
        data = path.read_text(encoding="utf-8")
        assert "live_shadow" in data
        assert "RUN-001" in data
        digest = build_telegram_digest(result)
        assert "Digest" in digest
        assert "Fetched: 2" in digest

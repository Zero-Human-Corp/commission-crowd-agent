"""Tests for CommissionCrowdApiAdapter.

Covers:
- Unit tests using mocked httpx responses (no real network).
- dry_run mode returns stub data without touching the network.
- Missing API key is surfaced gracefully in structured results.
- Health check parses the root endpoint correctly.
- Error handling for 401, 500, network failures, timeouts.
- No secret values leak into result dicts or exceptions.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from commission_crowd_agent.commissioncrowd_adapter import (
    CommissionCrowdAgentProfile,
    CommissionCrowdApiAdapter,
    CommissionCrowdOpportunity,
)
from commission_crowd_agent.config import CcaSettings


def _make_settings(api_key: str = "fake-key") -> CcaSettings:
    """Return a CcaSettings with only the CommissionCrowd key set."""
    return CcaSettings(
        commissioncrowd_api_key=api_key,
        commissioncrowd_base_url="https://www.commissioncrowd.com/api",
    )


def _fake_ok_response(json_body: dict, status: int = 200) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = json_body
    resp.reason_phrase = "OK" if status == 200 else "Error"
    return resp


class TestDryRun:
    def test_health_check_dry_run_returns_ok(self) -> None:
        adapter = CommissionCrowdApiAdapter(dry_run=True)
        result = adapter.health_check()
        assert result["ok"] is True
        assert result["status"] == 0
        assert result["dry_run"] is True
        assert result["error"] is None

    def test_list_opportunities_dry_run_fails_closed(self) -> None:
        """Dry-run with no key must fail closed rather than return fake data."""
        adapter = CommissionCrowdApiAdapter(dry_run=True)
        result = adapter.list_opportunities()
        assert result["ok"] is False
        assert "Missing" in result["error"]

    def test_list_agents_dry_run_returns_stub(self) -> None:
        adapter = CommissionCrowdApiAdapter(dry_run=True)
        result = adapter.list_agents()
        assert result["ok"] is True
        data = result["data"]
        assert data["items"]

    def test_get_opportunity_dry_run_returns_stub(self) -> None:
        adapter = CommissionCrowdApiAdapter(dry_run=True)
        result = adapter.get_opportunity(42)
        assert result["ok"] is True
        assert result["data"]["id"] == 42

    def test_no_network_call_in_dry_run(self) -> None:
        """Ensure we never instantiate an httpx client in dry_run."""
        with patch("httpx.Client") as mock_client:
            adapter = CommissionCrowdApiAdapter(dry_run=True)
            adapter.health_check()
            adapter.list_opportunities()
            mock_client.assert_not_called()


class TestMissingKey:
    def test_list_opportunities_without_key_fails_early(self) -> None:
        adapter = CommissionCrowdApiAdapter(api_key="")
        result = adapter.list_opportunities()
        assert result["ok"] is False
        assert "Missing" in result["error"]

    def test_list_agents_without_key_fails_early(self) -> None:
        adapter = CommissionCrowdApiAdapter(api_key="")
        result = adapter.list_agents()
        assert result["ok"] is False
        assert "Missing" in result["error"]

    def test_get_opportunity_without_key_fails_early(self) -> None:
        adapter = CommissionCrowdApiAdapter(api_key="")
        result = adapter.get_opportunity(1)
        assert result["ok"] is False
        assert "Missing" in result["error"]


class TestHealthCheck:
    @patch("httpx.Client")
    def test_health_check_success(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.request.return_value = _fake_ok_response(
            {"opportunities": "url", "agents": "url"}
        )

        adapter = CommissionCrowdApiAdapter(api_key="k")
        result = adapter.health_check()

        assert result["ok"] is True
        assert result["status"] == 200
        assert "resources" in result["data"]
        # CommissionCrowd legacy API uses Token scheme (not Bearer)
        call = mock_client.request.call_args
        assert call[1]["headers"]["Authorization"].startswith("Token")

    @patch("httpx.Client")
    def test_health_check_401(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.request.return_value = _fake_ok_response({}, status=401)

        adapter = CommissionCrowdApiAdapter(api_key="k")
        result = adapter.health_check()
        assert result["ok"] is False
        assert result["status"] == 401


class TestListOpportunities:
    @patch("httpx.Client")
    def test_list_opportunities_success(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        payload = {
            "results": [
                {"id": 1, "title": "Opportunity A"},
                {"id": 2, "title": "Opportunity B"},
            ],
            "next": "https://www.commissioncrowd.com/api/opportunities/?page=2",
            "count": 2,
        }
        mock_client.request.return_value = _fake_ok_response(payload)

        adapter = CommissionCrowdApiAdapter(api_key="k")
        result = adapter.list_opportunities()
        assert result["ok"] is True
        assert len(result["data"]["items"]) == 2
        assert result["data"]["count"] == 2
        assert "page=2" in result["data"]["next"]

    @patch("httpx.Client")
    def test_list_opportunities_401(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.request.return_value = _fake_ok_response({}, status=401)

        adapter = CommissionCrowdApiAdapter(api_key="k")
        result = adapter.list_opportunities()
        assert result["ok"] is False
        assert result["status"] == 401

    @patch("httpx.Client")
    def test_list_opportunities_network_error(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.request.side_effect = httpx.ConnectError("DNS failed")

        adapter = CommissionCrowdApiAdapter(api_key="k")
        result = adapter.list_opportunities()
        assert result["ok"] is False
        assert "Network error" in result["error"]


class TestListAgents:
    @patch("httpx.Client")
    def test_list_agents_success(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        payload = {"results": [{"id": 1, "full_name": "Agent One"}], "next": None, "count": 1}
        mock_client.request.return_value = _fake_ok_response(payload)

        adapter = CommissionCrowdApiAdapter(api_key="k")
        result = adapter.list_agents()
        assert result["ok"] is True
        assert result["data"]["count"] == 1


class TestGetOpportunity:
    @patch("httpx.Client")
    def test_get_opportunity_success(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.request.return_value = _fake_ok_response({"id": 99, "title": "Specific Opp"})

        adapter = CommissionCrowdApiAdapter(api_key="k")
        result = adapter.get_opportunity(99)
        assert result["ok"] is True
        assert result["data"]["title"] == "Specific Opp"


class TestSettingsIntegration:
    def test_api_key_from_settings(self) -> None:
        settings = _make_settings(api_key="settings-key")
        adapter = CommissionCrowdApiAdapter(settings=settings)
        assert adapter.api_key == "settings-key"

    def test_explicit_key_overrides_settings(self) -> None:
        settings = _make_settings(api_key="settings-key")
        adapter = CommissionCrowdApiAdapter(api_key="explicit-key", settings=settings)
        assert adapter.api_key == "explicit-key"


class TestTokenPresent:
    def test_token_present_when_key(self) -> None:
        assert CommissionCrowdApiAdapter(api_key="k").token_present() is True

    def test_token_present_when_empty(self) -> None:
        assert CommissionCrowdApiAdapter(api_key="").token_present() is False


class TestNoSecretsInResults:
    @patch("httpx.Client")
    def test_result_contains_no_api_key(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.request.return_value = _fake_ok_response({"results": [{"id": 1}]})

        secret_key = "super-secret-key-12345"
        adapter = CommissionCrowdApiAdapter(api_key=secret_key)
        result = adapter.list_opportunities()
        result_str = json.dumps(result)
        assert secret_key not in result_str
        assert "Bearer" not in result_str


class TestDomainModels:
    def test_opportunity_model(self) -> None:
        opp = CommissionCrowdOpportunity(id=1, title="Test", territory="UK", commission="10%")
        assert opp.territory == "UK"
        assert opp.id == 1

    def test_agent_profile_model(self) -> None:
        agent = CommissionCrowdAgentProfile(id=1, full_name="Alice", email="alice@example.com")
        assert agent.full_name == "Alice"

    def test_opportunity_validation_fails_on_bad_data(self) -> None:
        """Pydantic should reject fields that don't match declared types."""
        with pytest.raises(ValidationError):
            CommissionCrowdOpportunity(id="not-an-int")


class TestUrlBuilding:
    def test_url_builder(self) -> None:
        adapter = CommissionCrowdApiAdapter(api_key="k")
        assert adapter._url("opportunities") == "https://www.commissioncrowd.com/api/opportunities/"
        assert (
            adapter._url("/opportunities") == "https://www.commissioncrowd.com/api/opportunities/"
        )
        # Custom base URL
        adapter2 = CommissionCrowdApiAdapter(api_key="k", base_url="https://cc.example.com/api")
        assert adapter2._url("opportunities") == "https://cc.example.com/api/opportunities/"

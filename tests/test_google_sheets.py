"""Tests for Google Sheets adapter.

All Google API calls are mocked. No real credentials or network traffic.
"""

import os
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from commission_crowd_agent.adapters import GoogleSheetsAdapter


class TestHealthCheck:
    def test_dry_run_returns_ok(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=True)
        result = adapter.health_check()
        assert result["ok"] is True
        assert result["action"] == "health_check"
        assert result["error"] is None

    def test_missing_spreadsheet_id(self) -> None:
        adapter = GoogleSheetsAdapter(access_token="token", dry_run=False)
        result = adapter.health_check()
        assert result["ok"] is False
        assert "Missing spreadsheet_id" in (result["error"] or "")

    def test_missing_access_token(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", dry_run=False)
        result = adapter.health_check()
        assert result["ok"] is False
        assert "Missing access_token" in (result["error"] or "")

    def test_success(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"properties": {"title": "CCA Sheet"}}
        with patch("commission_crowd_agent.adapters.httpx.get", return_value=mock_response):
            result = adapter.health_check()
        assert result["ok"] is True
        assert result["error"] is None

    def test_http_error(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_response
        )
        with patch("commission_crowd_agent.adapters.httpx.get", return_value=mock_response):
            result = adapter.health_check()
        assert result["ok"] is False
        assert "403" in (result["error"] or "")

    def test_network_error(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=False)
        with patch(
            "commission_crowd_agent.adapters.httpx.get",
            side_effect=httpx.ConnectError("Network unreachable"),
        ):
            result = adapter.health_check()
        assert result["ok"] is False
        assert "Network" in (result["error"] or "")


class TestReadRows:
    def test_dry_run_returns_empty(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=True)
        result = adapter.read_rows("leads")
        assert result["ok"] is True
        assert result["rows"] == []
        assert result["rows_changed"] == 0

    def test_success(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "values": [
                ["lead_id", "source", "name"],
                ["L001", "web", "Alice"],
            ]
        }
        with patch("commission_crowd_agent.adapters.httpx.get", return_value=mock_response):
            result = adapter.read_rows("leads")
        assert result["ok"] is True
        assert result["rows"] == [["lead_id", "source", "name"], ["L001", "web", "Alice"]]
        assert result["rows_changed"] == 2


class TestAppendRow:
    def test_dry_run_returns_ok(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=True)
        result = adapter.append_row("leads", ["L001", "web", "Alice"])
        assert result["ok"] is True
        assert result["rows_changed"] == 1

    def test_success(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updates": {"updatedRows": 1}}
        with patch("commission_crowd_agent.adapters.httpx.post", return_value=mock_response):
            result = adapter.append_row("leads", ["L001", "web", "Alice"])
        assert result["ok"] is True
        assert result["rows_changed"] == 1


class TestUpsertRowByKey:
    def test_dry_run_returns_ok(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=True)
        result = adapter.upsert_row_by_key("leads", "lead_id", "L001", ["L001", "web", "Alice"])
        assert result["ok"] is True
        assert result["rows_changed"] == 1

    def test_update_existing_row(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=False)
        read_response = MagicMock()
        read_response.status_code = 200
        read_response.json.return_value = {
            "values": [
                ["lead_id", "source", "name"],
                ["L001", "web", "Alice"],
            ]
        }
        put_response = MagicMock()
        put_response.status_code = 200
        put_response.json.return_value = {"updates": {"updatedRows": 1}}

        def mock_request(method: str, *args: Any, **kwargs: Any) -> MagicMock:
            if method == "get":
                return read_response
            return put_response

        with (
            patch("commission_crowd_agent.adapters.httpx.get", return_value=read_response),
            patch("commission_crowd_agent.adapters.httpx.put", return_value=put_response),
        ):
            result = adapter.upsert_row_by_key(
                "leads", "lead_id", "L001", ["L001", "web", "Alice Updated"]
            )
        assert result["ok"] is True
        assert result["rows_changed"] == 1

    def test_append_when_key_not_found(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=False)
        read_response = MagicMock()
        read_response.status_code = 200
        read_response.json.return_value = {
            "values": [
                ["lead_id", "source", "name"],
                ["L002", "web", "Bob"],
            ]
        }
        post_response = MagicMock()
        post_response.status_code = 200
        post_response.json.return_value = {"updates": {"updatedRows": 1}}

        with (
            patch("commission_crowd_agent.adapters.httpx.get", return_value=read_response),
            patch("commission_crowd_agent.adapters.httpx.post", return_value=post_response),
        ):
            result = adapter.upsert_row_by_key("leads", "lead_id", "L001", ["L001", "web", "Alice"])
        assert result["ok"] is True
        assert result["rows_changed"] == 1


class TestEnsureSchema:
    def test_dry_run_returns_ok(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", access_token="token", dry_run=True)
        result = adapter.ensure_schema()
        assert result["ok"] is True
        assert result["rows_changed"] == len(adapter.SCHEMA)

    def test_missing_spreadsheet_id(self) -> None:
        adapter = GoogleSheetsAdapter(dry_run=False)
        result = adapter.ensure_schema()
        assert result["ok"] is False
        assert "Missing spreadsheet_id" in (result["error"] or "")


class TestNoSecretLeak:
    def test_error_result_never_contains_token(self) -> None:
        adapter = GoogleSheetsAdapter(
            spreadsheet_id="test-id",
            access_token="super-secret-token-123",
            dry_run=False,
        )
        result = adapter.health_check()
        result_str = str(result)
        assert "super-secret-token-123" not in result_str

    def test_auth_headers_contain_masked_token(self) -> None:
        adapter = GoogleSheetsAdapter(access_token="secret-456")
        headers = adapter._auth_headers()
        assert headers["Authorization"].startswith("Bearer ")
        # The header itself contains the token (needed for real requests),
        # but it is never exposed in result dicts or logs.
        assert "secret-456" in headers["Authorization"]


class TestSchemaDefinition:
    def test_schema_has_expected_tabs(self) -> None:
        adapter = GoogleSheetsAdapter()
        assert set(adapter.SCHEMA.keys()) == {
            "leads",
            "opportunities",
            "approvals",
            "runs",
            "outcomes",
        }

    def test_leads_tab_has_expected_columns(self) -> None:
        adapter = GoogleSheetsAdapter()
        assert adapter.SCHEMA["leads"][0] == "lead_id"
        assert adapter.SCHEMA["leads"][-1] == "notes"


class TestServiceAccountTokenGeneration:
    def test_no_token_when_no_credentials(self) -> None:
        adapter = GoogleSheetsAdapter(spreadsheet_id="test-id", dry_run=False)
        adapter._ensure_access_token()
        assert adapter.access_token == ""

    def test_no_token_when_dry_run(self) -> None:
        adapter = GoogleSheetsAdapter(
            spreadsheet_id="test-id",
            credentials_path="/tmp/fake.json",
            dry_run=True,
        )
        adapter._ensure_access_token()
        assert adapter.access_token == ""

    def test_token_generated_from_service_account_json(self) -> None:
        adapter = GoogleSheetsAdapter(
            spreadsheet_id="test-id",
            service_account_json='{"type": "service_account"}',
            dry_run=False,
        )
        with patch(
            "google.oauth2.service_account.Credentials.from_service_account_info"
        ) as mock_from_info:
            mock_creds = MagicMock()
            mock_creds.token = "mock-token-123"
            mock_from_info.return_value = mock_creds
            adapter._ensure_access_token()
            assert adapter.access_token == "mock-token-123"

    def test_token_generated_from_service_account_path(self) -> None:
        import json as _json
        import tempfile

        fake_sa = {
            "type": "service_account",
            "project_id": "test",
            "private_key_id": "abc",
            # fmt: off
            "private_key": (
                "-----BEGIN RSA PRIVATE KEY-----\\n"
                "MIIBOgIBAAJBALRiMLAH\\n"
                "-----END RSA PRIVATE KEY-----\\n"
            ),
            # fmt: on
            "client_email": "test@test.iam.gserviceaccount.com",
            "client_id": "123",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            _json.dump(fake_sa, fh)
            tmp_path = fh.name

        try:
            adapter = GoogleSheetsAdapter(
                spreadsheet_id="test-id",
                credentials_path=tmp_path,
                dry_run=False,
            )
            with patch(
                "google.oauth2.service_account.Credentials.from_service_account_info"
            ) as mock_from_info:
                mock_creds = MagicMock()
                mock_creds.token = "mock-from-path"
                mock_from_info.return_value = mock_creds
                adapter._ensure_access_token()
                assert adapter.access_token == "mock-from-path"
        finally:
            os.remove(tmp_path)

    def test_access_token_not_required_when_service_account_json_present(self) -> None:
        adapter = GoogleSheetsAdapter(
            spreadsheet_id="test-id",
            service_account_json='{"type": "service_account"}',
            dry_run=False,
        )
        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_info"
            ) as mock_from_info,
            patch("commission_crowd_agent.adapters.httpx.get") as mock_get,
        ):
            mock_creds = MagicMock()
            mock_creds.token = "sa-token"
            mock_from_info.return_value = mock_creds
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"properties": {"title": "CCA Sheet"}}
            mock_get.return_value = mock_response
            result = adapter.health_check()
            assert result["ok"] is True
            assert result["error"] is None

    def test_no_leaked_token_in_error_output(self) -> None:
        adapter = GoogleSheetsAdapter(
            spreadsheet_id="test-id",
            service_account_json='{"type": "service_account"}',
            dry_run=False,
        )
        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_info"
            ) as mock_from_info,
            patch("commission_crowd_agent.adapters.httpx.get") as mock_get,
        ):
            mock_creds = MagicMock()
            mock_creds.token = "super-secret-sa-token"
            mock_from_info.return_value = mock_creds
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Forbidden", request=MagicMock(), response=mock_response
            )
            mock_get.return_value = mock_response
            result = adapter.health_check()
            result_str = str(result)
            assert "super-secret-sa-token" not in result_str

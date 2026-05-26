"""Tests for Telegram notifier adapter.

All Telegram API calls are mocked. No real token or network traffic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from commission_crowd_agent.adapters import NotifierAdapter


class TestDryRun:
    def test_dry_run_returns_ok_without_calling_api(self) -> None:
        notifier = NotifierAdapter(bot_token="fake", chat_id="123", dry_run=True)
        with patch("commission_crowd_agent.adapters.httpx.post") as mock_post:
            result = notifier.send_message(text="hello")
        mock_post.assert_not_called()
        assert result["ok"] is True
        assert result["status"] == 0
        assert result["message_id"] is None
        assert result["error"] is None


class TestSendMessageSuccess:
    def test_send_message_success(self) -> None:
        notifier = NotifierAdapter(bot_token="fake", chat_id="123", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 42}}
        with patch("commission_crowd_agent.adapters.httpx.post", return_value=mock_response):
            result = notifier.send_message(text="hello")
        assert result["ok"] is True
        assert result["status"] == 200
        assert result["message_id"] == 42
        assert result["error"] is None

    def test_send_message_api_returns_ok_false(self) -> None:
        notifier = NotifierAdapter(bot_token="fake", chat_id="123", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "ok": False,
            "description": "Bad Request: chat not found",
        }
        with patch("commission_crowd_agent.adapters.httpx.post", return_value=mock_response):
            result = notifier.send_message(text="hello")
        assert result["ok"] is False
        assert result["status"] == 400
        assert result["message_id"] is None
        assert "chat not found" in (result["error"] or "")

    def test_send_message_http_error(self) -> None:
        notifier = NotifierAdapter(bot_token="fake", chat_id="123", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_response
        )
        with patch("commission_crowd_agent.adapters.httpx.post", return_value=mock_response):
            result = notifier.send_message(text="hello")
        assert result["ok"] is False
        assert result["status"] == 403
        assert result["error"] is not None


class TestSendMessageNetworkFailure:
    def test_connect_error(self) -> None:
        notifier = NotifierAdapter(bot_token="fake", chat_id="123", dry_run=False)
        with patch(
            "commission_crowd_agent.adapters.httpx.post",
            side_effect=httpx.ConnectError("Network unreachable"),
        ):
            result = notifier.send_message(text="hello")
        assert result["ok"] is False
        assert result["status"] == 0
        assert "Network error" in (result["error"] or "")

    def test_timeout(self) -> None:
        notifier = NotifierAdapter(bot_token="fake", chat_id="123", dry_run=False)
        with patch(
            "commission_crowd_agent.adapters.httpx.post",
            side_effect=httpx.TimeoutException("Read timeout"),
        ):
            result = notifier.send_message(text="hello")
        assert result["ok"] is False
        assert result["status"] == 0
        assert "Network error" in (result["error"] or "")


class TestMissingCredentials:
    def test_missing_bot_token(self) -> None:
        notifier = NotifierAdapter(bot_token="", chat_id="123", dry_run=False)
        result = notifier.send_message(text="hello")
        assert result["ok"] is False
        assert "Missing bot_token" in (result["error"] or "")

    def test_missing_chat_id(self) -> None:
        notifier = NotifierAdapter(bot_token="fake", chat_id="", dry_run=False)
        result = notifier.send_message(text="hello")
        assert result["ok"] is False
        assert "Missing" in (result["error"] or "")

    def test_missing_chat_id_overridden_by_param(self) -> None:
        notifier = NotifierAdapter(bot_token="fake", chat_id="", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 7}}
        with patch("commission_crowd_agent.adapters.httpx.post", return_value=mock_response):
            result = notifier.send_message(chat_id="override", text="hello")
        assert result["ok"] is True
        assert result["message_id"] == 7


class TestTokenPresence:
    def test_token_present_false_when_empty(self) -> None:
        notifier = NotifierAdapter(bot_token="", chat_id="123")
        assert notifier.token_present() is False

    def test_token_present_true_when_set(self) -> None:
        notifier = NotifierAdapter(bot_token="secret-token", chat_id="123")
        assert notifier.token_present() is True


class TestNoSecretLeak:
    def test_result_dict_never_contains_token(self) -> None:
        notifier = NotifierAdapter(bot_token="super-secret-123", chat_id="456", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        with patch("commission_crowd_agent.adapters.httpx.post", return_value=mock_response):
            result = notifier.send_message(text="hi")
        for value in result.values():
            if isinstance(value, str):
                assert "super-secret-123" not in value

    def test_error_string_never_contains_token(self) -> None:
        notifier = NotifierAdapter(bot_token="super-secret-123", chat_id="456", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"ok": False, "description": "Bad Request"}
        with patch("commission_crowd_agent.adapters.httpx.post", return_value=mock_response):
            result = notifier.send_message(text="hi")
        error = result.get("error") or ""
        assert "super-secret-123" not in error


class TestRetry:
    def test_success_after_two_500s(self) -> None:
        notifier = NotifierAdapter(bot_token="fake", chat_id="123", dry_run=False)
        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {"ok": True, "result": {"message_id": 99}}

        fail_response = MagicMock()
        fail_response.status_code = 500

        call_count = 0

        def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return fail_response
            return ok_response

        with patch("commission_crowd_agent.adapters.httpx.post", side_effect=side_effect):
            result = notifier.send_message(text="hello")

        assert call_count == 3
        assert result["ok"] is True
        assert result["message_id"] == 99

"""Tests for config module with shared secrets integration.

Never reads the real /home/ubuntu/hermes-control/secrets/shared.env file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from commission_crowd_agent.config import CcaSettings, load_settings


def test_load_settings_defaults() -> None:
    settings = CcaSettings()
    assert settings.ollama_model == "kimi-k2.6"
    assert settings.cca_daily_volume_limit == 50
    assert settings.cca_log_level == "INFO"


def test_load_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCA_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    settings = load_settings()
    assert settings.cca_log_level == "DEBUG"
    assert settings.telegram_bot_token == "test-token"


def test_readiness_properties_false_by_default() -> None:
    settings = CcaSettings()
    assert settings.ollama_ready is False
    assert settings.telegram_ready is False
    assert settings.google_ready is False
    assert settings.smtp_ready is False


def test_readiness_properties_true_when_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_API_KEY", "secret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    settings = CcaSettings()
    assert settings.ollama_ready is True
    assert settings.telegram_ready is True


def test_ollama_ready_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local Ollama should report ready when only base_url is set."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    settings = CcaSettings()
    assert settings.ollama_ready is True


def test_env_var_precedence_over_shared_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "shared.env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=file-token\nTELEGRAM_CHAT_ID=111\n")
    monkeypatch.setenv("COMMISSION_CROWD_SHARED_ENV_PATH", str(env_file))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    settings = load_settings()
    assert settings.telegram_bot_token == "env-token"


def test_shared_env_fallback_when_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "shared.env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=shared-token\nTELEGRAM_CHAT_ID=222\n")
    monkeypatch.setenv("COMMISSION_CROWD_SHARED_ENV_PATH", str(env_file))
    # Ensure env var is NOT set
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    settings = load_settings()
    assert settings.telegram_bot_token == "shared-token"


def test_safe_repr_does_not_expose_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASS", "mail-secret")
    settings = load_settings()
    repr_str = settings.safe_repr()
    assert "super-secret" not in repr_str
    assert "mail-secret" not in repr_str
    assert "telegram_ready=True" in repr_str
    assert "smtp_ready=True" in repr_str

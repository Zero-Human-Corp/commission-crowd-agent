"""Tests for config module."""

from commission_crowd_agent.config import CcaSettings, load_settings


def test_load_settings_defaults():
    settings = CcaSettings()
    assert settings.ollama_model == "kimi-k2.6"
    assert settings.cca_daily_volume_limit == 50
    assert settings.cca_log_level == "INFO"


def test_load_settings_from_env(monkeypatch):
    monkeypatch.setenv("CCA_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    settings = load_settings()
    assert settings.cca_log_level == "DEBUG"
    assert settings.telegram_bot_token == "test-token"


def test_readiness_properties_false_by_default():
    settings = CcaSettings()
    assert settings.ollama_ready is False
    assert settings.telegram_ready is False
    assert settings.google_ready is False
    assert settings.smtp_ready is False


def test_readiness_properties_true_when_populated(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_API_KEY", "secret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    settings = CcaSettings()
    assert settings.ollama_ready is True
    assert settings.telegram_ready is True

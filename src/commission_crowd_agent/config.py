"""Typed configuration loader using Pydantic Settings.

Reads from environment variables and optional `.env` file.
No secrets are hardcoded; failures are loud.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CcaSettings(BaseSettings):
    """Commission Crowd Agent runtime settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM / Ollama ---
    ollama_base_url: str = Field(default="", description="Ollama.com Cloud base URL")
    ollama_api_key: str = Field(default="", description="Ollama API key")
    ollama_model: str = Field(default="kimi-k2.6", description="Model name for agents")

    # --- Telegram ---
    telegram_bot_token: str = Field(default="", description="Telegram Bot API token")
    telegram_chat_id: str = Field(default="", description="Default operator chat ID")

    # --- Google (Sheets, Drive, Gmail) ---
    google_client_id: str = Field(default="")
    google_client_secret: str = Field(default="")
    google_refresh_token: str = Field(default="")
    google_sheets_spreadsheet_id: str = Field(default="")

    # --- Email / SMTP ---
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_pass: str = Field(default="")
    smtp_from: str = Field(default="")

    # --- n8n ---
    n8n_base_url: str = Field(default="")
    n8n_api_key: str = Field(default="")
    n8n_basic_auth_user: str = Field(default="")
    n8n_basic_auth_pass: str = Field(default="")

    # --- Agent ---
    cca_client_name: str = Field(default="", description="Default client name for runs")
    cca_daily_volume_limit: int = Field(default=50, ge=1)
    cca_log_level: str = Field(default="INFO")

    @property
    def ollama_ready(self) -> bool:
        return bool(self.ollama_base_url and self.ollama_api_key)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def google_ready(self) -> bool:
        return bool(
            self.google_client_id and self.google_client_secret and self.google_refresh_token
        )

    @property
    def smtp_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_pass)


def load_settings() -> CcaSettings:
    """Return a validated settings instance."""
    return CcaSettings()

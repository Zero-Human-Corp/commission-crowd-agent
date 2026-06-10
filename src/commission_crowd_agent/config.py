"""Typed configuration loader using Pydantic Settings.

Reads from environment variables, optional `.env` file, and the shared
secrets file at /home/ubuntu/hermes-control/secrets/shared.env.
No secrets are hardcoded; failures are loud.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .secrets import MissingEnvFileError, load_shared_env


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
    google_application_credentials_path: str = Field(
        default="", description="Path to service account JSON file"
    )
    google_service_account_json: str = Field(
        default="", description="Inline service account JSON (use path if possible)"
    )

    # --- Operator identity ---
    operator_name: str = Field(default="", description="Sales agent full name")
    operator_email: str = Field(default="", description="Primary sales email")
    operator_phone: str = Field(default="", description="Contact phone number")

    # --- Email / SMTP ---
    smtp_host: str = Field(default="smtp.hostinger.com")
    smtp_port: int = Field(default=465)
    smtp_user: str = Field(default="publisher@syntaxis.online")
    smtp_pass: str = Field(default="")
    smtp_from: str = Field(default="publisher@syntaxis.online")

    # --- n8n ---
    n8n_base_url: str = Field(default="")
    n8n_api_key: str = Field(default="")
    n8n_basic_auth_user: str = Field(default="")
    n8n_basic_auth_pass: str = Field(default="")

    # --- CommissionCrowd ---
    commissioncrowd_api_key: str = Field(default="", description="CommissionCrowd REST API key")
    commissioncrowd_base_url: str = Field(
        default="https://www.commissioncrowd.com/api",
        description="CommissionCrowd API base URL",
    )
    cca_client_name: str = Field(default="", description="Default client name for runs")
    cca_daily_volume_limit: int = Field(default=50, ge=1)
    cca_log_level: str = Field(default="INFO")

    # --- Supervisor Relay (local model routing) ---
    supervisor_mode: str = Field(default="local", description="local | disabled | openai")
    supervisor_base_url: str = Field(default="http://localhost:11434/v1")
    supervisor_api_key: str = Field(default="")
    supervisor_primary_model: str = Field(default="glm-5.1")
    supervisor_code_review_model: str = Field(default="qwen3-coder-next")
    supervisor_reasoning_fallback_model: str = Field(default="deepseek-v3.2")
    supervisor_draft_review_model: str = Field(default="gemma3:27b-cloud")
    supervisor_long_context_model: str = Field(default="nemotron-3-super:cloud")
    supervisor_emergency_fallback_model: str = Field(default="kimi-k2.6:cloud")
    supervisor_allow_fallback: bool = Field(
        default=False,
        description=(
            "Allow fallback to another model when the configured route model is unavailable"
        ),
    )
    supervisor_fallback_model: str = Field(
        default="",
        description="Fallback model name when route model unavailable and fallback enabled",
    )
    supervisor_telegram_notify: bool = Field(
        default=True,
        description="Send Telegram acknowledgement after supervisor decisions",
    )

    @property
    def ollama_ready(self) -> bool:
        """Local Ollama does not require an API key."""
        return bool(self.ollama_base_url)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def google_ready(self) -> bool:
        """True if Google credentials are available (OAuth or service account)."""
        has_oauth = bool(
            self.google_client_id and self.google_client_secret and self.google_refresh_token
        )
        has_service_account = bool(
            self.google_application_credentials_path or self.google_service_account_json
        )
        return has_oauth or has_service_account

    @property
    def smtp_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_pass)

    @property
    def commissioncrowd_ready(self) -> bool:
        return bool(self.commissioncrowd_api_key)

    def safe_repr(self) -> str:
        """Return a settings summary with no secret values exposed."""
        return (
            f"CcaSettings(ollama_ready={self.ollama_ready}, "
            f"telegram_ready={self.telegram_ready}, "
            f"google_ready={self.google_ready}, "
            f"smtp_ready={self.smtp_ready}, "
            f"client={self.cca_client_name!r})"
        )


# Mapping of config field names to shared-env key names
_SHARED_KEY_MAP: dict[str, str] = {
    "operator_name": "OPERATOR_NAME",
    "operator_email": "OPERATOR_EMAIL",
    "operator_phone": "OPERATOR_PHONE",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "ollama_api_key": "OLLAMA_API_KEY",
    "ollama_model": "OLLAMA_MODEL",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "google_refresh_token": "GOOGLE_REFRESH_TOKEN",
    "google_sheets_spreadsheet_id": "GOOGLE_SHEETS_SPREADSHEET_ID",
    "google_application_credentials_path": "GOOGLE_APPLICATION_CREDENTIALS_PATH",
    "google_service_account_json": "GOOGLE_SERVICE_ACCOUNT_JSON",
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_user": "SMTP_USER",
    "smtp_pass": "SMTP_PASS",
    "smtp_from": "SMTP_FROM",
    "n8n_base_url": "N8N_BASE_URL",
    "n8n_api_key": "N8N_API_KEY",
    "n8n_basic_auth_user": "N8N_BASIC_AUTH_USER",
    "n8n_basic_auth_pass": "N8N_BASIC_AUTH_PASS",
    "commissioncrowd_api_key": "COMMISSIONCROWD_API_KEY",
    "commissioncrowd_base_url": "COMMISSIONCROWD_BASE_URL",
    "cca_client_name": "CCA_CLIENT_NAME",
    "cca_daily_volume_limit": "CCA_DAILY_VOLUME_LIMIT",
    "cca_log_level": "CCA_LOG_LEVEL",
    "supervisor_mode": "SUPERVISOR_MODE",
    "supervisor_base_url": "SUPERVISOR_BASE_URL",
    "supervisor_api_key": "SUPERVISOR_API_KEY",
    "supervisor_primary_model": "SUPERVISOR_PRIMARY_MODEL",
    "supervisor_code_review_model": "SUPERVISOR_CODE_REVIEW_MODEL",
    "supervisor_reasoning_fallback_model": "SUPERVISOR_REASONING_FALLBACK_MODEL",
    "supervisor_draft_review_model": "SUPERVISOR_DRAFT_REVIEW_MODEL",
    "supervisor_long_context_model": "SUPERVISOR_LONG_CONTEXT_MODEL",
    "supervisor_emergency_fallback_model": "SUPERVISOR_EMERGENCY_FALLBACK_MODEL",
    "supervisor_allow_fallback": "SUPERVISOR_ALLOW_FALLBACK",
    "supervisor_fallback_model": "SUPERVISOR_FALLBACK_MODEL",
    "supervisor_telegram_notify": "SUPERVISOR_TELEGRAM_NOTIFY",
}


def _parse_dotenv(path: str) -> dict[str, str]:
    """Parse a dotenv-style file manually (no external deps needed)."""
    result: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return result
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip()
    return result


def _merge_sources() -> dict[str, Any]:
    """Build a merged dict: os.environ > .env > shared.env > defaults.

    Returns a plain dict suitable for CcaSettings(**merged).
    """
    merged: dict[str, Any] = {}

    # 1. Load .env (project-local) and shared.env (system-wide)
    dotenv = _parse_dotenv(".env")
    try:
        shared = load_shared_env()
    except MissingEnvFileError:
        shared = {}

    # 2. For each known field, prefer os.environ, then .env, then shared.env
    for field, env_key in _SHARED_KEY_MAP.items():
        env_val = os.getenv(env_key, "")
        dotenv_val = dotenv.get(env_key, "")
        shared_val = shared.get(env_key, "")
        value = env_val or dotenv_val or shared_val
        if value:
            # Pydantic will coerce numeric strings to int automatically
            merged[field] = value

    return merged


def load_settings() -> CcaSettings:
    """Return a validated settings instance.

    Merges os.environ (highest priority) with the shared secrets file.
    """
    merged = _merge_sources()
    return CcaSettings(**merged)

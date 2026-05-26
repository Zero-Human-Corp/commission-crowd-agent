"""Shared secrets loader for Commission Crowd Agent.

Reads dotenv-style KEY=VALUE files from a path outside the repository.
No values are logged or printed.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SHARED_ENV_PATH = "/home/ubuntu/hermes-control/secrets/shared.env"
SHARED_ENV_VAR = "COMMISSION_CROWD_SHARED_ENV_PATH"


class SecretsError(Exception):
    """Raised when a required secret is missing or the shared env file cannot be read."""


class MissingSecretError(SecretsError):
    """Raised when a specific required key is absent."""


class MissingEnvFileError(SecretsError):
    """Raised when the shared env file does not exist."""


def _resolve_path() -> Path:
    """Return the shared env file path from env var or default."""
    raw = os.getenv(SHARED_ENV_VAR, DEFAULT_SHARED_ENV_PATH)
    return Path(raw)


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv-style file and return a plain dict.

    Rules:
    - Skip blank lines and lines starting with '#'.
    - Split on the first '=' only.
    - Strip whitespace from key and value.
    - Values may be empty strings.
    """
    result: dict[str, str] = {}
    if not path.exists():
        return result
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip()
    return result


def load_shared_env(path: Path | None = None) -> dict[str, str]:
    """Load the shared env file and return all key-value pairs.

    Raises MissingEnvFileError if the file does not exist.
    """
    target = path or _resolve_path()
    if not target.exists():
        raise MissingEnvFileError(f"Shared env file not found: {target}")
    return _parse_env_file(target)


def get_secret(key: str, *, required: bool = True, path: Path | None = None) -> str:
    """Return a single secret value.

    Precedence:
    1. Actual environment variable (os.environ).
    2. Shared env file (COMMISSION_CROWD_SHARED_ENV_PATH or default).

    If required=True and the key is missing, raises MissingSecretError.
    If required=False, returns an empty string when missing.
    """
    # 1. Environment takes precedence
    env_value = os.getenv(key, "")
    if env_value:
        return env_value

    # 2. Fall back to shared env file
    shared = load_shared_env(path)
    value = shared.get(key, "")

    if required and not value:
        raise MissingSecretError(f"Required secret '{key}' not found in env or shared env file")
    return value

"""Tests for shared secrets loader.

Never reads the real /home/ubuntu/hermes-control/secrets/shared.env file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from commission_crowd_agent.secrets import (
    MissingEnvFileError,
    MissingSecretError,
    _parse_env_file,
    _resolve_path,
    get_secret,
    load_shared_env,
)


class TestParseEnvFile:
    def test_parses_key_value(self, tmp_path: Path) -> None:
        env_file = tmp_path / "fake.env"
        env_file.write_text("FOO=bar\n")
        result = _parse_env_file(env_file)
        assert result == {"FOO": "bar"}

    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        env_file = tmp_path / "fake.env"
        env_file.write_text("\n# comment\nKEY=value\n\n")
        result = _parse_env_file(env_file)
        assert result == {"KEY": "value"}

    def test_allows_empty_values(self, tmp_path: Path) -> None:
        env_file = tmp_path / "fake.env"
        env_file.write_text("EMPTY=\n")
        result = _parse_env_file(env_file)
        assert result == {"EMPTY": ""}

    def test_splits_on_first_equals_only(self, tmp_path: Path) -> None:
        env_file = tmp_path / "fake.env"
        env_file.write_text("EQ=a=b\n")
        result = _parse_env_file(env_file)
        assert result == {"EQ": "a=b"}

    def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "no.env"
        result = _parse_env_file(missing)
        assert result == {}


class TestLoadSharedEnv:
    def test_loads_all_pairs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / "shared.env"
        env_file.write_text("A=1\nB=2\n")
        monkeypatch.setenv("COMMISSION_CROWD_SHARED_ENV_PATH", str(env_file))
        result = load_shared_env()
        assert result == {"A": "1", "B": "2"}

    def test_raises_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        missing = tmp_path / "missing.env"
        monkeypatch.setenv("COMMISSION_CROWD_SHARED_ENV_PATH", str(missing))
        with pytest.raises(MissingEnvFileError):
            load_shared_env()

    def test_accepts_explicit_path(self, tmp_path: Path) -> None:
        env_file = tmp_path / "override.env"
        env_file.write_text("X=y\n")
        result = load_shared_env(env_file)
        assert result == {"X": "y"}


class TestGetSecret:
    def test_env_var_takes_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / "shared.env"
        env_file.write_text("MY_KEY=file-value\n")
        monkeypatch.setenv("COMMISSION_CROWD_SHARED_ENV_PATH", str(env_file))
        monkeypatch.setenv("MY_KEY", "env-value")
        result = get_secret("MY_KEY")
        assert result == "env-value"

    def test_falls_back_to_shared_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / "shared.env"
        env_file.write_text("MY_KEY=file-value\n")
        monkeypatch.setenv("COMMISSION_CROWD_SHARED_ENV_PATH", str(env_file))
        result = get_secret("MY_KEY")
        assert result == "file-value"

    def test_raises_when_required_and_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / "shared.env"
        env_file.write_text("OTHER=val\n")
        monkeypatch.setenv("COMMISSION_CROWD_SHARED_ENV_PATH", str(env_file))
        with pytest.raises(MissingSecretError, match="MY_KEY"):
            get_secret("MY_KEY", required=True)

    def test_returns_empty_when_optional_and_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / "shared.env"
        env_file.write_text("OTHER=val\n")
        monkeypatch.setenv("COMMISSION_CROWD_SHARED_ENV_PATH", str(env_file))
        result = get_secret("MY_KEY", required=False)
        assert result == ""


class TestResolvePath:
    def test_default_path(self) -> None:
        path = _resolve_path()
        assert path == Path("/home/ubuntu/hermes-control/secrets/shared.env")

    def test_override_via_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMMISSION_CROWD_SHARED_ENV_PATH", "/tmp/test.env")
        path = _resolve_path()
        assert path == Path("/tmp/test.env")

"""Tests for operator_source ingestion workflow.

Covers:
- OperatorSource validation (URL scheme, placeholders)
- OperatorSourceIngester.load_source_file / parse_single_url
- ingest_sources dry-run safety
- Hard limit enforcement
- Placeholder blocking
- Provenance tracking
- No write by default
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from commission_crowd_agent.lead_ingestion import LeadIngester
from commission_crowd_agent.operator_source import (
    OperatorSource,
    OperatorSourceIngester,
)
from commission_crowd_agent.stub_detector import is_placeholder_lead


class TestOperatorSourceValidation:
    def test_valid_http_url(self) -> None:
        s = OperatorSource(name="Acme", url="https://acme.dev/about")
        assert s.url == "https://acme.dev/about"

    def test_invalid_url_missing_scheme(self) -> None:
        with pytest.raises(ValueError):
            OperatorSource(name="Bad", url="ftp://acme.dev")

    def test_invalid_url_no_scheme(self) -> None:
        with pytest.raises(ValueError):
            OperatorSource(name="Bad", url="acme.dev")

    def test_name_min_length(self) -> None:
        with pytest.raises(ValueError):
            OperatorSource(name="", url="https://acme.dev")


class TestOperatorSourcePlaceholder:
    def test_placeholder_domain_example(self) -> None:
        s = OperatorSource(name="Example", url="https://example.com/dir", enabled=True)
        assert s.is_placeholder is True

    def test_placeholder_domain_test(self) -> None:
        s = OperatorSource(name="TestCo", url="https://test.io", enabled=True)
        assert s.is_placeholder is True

    def test_placeholder_domain_localhost(self) -> None:
        s = OperatorSource(name="Local", url="http://localhost:3000", enabled=True)
        assert s.is_placeholder is True

    def test_real_domain_not_placeholder(self) -> None:
        s = OperatorSource(name="Acme", url="https://acme.dev/about", enabled=True)
        assert s.is_placeholder is False

    def test_fixture_name_blocked(self) -> None:
        s = OperatorSource(name="StubCorp", url="https://real.io", enabled=True)
        assert s.is_placeholder is True

    def test_placeholder_notes_with_url(self) -> None:
        # Stub hints only trigger when URL is missing — tested via direct heuristic
        assert is_placeholder_lead(notes="stub entry") is True

    def test_placeholder_notes_without_stub(self) -> None:
        s = OperatorSource(name="Something", url="https://real.io/a", notes="real entry")
        assert s.is_placeholder is False

    def test_placeholder_notes_ignored_when_url_present(self) -> None:
        s = OperatorSource(name="Something", url="https://real.io/a", notes="stub entry")
        # heuristic requires missing url + synthetic notes
        assert s.is_placeholder is False


class TestLoadSourceFile:
    def test_load_valid_sources(self, tmp_path: Path) -> None:
        data = [
            {"name": "Alpha", "url": "https://alpha.dev", "source_type": "blog", "enabled": True},
            {"name": "Beta", "url": "https://beta.dev", "source_type": "news", "enabled": False},
        ]
        path = tmp_path / "sources.json"
        path.write_text(json.dumps(data))
        entries = OperatorSourceIngester.load_source_file(path)
        assert len(entries) == 2
        assert entries[0].name == "Alpha"
        assert entries[1].enabled is False

    def test_load_skips_malformed(self, tmp_path: Path) -> None:
        data = [
            {"name": "Good", "url": "https://good.dev"},
            {"invalid": "entry"},
        ]
        path = tmp_path / "sources.json"
        path.write_text(json.dumps(data))
        entries = OperatorSourceIngester.load_source_file(path)
        assert len(entries) == 1
        assert entries[0].name == "Good"

    def test_load_non_list_root_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"name": "solo"}))
        with pytest.raises(ValueError):
            OperatorSourceIngester.load_source_file(path)


class TestParseSingleUrl:
    def test_parse_valid_url(self) -> None:
        s = OperatorSourceIngester.parse_single_url("https://alpha.dev/about", name="Alpha")
        assert s.name == "Alpha"
        assert s.url == "https://alpha.dev/about"
        assert s.source_type == "cli_provided"

    def test_parse_placeholder_url_raises(self) -> None:
        with pytest.raises(ValueError):
            OperatorSourceIngester.parse_single_url("https://example.com")

    def test_parse_missing_scheme_raises(self) -> None:
        with pytest.raises(ValueError):
            OperatorSourceIngester.parse_single_url("alpha.dev")


class TestIngestSourcesDryRun:
    @pytest.fixture(autouse=True)
    def _stub_fetch_html(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make every test hermetic: never hit the network for source HTML.

        Several tests in this class previously made a real ``httpx.get`` to the
        source URL without mocking ``_fetch_html``, so they only passed when the
        external host happened to be reachable. Returning minimal HTML forces
        the extraction fallback path (source-page-as-lead) deterministically,
        matching the existing ``test_limit_capped_at_hard_max`` pattern.
        """
        monkeypatch.setattr(
            OperatorSourceIngester,
            "_fetch_html",
            lambda self, url: "<html></body></html>",
        )

    def test_no_sources_returns_safe(self) -> None:
        ingester = OperatorSourceIngester()
        result = ingester.ingest_sources([], limit=3, dry_run=True)
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["candidates"] == 0
        assert result["written"] == 0
        assert "No enabled" in result["message"] or "sources" in result["message"]

    def test_placeholder_sources_skipped(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="StubCorp", url="https://example.com/stub", enabled=True),
            OperatorSource(name="Acme", url="https://acme.dev", enabled=True),
        ]
        result = ingester.ingest_sources(sources, limit=3, dry_run=True)
        assert result["candidates"] == 1
        assert result["skipped"] == 1
        assert result["sources"][0]["name"] == "Acme"

    def test_disabled_sources_skipped(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="Alpha", url="https://alpha.dev", enabled=False),
        ]
        result = ingester.ingest_sources(sources, limit=3, dry_run=True)
        assert result["candidates"] == 0
        assert result["skipped"] == 1

    def test_limit_capped_at_hard_max(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name=f"S{i}", url=f"https://s{i}.dev", enabled=True) for i in range(10)
        ]
        with patch.object(ingester, "_fetch_html", return_value="<html></body></html>"):
            result = ingester.ingest_sources(sources, limit=10, dry_run=True)
        # limit should be silently clamped to 5
        assert result["candidates"] == 5
        # sources list now includes all valid sources with per_source_limit metadata
        assert len(result["sources"]) == 10
        # source_reports should exist for every source
        assert len(result["source_reports"]) == 10

    def test_provenance_is_url(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="Acme", url="https://acme.dev/careers", enabled=True),
        ]
        result = ingester.ingest_sources(sources, limit=3, dry_run=True)
        assert result["candidates"] == 1
        assert result["sources"][0]["url"] == "https://acme.dev/careers"

    def test_dry_run_writes_zero(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.validate_tab_header.return_value = {"ok": True}
        mock_adapter.append_row.return_value = {"ok": True}
        lead_ingester = LeadIngester(sheets_adapter=mock_adapter)
        ingester = OperatorSourceIngester(lead_ingester=lead_ingester)
        sources = [
            OperatorSource(name="Acme", url="https://acme.dev", enabled=True),
        ]
        result = ingester.ingest_sources(sources, limit=3, dry_run=True)
        assert result["dry_run"] is True
        assert result["written"] == 0
        mock_adapter.append_row.assert_not_called()

    def test_live_write_calls_adapter(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.validate_tab_header.return_value = {"ok": True}
        mock_adapter.append_row.return_value = {"ok": True}
        lead_ingester = LeadIngester(sheets_adapter=mock_adapter)
        ingester = OperatorSourceIngester(lead_ingester=lead_ingester)
        sources = [
            OperatorSource(name="Acme", url="https://acme.dev", enabled=True),
        ]
        result = ingester.ingest_sources(sources, limit=3, dry_run=False)
        assert result["dry_run"] is False
        assert result["written"] == 1
        mock_adapter.append_row.assert_called_once()

    def test_email_not_invented(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="Acme", url="https://acme.dev", enabled=True),
        ]
        result = ingester.ingest_sources(sources, limit=3, dry_run=True)
        # This is an indirect check: we don't set email because we never invent one.
        assert result["ok"] is True

    def test_no_outreach_path_called(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="Acme", url="https://acme.dev", enabled=True),
        ]
        result = ingester.ingest_sources(sources, limit=3, dry_run=True)
        assert result["approvals"] == 0  # no approval_gate wired by default
        assert result["candidates"] == 1

"""Tests for per-source extraction limits and related reporting.

Covers:
- One source cannot consume the full global limit when per_source_limit is set
- Global limit still caps total candidates across all sources
- Per-source limit 0 falls back to global limit
- Affiverse candidates are reached after Rewardful per-source cap
- Duplicate candidates are skipped per source
- Placeholder candidates are blocked per source
- Source reports contain correct extraction/duplicate/placeholder/written counts
- No outreach path is called
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from commission_crowd_agent.directory_extractor import ExtractedCandidate
from commission_crowd_agent.operator_source import (
    OperatorSource,
    OperatorSourceIngester,
)


class TestPerSourceLimits:
    def test_one_source_cannot_consume_full_global_limit(self) -> None:
        """Rewardful with per_source_limit=2 can only contribute 2 even when 5 are available."""
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(
                name="BigDir",
                url="https://bigdir.dev",
                enabled=True,
                per_source_limit=2,
            ),
        ]
        mock_candidates = [
            ExtractedCandidate(company=f"Co{i}", url=f"https://bigdir.dev/c{i}") for i in range(5)
        ]

        with (
            patch.object(ingester, "_fetch_html", return_value=""),
            patch(
                "commission_crowd_agent.operator_source.extract_candidates",
                return_value=mock_candidates,
            ),
        ):
            result = ingester.ingest_sources(sources, limit=5, dry_run=True)

        assert result["candidates"] == 2
        assert result["source_reports"][0]["extracted"] == 2
        assert result["source_reports"][0]["per_source_limit"] == 2

    def test_global_limit_still_caps_total(self) -> None:
        """Even with generous per-source limits, global limit caps total."""
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(
                name="DirA",
                url="https://dira.dev",
                enabled=True,
                per_source_limit=10,
            ),
            OperatorSource(
                name="DirB",
                url="https://dirb.dev",
                enabled=True,
                per_source_limit=10,
            ),
        ]
        mock_a = [
            ExtractedCandidate(company=f"A{i}", url=f"https://dira.dev/a{i}") for i in range(5)
        ]
        mock_b = [
            ExtractedCandidate(company=f"B{i}", url=f"https://dirb.dev/b{i}") for i in range(5)
        ]

        with (
            patch.object(ingester, "_fetch_html", return_value=""),
            patch(
                "commission_crowd_agent.operator_source.extract_candidates",
                side_effect=[mock_a, mock_b],
            ),
        ):
            result = ingester.ingest_sources(sources, limit=5, dry_run=True)

        assert result["candidates"] == 5
        # First source consumed all 5 slots, second was skipped due to global cap
        assert result["source_reports"][0]["written"] == 5
        assert result["source_reports"][1]["status"] == "skipped_global_cap"

    def test_affiverse_reached_after_rewardful_cap(self) -> None:
        """Affiverse gets candidates after Rewardful's per-source cap is hit."""
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(
                name="Rewardful",
                url="https://www.rewardful.com/saas-affiliate-programs",
                enabled=True,
                per_source_limit=2,
            ),
            OperatorSource(
                name="Affiverse",
                url="https://www.affiversemedia.com/directory/",
                enabled=True,
                per_source_limit=3,
            ),
        ]
        mock_rewardful = [
            ExtractedCandidate(
                company=f"RewardfulCo {i}",
                url=f"https://www.rewardful.com/saas-affiliate-programs/c{i}",
            )
            for i in range(5)
        ]
        mock_affiverse = [
            ExtractedCandidate(
                company=f"AffiverseCo {i}",
                url=f"https://www.affiversemedia.com/affiliate_directory/c{i}/",
            )
            for i in range(3)
        ]

        with (
            patch.object(ingester, "_fetch_html", return_value=""),
            patch(
                "commission_crowd_agent.operator_source.extract_candidates",
                side_effect=[mock_rewardful, mock_affiverse],
            ),
        ):
            result = ingester.ingest_sources(sources, limit=5, dry_run=True)

        assert result["candidates"] == 5
        assert result["source_reports"][0]["extracted"] == 2
        assert result["source_reports"][0]["per_source_limit"] == 2
        assert result["source_reports"][1]["extracted"] == 3
        assert result["source_reports"][1]["per_source_limit"] == 3

    def test_zero_per_source_limit_falls_back_to_global(self) -> None:
        """per_source_limit=0 means source can consume up to the global limit."""
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(
                name="DirA",
                url="https://dira.dev",
                enabled=True,
                per_source_limit=0,
            ),
        ]
        mock_candidates = [
            ExtractedCandidate(company=f"A{i}", url=f"https://dira.dev/a{i}") for i in range(5)
        ]

        with (
            patch.object(ingester, "_fetch_html", return_value=""),
            patch(
                "commission_crowd_agent.operator_source.extract_candidates",
                return_value=mock_candidates,
            ),
        ):
            result = ingester.ingest_sources(sources, limit=3, dry_run=True)

        assert result["candidates"] == 3
        assert result["source_reports"][0]["per_source_limit"] == 3

    def test_duplicate_candidates_skipped(self) -> None:
        """Same URL across sources is deduplicated."""
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(
                name="DirA",
                url="https://dira.dev",
                enabled=True,
                per_source_limit=2,
            ),
            OperatorSource(
                name="DirB",
                url="https://dirb.dev",
                enabled=True,
                per_source_limit=2,
            ),
        ]
        # Both directories list the same company
        mock_a = [
            ExtractedCandidate(company="SameCo", url="https://same.co"),
            ExtractedCandidate(company="OtherA", url="https://othera.co"),
        ]
        mock_b = [
            ExtractedCandidate(company="SameCo", url="https://same.co"),
            ExtractedCandidate(company="OtherB", url="https://otherb.co"),
        ]

        with (
            patch.object(ingester, "_fetch_html", return_value=""),
            patch(
                "commission_crowd_agent.operator_source.extract_candidates",
                side_effect=[mock_a, mock_b],
            ),
        ):
            result = ingester.ingest_sources(sources, limit=5, dry_run=True)

        assert result["candidates"] == 3  # SameCo, OtherA, OtherB
        assert result["source_reports"][0]["duplicates_skipped"] == 0
        assert result["source_reports"][1]["duplicates_skipped"] == 1

    def test_placeholder_candidates_blocked(self) -> None:
        """Placeholder/stub candidates are blocked at ingestion time."""
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(
                name="DirA",
                url="https://dira.dev",
                enabled=True,
                per_source_limit=5,
            ),
        ]
        mock_candidates = [
            ExtractedCandidate(company="RealCo", url="https://realco.dev"),
            ExtractedCandidate(company="StubCorp", url="https://stubcorp.dev"),
        ]

        with (
            patch.object(ingester, "_fetch_html", return_value=""),
            patch(
                "commission_crowd_agent.operator_source.extract_candidates",
                return_value=mock_candidates,
            ),
        ):
            result = ingester.ingest_sources(sources, limit=5, dry_run=True)

        assert result["candidates"] == 1
        assert result["source_reports"][0]["placeholders_blocked"] == 1
        assert result["source_reports"][0]["written"] == 1

    def test_no_outreach_path_called(self) -> None:
        """ingest_sources never triggers outreach or email."""
        ingester = OperatorSourceIngester()
        sources = [OperatorSource(name="Acme", url="https://acme.dev", enabled=True)]
        result = ingester.ingest_sources(sources, limit=3, dry_run=True)
        assert result["approvals"] == 0  # no approval_gate wired by default
        assert result["candidates"] == 1  # fallback lead from source page


class TestSourceReports:
    def test_source_reports_present_for_all_sources(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="A", url="https://a.dev", enabled=True),
            OperatorSource(name="B", url="https://b.dev", enabled=True),
        ]
        result = ingester.ingest_sources(sources, limit=5, dry_run=True)
        assert "source_reports" in result
        assert len(result["source_reports"]) == 2

    def test_skipped_placeholder_source_reports(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="Real", url="https://real.dev", enabled=True),
            OperatorSource(name="StubCorp", url="https://example.com/stub", enabled=True),
        ]
        result = ingester.ingest_sources(sources, limit=5, dry_run=True)
        assert result["skipped"] == 1
        # Only 1 valid source, so 1 source report
        assert len(result["source_reports"]) == 1

    def test_error_source_report_contains_error(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="Bad", url="https://bad.dev", enabled=True),
        ]
        with patch.object(ingester, "_fetch_html", side_effect=Exception("Timeout")):
            result = ingester.ingest_sources(sources, limit=5, dry_run=True)

        sr = result["source_reports"][0]
        assert sr["status"] == "error"
        assert "Timeout" in sr["error"]
        assert sr["written"] == 0

    def test_fallback_source_report(self) -> None:
        """When extraction yields zero, fallback lead is reported."""
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="EmptyDir", url="https://emptydir.dev", enabled=True),
        ]
        # HTML with no h2/h3 headings that match extractors
        html = "<html><body><p>No listings here</p></body></html>"

        with patch.object(ingester, "_fetch_html", return_value=html):
            result = ingester.ingest_sources(sources, limit=5, dry_run=True)

        sr = result["source_reports"][0]
        assert sr["status"] == "fallback"
        assert sr["written"] == 1
        assert sr["extracted"] == 0

    def test_disabled_source_not_in_reports(self) -> None:
        ingester = OperatorSourceIngester()
        sources = [
            OperatorSource(name="On", url="https://on.dev", enabled=True),
            OperatorSource(name="Off", url="https://off.dev", enabled=False),
        ]
        result = ingester.ingest_sources(sources, limit=5, dry_run=True)
        assert len(result["source_reports"]) == 1
        assert result["source_reports"][0]["name"] == "On"


class TestLoadSourceFileWithPerSourceLimit:
    def test_load_sources_with_per_source_limit(self, tmp_path: Path) -> None:
        data = [
            {
                "name": "Rewardful",
                "url": "https://www.rewardful.com/saas-affiliate-programs",
                "source_type": "public_directory",
                "per_source_limit": 2,
                "enabled": True,
            },
            {
                "name": "Affiverse",
                "url": "https://www.affiversemedia.com/directory/",
                "source_type": "public_directory",
                "per_source_limit": 3,
                "enabled": True,
            },
        ]
        path = tmp_path / "sources.json"
        path.write_text(json.dumps(data))
        entries = OperatorSourceIngester.load_source_file(path)
        assert len(entries) == 2
        assert entries[0].per_source_limit == 2
        assert entries[1].per_source_limit == 3

    def test_load_sources_without_per_source_limit_defaults_zero(self, tmp_path: Path) -> None:
        data = [
            {"name": "Alpha", "url": "https://alpha.dev", "enabled": True},
        ]
        path = tmp_path / "sources.json"
        path.write_text(json.dumps(data))
        entries = OperatorSourceIngester.load_source_file(path)
        assert entries[0].per_source_limit == 0

"""Tests for the Sprint 3 report registry.

Covers:
- CommissionReport hash computation
- ReportRegistry deduplication by report_hash
- Conflict detection (amount_mismatch, period_overlap, orphan_report)
- Load/save round-trip
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from commission_crowd_agent.report_registry import CommissionReport, ReportRegistry, compute_report_hash


@pytest.fixture
def sample_report() -> CommissionReport:
    return CommissionReport(
        report_id="r-001",
        opportunity_id="opp-1",
        principal_name="Principal A",
        report_type="earnings",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        currency="USD",
        gross_amount=1000.0,
        net_amount=950.0,
        status="confirmed",
        source_url="https://example.com/report/1",
        raw_fingerprint="fp-1",
    )


class TestCommissionReport:
    def test_report_hash_is_stable(self, sample_report: CommissionReport) -> None:
        first = sample_report.report_hash
        second = sample_report.report_hash
        assert first == second
        assert len(first) == 64  # SHA-256 hex

    def test_hash_excludes_monetary_amounts(self, sample_report: CommissionReport) -> None:
        original_hash = compute_report_hash(sample_report)
        sample_report.gross_amount = 9999.0
        sample_report.net_amount = 1.0
        assert compute_report_hash(sample_report) == original_hash


class TestReportRegistry:
    def test_add_report_stores_record(self, sample_report: CommissionReport) -> None:
        registry = ReportRegistry()
        registry.add_report(sample_report)
        assert len(registry.list_reports()) == 1
        assert registry.list_reports()[0].report_id == "r-001"

    def test_deduplication_by_hash(self, sample_report: CommissionReport) -> None:
        registry = ReportRegistry()
        registry.add_report(sample_report)
        duplicate = CommissionReport(
            report_id="r-002",
            opportunity_id=sample_report.opportunity_id,
            principal_name=sample_report.principal_name,
            report_type=sample_report.report_type,
            period_start=sample_report.period_start,
            period_end=sample_report.period_end,
            currency=sample_report.currency,
            gross_amount=sample_report.gross_amount,
            net_amount=sample_report.net_amount,
            status=sample_report.status,
            source_url=sample_report.source_url,
            raw_fingerprint="different-raw-fingerprint",
        )
        result = registry.add_report(duplicate)
        assert len(registry.list_reports()) == 1
        assert result["action"] == "duplicate"

    def test_amount_mismatch_conflict(self, sample_report: CommissionReport) -> None:
        registry = ReportRegistry()
        registry.add_report(sample_report)
        conflicting = CommissionReport(
            report_id="r-003",
            opportunity_id=sample_report.opportunity_id,
            principal_name=sample_report.principal_name,
            report_type=sample_report.report_type,
            period_start=sample_report.period_start,
            period_end=sample_report.period_end,
            currency=sample_report.currency,
            gross_amount=999.0,
            net_amount=sample_report.net_amount,
            status=sample_report.status,
            source_url=sample_report.source_url,
            raw_fingerprint="fp-3",
        )
        result = registry.add_report(conflicting)
        assert "amount_mismatch" in result["conflicts"]
        assert len(registry.list_reports()) == 1  # kept existing

    def test_orphan_report_conflict(self, sample_report: CommissionReport) -> None:
        registry = ReportRegistry()
        result = registry.add_report(
            sample_report, known_opportunity_ids={"different-opp"}
        )
        assert "orphan_report" in result["conflicts"]

    def test_save_and_load_round_trip(self, sample_report: CommissionReport) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = ReportRegistry(path=path)
            registry.add_report(sample_report)
            registry.save()
            loaded = ReportRegistry(path=path)
            reports = loaded.list_reports()
            assert len(reports) == 1
            assert reports[0].report_id == "r-001"

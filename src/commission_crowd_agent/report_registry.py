"""In-memory registry for fetched commission reports with durable JSON backing.

The registry deduplicates by ``report_hash`` and detects basic conflicts such as
amount mismatches, period overlaps, and orphan reports (reports whose
opportunity is not known to the caller).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_PATH: Path = Path("/home/ubuntu/hermes-control/reports/cca_report_registry.json")


@dataclass
class CommissionReport:
    """A single commission report record.

    Fields are intentionally broad so the registry can hold reports that
    originate from API responses, browser scraping, or manual ingestion.
    """

    report_id: str = ""
    opportunity_id: str = ""
    principal_name: str = ""
    report_type: str = ""
    period_start: date | None = None
    period_end: date | None = None
    currency: str = "USD"
    gross_amount: float = 0.0
    net_amount: float = 0.0
    status: str = "pending"
    source_url: str = ""
    raw_fingerprint: str = ""
    report_hash: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    requires_review: bool = False

    def __post_init__(self) -> None:
        """Ensure ``report_hash`` is materialised if empty."""
        if not self.report_hash:
            self.report_hash = compute_report_hash(self)


def compute_report_hash(report: CommissionReport) -> str:
    """Return a stable SHA-256 hash over the identifying fields of a report.

    The hash deliberately excludes monetary amounts, ``report_id``,
    ``fetched_at``, ``provenance`` timestamps, ``raw_fingerprint`` and
    ``requires_review`` so that two logically identical reports collide and can
    be deduplicated, while amount changes surface as ``amount_mismatch``
    conflicts.  ``raw_fingerprint`` is excluded because two scrapes of the same
    row may produce slightly different raw cell strings while still describing
    the same underlying report.
    """
    payload: dict[str, Any] = {
        "opportunity_id": report.opportunity_id,
        "principal_name": report.principal_name,
        "report_type": report.report_type,
        "period_start": report.period_start.isoformat() if report.period_start else "",
        "period_end": report.period_end.isoformat() if report.period_end else "",
        "currency": report.currency,
        "status": report.status,
        "source_url": report.source_url,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Conflict:
    """A single conflict record produced by the registry."""

    conflict_type: str
    report_hash: str
    report_id: str
    details: dict[str, Any] = field(default_factory=dict)


class ReportRegistry:
    """Hold, deduplicate, and persist ``CommissionReport`` records.

    The registry is backed by a JSON file and is safe to create even when the
    file does not yet exist.  All mutations return structured metadata so
    callers can audit what happened without re-reading the file.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_REGISTRY_PATH
        self._reports: dict[str, CommissionReport] = {}
        self._conflicts: list[Conflict] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load existing reports from disk, if any."""
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for item in raw.get("reports", []):
            try:
                report = _report_from_dict(item)
                self._reports[report.report_hash] = report
            except (KeyError, ValueError, TypeError):
                continue

    def save(self) -> dict[str, Any]:
        """Persist the current registry to disk.

        Returns a structured summary with the destination path and report count.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": datetime.now(UTC).isoformat(),
            "path": str(self.path),
            "count": len(self._reports),
            "reports": [_report_to_dict(r) for r in self._reports.values()],
            "conflicts": [
                {
                    "conflict_type": c.conflict_type,
                    "report_hash": c.report_hash,
                    "report_id": c.report_id,
                    "details": c.details,
                }
                for c in self._conflicts
            ],
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return {"ok": True, "path": str(self.path), "count": len(self._reports)}

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def add_report(
        self,
        report: CommissionReport,
        *,
        known_opportunity_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Add a report to the registry, deduplicating and checking conflicts.

        Returns metadata describing the action taken and any conflicts found.
        """
        if not report.report_hash:
            report.report_hash = compute_report_hash(report)

        existing = self._reports.get(report.report_hash)
        conflicts = self._detect_conflicts(
            report, existing_report=existing, known_opportunity_ids=known_opportunity_ids
        )
        self._conflicts.extend(conflicts)

        action = "duplicate"
        if existing is not None:
            # Keep the most recent fetch time and merge provenance
            existing.fetched_at = max(existing.fetched_at, report.fetched_at)
            existing.provenance.update(report.provenance)
            if report.requires_review:
                existing.requires_review = True
        else:
            self._reports[report.report_hash] = report
            action = "added"

        return {
            "ok": True,
            "report_id": report.report_id,
            "report_hash": report.report_hash,
            "action": action,
            "conflicts": [c.conflict_type for c in conflicts],
            "count": len(self._reports),
        }

    def get_by_hash(self, report_hash: str) -> CommissionReport | None:
        """Return a report by its stable hash, if present."""
        return self._reports.get(report_hash)

    def list_reports(
        self,
        *,
        opportunity_id: str | None = None,
        report_type: str | None = None,
        status: str | None = None,
        requires_review: bool | None = None,
    ) -> list[CommissionReport]:
        """Return reports filtered by the supplied criteria."""
        result = list(self._reports.values())
        if opportunity_id is not None:
            result = [r for r in result if r.opportunity_id == opportunity_id]
        if report_type is not None:
            result = [r for r in result if r.report_type == report_type]
        if status is not None:
            result = [r for r in result if r.status == status]
        if requires_review is not None:
            result = [r for r in result if r.requires_review == requires_review]
        return result

    def deduplicate(self) -> dict[str, Any]:
        """Recompute hashes and remove exact duplicates.

        Returns a summary of removed and retained counts.
        """
        before = len(self._reports)
        recomputed: dict[str, CommissionReport] = {}
        for report in self._reports.values():
            report.report_hash = compute_report_hash(report)
            existing = recomputed.get(report.report_hash)
            if existing is None:
                recomputed[report.report_hash] = report
            else:
                existing.fetched_at = max(existing.fetched_at, report.fetched_at)
                existing.provenance.update(report.provenance)
                if report.requires_review:
                    existing.requires_review = True
        removed = before - len(recomputed)
        self._reports = recomputed
        return {"before": before, "after": len(self._reports), "removed": removed}

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def _detect_conflicts(
        self,
        report: CommissionReport,
        *,
        existing_report: CommissionReport | None,
        known_opportunity_ids: set[str] | None,
    ) -> list[Conflict]:
        conflicts: list[Conflict] = []

        if existing_report is not None and (
            existing_report.gross_amount != report.gross_amount
            or existing_report.net_amount != report.net_amount
        ):
                conflicts.append(
                    Conflict(
                        conflict_type="amount_mismatch",
                        report_hash=report.report_hash,
                        report_id=report.report_id,
                        details={
                            "existing_gross": existing_report.gross_amount,
                            "incoming_gross": report.gross_amount,
                            "existing_net": existing_report.net_amount,
                            "incoming_net": report.net_amount,
                        },
                    )
                )

        if report.period_start and report.period_end:
            for other in self._reports.values():
                if other.report_hash == report.report_hash:
                    continue
                if other.opportunity_id != report.opportunity_id:
                    continue
                if other.report_type != report.report_type:
                    continue
                if other.period_start is None or other.period_end is None:
                    continue
                if _periods_overlap(
                    report.period_start, report.period_end, other.period_start, other.period_end
                ):
                    conflicts.append(
                        Conflict(
                            conflict_type="period_overlap",
                            report_hash=report.report_hash,
                            report_id=report.report_id,
                            details={
                                "other_report_id": other.report_id,
                                "other_hash": other.report_hash,
                                "period": f"{report.period_start}..{report.period_end}",
                                "other_period": f"{other.period_start}..{other.period_end}",
                            },
                        )
                    )

        if (
            known_opportunity_ids is not None
            and report.opportunity_id
            and report.opportunity_id not in known_opportunity_ids
        ):
            conflicts.append(
                Conflict(
                    conflict_type="orphan_report",
                    report_hash=report.report_hash,
                    report_id=report.report_id,
                    details={"opportunity_id": report.opportunity_id},
                )
            )

        return conflicts

    @property
    def conflicts(self) -> list[Conflict]:
        """All conflicts detected during the lifetime of this registry instance."""
        return list(self._conflicts)

    @property
    def reports(self) -> dict[str, CommissionReport]:
        """Map of report_hash -> report."""
        return dict(self._reports)

    def summary(self) -> dict[str, Any]:
        """Return a human-readable summary of registry state."""
        return {
            "count": len(self._reports),
            "conflicts": len(self._conflicts),
            "path": str(self.path),
            "report_types": sorted({r.report_type for r in self._reports.values()}),
            "opportunity_ids": sorted(
                {r.opportunity_id for r in self._reports.values() if r.opportunity_id}
            ),
            "requires_review": sum(1 for r in self._reports.values() if r.requires_review),
        }

    # ------------------------------------------------------------------
    # Pydantic schema bridge (additive, Sprint 3 §4.2)
    # ------------------------------------------------------------------

    def add_report_schema(
        self,
        schema: Any,
        *,
        known_opportunity_ids: set[str] | None = None,
        source: str = "report_registry",
        route: str = "schema_bridge",
    ) -> dict[str, Any]:
        """Add a report supplied as a Pydantic ``CommissionReportSchema``.

        Converts the schema to a :class:`CommissionReport` via
        :func:`schema_to_report`, appends a registry-ingestion provenance entry
        produced by the provenance engine (:func:`build_provenance`), and
        delegates to :meth:`add_report`.  Existing ``add_report`` behaviour is
        unchanged.
        """
        from .models.report_schema import build_provenance, schema_to_report

        report = schema_to_report(schema)
        # Record that the row passed through the schema bridge.  Stored under
        # the ``_entries`` key so the round-trip stays lossless.
        entries: list[dict[str, Any]] = list(report.provenance.get("_entries", []))
        entries.append(build_provenance(source=source, route=route).model_dump(mode="json"))
        report.provenance = {"_entries": entries}
        return self.add_report(report, known_opportunity_ids=known_opportunity_ids)

    def to_schemas(self) -> list[Any]:
        """Return every stored report as a ``CommissionReportSchema``.

        The conversion is lossless: ``schema_to_report(report_to_schema(r))``
        preserves ``report_hash``, monetary amounts, and provenance entries.
        """
        from .models.report_schema import report_to_schema

        return [report_to_schema(report) for report in self._reports.values()]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _date_from_value(value: Any) -> date | None:
    """Parse a date from ISO format string, date object, or None."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"Cannot parse date from {value!r}")


def _datetime_from_value(value: Any) -> datetime:
    """Parse a datetime from ISO format string, datetime object, or None."""
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"Cannot parse datetime from {value!r}")


def _report_from_dict(data: dict[str, Any]) -> CommissionReport:
    """Rebuild a ``CommissionReport`` from a dictionary."""
    return CommissionReport(
        report_id=data.get("report_id", ""),
        opportunity_id=data.get("opportunity_id", ""),
        principal_name=data.get("principal_name", ""),
        report_type=data.get("report_type", ""),
        period_start=_date_from_value(data.get("period_start")),
        period_end=_date_from_value(data.get("period_end")),
        currency=data.get("currency", "USD"),
        gross_amount=float(data.get("gross_amount", 0.0)),
        net_amount=float(data.get("net_amount", 0.0)),
        status=data.get("status", "pending"),
        source_url=data.get("source_url", ""),
        raw_fingerprint=data.get("raw_fingerprint", ""),
        report_hash=data.get("report_hash", ""),
        provenance=data.get("provenance", {}),
        fetched_at=_datetime_from_value(data.get("fetched_at")),
        requires_review=bool(data.get("requires_review", False)),
    )


def _report_to_dict(report: CommissionReport) -> dict[str, Any]:
    """Serialise a ``CommissionReport`` to a plain dictionary."""
    return {
        "report_id": report.report_id,
        "opportunity_id": report.opportunity_id,
        "principal_name": report.principal_name,
        "report_type": report.report_type,
        "period_start": report.period_start.isoformat() if report.period_start else None,
        "period_end": report.period_end.isoformat() if report.period_end else None,
        "currency": report.currency,
        "gross_amount": report.gross_amount,
        "net_amount": report.net_amount,
        "status": report.status,
        "source_url": report.source_url,
        "raw_fingerprint": report.raw_fingerprint,
        "report_hash": report.report_hash,
        "provenance": report.provenance,
        "fetched_at": report.fetched_at.isoformat(),
        "requires_review": report.requires_review,
    }


def _periods_overlap(
    start_a: date, end_a: date, start_b: date, end_b: date
) -> bool:
    """Return True if two inclusive date ranges share at least one day."""
    return start_a <= end_b and start_b <= end_a

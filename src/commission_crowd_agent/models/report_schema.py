"""Pydantic v2 schemas for commission reports and the provenance engine.

This module mirrors the storage schema defined in
``docs/sprint_3_specifications.md`` §4.2 and provides a lossless bridge to the
existing :class:`commission_crowd_agent.report_registry.CommissionReport`
dataclass that remains the on-disk source of truth.

Public symbols
--------------
- :class:`ReportType` / :class:`ReportStatus`  -- enumerations from §4.2.
- :class:`ReportProvenanceEntry`               -- ``{source, route, retrieved_at}``.
- :class:`CommissionReportSchema`              -- full Pydantic model with
  validators for ISO dates, ISO 4217 currency codes, finite amounts, and a
  computed ``report_hash``.
- :func:`build_provenance`                     -- provenance-engine helper.
- :func:`compute_schema_hash`                  -- hash equivalent of
  :func:`compute_report_hash` for a schema instance.
- :func:`report_to_schema` / :func:`schema_to_report` -- lossless interconversion
  with the legacy dataclass.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..report_registry import CommissionReport, compute_report_hash

# ---------------------------------------------------------------------------
# Enumerations (spec §4.2)
# ---------------------------------------------------------------------------


class ReportType(StrEnum):
    """Canonical commission report types."""

    earnings = "earnings"
    applications = "applications"
    payouts = "payouts"
    clawbacks = "clawbacks"
    performance = "performance"


class ReportStatus(StrEnum):
    """Canonical commission report statuses."""

    confirmed = "confirmed"
    pending = "pending"
    estimated = "estimated"
    disputed = "disputed"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class ReportProvenanceEntry(BaseModel):
    """A single provenance record describing where and when a report was sourced.

    Matches the ``{source, route, retrieved_at}`` pattern referenced in §4.2
    and mirrors :class:`OpportunityStateRecord` provenance entries.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Origin of the report (fetcher, API, manual...).")
    route: str = Field(
        description="Acquisition channel, e.g. 'browser' or 'api'.",
    )
    retrieved_at: datetime = Field(
        description="UTC timestamp at which the report was retrieved.",
    )

    @field_validator("source", "route")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("source and route must be non-blank strings")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def build_provenance(
    source: str,
    route: str,
    retrieved_at: datetime | None = None,
) -> ReportProvenanceEntry:
    """Build a :class:`ReportProvenanceEntry` with a UTC ``retrieved_at``.

    If ``retrieved_at`` is omitted the current UTC time is used.  This is the
    provenance-engine entry point used by the fetcher and the registry bridge.
    """
    return ReportProvenanceEntry(
        source=source,
        route=route,
        retrieved_at=retrieved_at or datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Canonical schema
# ---------------------------------------------------------------------------

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_ENTRIES_KEY = "_entries"


class CommissionReportSchema(BaseModel):
    """Pydantic v2 mirror of the §4.2 report storage schema.

    The ``report_hash`` is computed automatically (matching
    :func:`compute_report_hash`) when left empty.  Validators enforce ISO
    dates, ISO 4217 currency codes, finite monetary amounts, and period
    ordering.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    report_id: str = Field(default="", description="Stable UUIDv4 primary key.")
    opportunity_id: str = Field(default="", description="Foreign key to the opportunity.")
    principal_name: str = Field(default="", description="Denormalized principal name.")
    report_type: ReportType = Field(description="Canonical report type.")
    period_start: date | None = Field(
        default=None, description="Inclusive period start (ISO date)."
    )
    period_end: date | None = Field(
        default=None, description="Inclusive period end (ISO date)."
    )
    currency: str = Field(default="USD", description="ISO 4217 currency code.")
    gross_amount: float = Field(default=0.0, description="Reported gross commission/earning.")
    net_amount: float = Field(default=0.0, description="Net amount after platform fees.")
    status: ReportStatus = Field(default=ReportStatus.pending, description="Report status.")
    source_url: str = Field(default="", description="URL the row was sourced from.")
    raw_fingerprint: str = Field(default="", description="SHA-256 of the raw extracted cells.")
    report_hash: str = Field(default="", description="Deterministic deduplication hash.")
    provenance: list[ReportProvenanceEntry] = Field(default_factory=list)
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC ingestion timestamp.",
    )
    requires_review: bool = Field(
        default=False, description="True if row conflicts or fails validation.",
    )

    # -- validators -------------------------------------------------------

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        if not _CURRENCY_RE.match(value):
            raise ValueError(
                f"currency must be an ISO 4217 code (3 uppercase letters), got {value!r}"
            )
        return value

    @field_validator("gross_amount", "net_amount")
    @classmethod
    def _validate_amount(cls, value: float) -> float:
        # Reject NaN / inf but allow negative values (clawbacks can be negative).
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("monetary amounts must be finite numbers")
        return float(value)

    @field_validator("period_start", "period_end", "fetched_at")
    @classmethod
    def _validate_iso_temporal(cls, value: date | datetime | None) -> date | datetime | None:
        # Pydantic already parsed the value into a date/datetime; this validator
        # exists to surface a clear error for malformed ISO inputs and to
        # guarantee timezone-aware datetimes.
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @model_validator(mode="after")
    def _validate_period_order_and_hash(self) -> Self:
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_start > self.period_end
        ):
            raise ValueError(
                f"period_start ({self.period_start}) must not follow "
                f"period_end ({self.period_end})"
            )
        if not self.report_hash:
            self.report_hash = compute_schema_hash(self)
        return self


# ---------------------------------------------------------------------------
# Hashing (mirrors report_registry.compute_report_hash)
# ---------------------------------------------------------------------------


def _enum_value(value: Any) -> str:
    """Return the underlying string value for a ReportType/ReportStatus enum."""
    if isinstance(value, StrEnum):
        return str(value.value)
    return str(value)


def compute_schema_hash(schema: CommissionReportSchema) -> str:
    """Return the deterministic deduplication hash for a schema instance.

    The payload is identical to :func:`compute_report_hash` applied to the
    equivalent :class:`CommissionReport` -- it excludes monetary amounts,
    ``report_id``, ``fetched_at``, ``provenance``, ``raw_fingerprint`` and
    ``requires_review`` so that logically identical reports collide while
    amount changes surface as ``amount_mismatch`` conflicts.
    """
    payload: dict[str, Any] = {
        "opportunity_id": schema.opportunity_id,
        "principal_name": schema.principal_name,
        "report_type": _enum_value(schema.report_type),
        "period_start": schema.period_start.isoformat() if schema.period_start else "",
        "period_end": schema.period_end.isoformat() if schema.period_end else "",
        "currency": schema.currency,
        "status": _enum_value(schema.status),
        "source_url": schema.source_url,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Bridge helpers (lossless interconversion with the legacy dataclass)
# ---------------------------------------------------------------------------


def _parse_datetime(value: Any) -> datetime:
    """Parse a datetime from an ISO string, datetime, or None (defaults to now)."""
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    raise ValueError(f"Cannot parse datetime from {value!r}")


def _provenance_dict_to_entries(provenance: Any) -> list[ReportProvenanceEntry]:
    """Convert a legacy dataclass ``provenance`` dict into schema entries.

    The bridge stores structured entries under the ``_entries`` key so that a
    schema->report->schema round-trip is lossless.  Legacy flat dicts produced
    by :mod:`report_fetcher` (with ``fetcher`` / ``method`` / ``fetched_at``
    keys) are adapted into a single synthetic entry.
    """
    if not isinstance(provenance, dict) or not provenance:
        return []
    raw_entries = provenance.get(_ENTRIES_KEY)
    if isinstance(raw_entries, list):
        return [ReportProvenanceEntry.model_validate(entry) for entry in raw_entries]
    # Legacy flat dict -- synthesise a single provenance entry.
    source = str(provenance.get("fetcher") or provenance.get("source") or "unknown")
    route = str(provenance.get("method") or provenance.get("route") or "unknown")
    retrieved_at = _parse_datetime(
        provenance.get("fetched_at") or provenance.get("retrieved_at")
    )
    return [ReportProvenanceEntry(source=source, route=route, retrieved_at=retrieved_at)]


def report_to_schema(report: CommissionReport) -> CommissionReportSchema:
    """Convert a :class:`CommissionReport` dataclass into a schema instance.

    The original ``report_hash`` is preserved when present so the bridge is
    lossless regardless of which hash version produced the source record.
    """
    return CommissionReportSchema(
        report_id=report.report_id,
        opportunity_id=report.opportunity_id,
        principal_name=report.principal_name,
        report_type=ReportType(report.report_type) if report.report_type else ReportType.earnings,
        period_start=report.period_start,
        period_end=report.period_end,
        currency=report.currency,
        gross_amount=report.gross_amount,
        net_amount=report.net_amount,
        status=ReportStatus(report.status) if report.status else ReportStatus.pending,
        source_url=report.source_url,
        raw_fingerprint=report.raw_fingerprint,
        report_hash=report.report_hash,
        provenance=_provenance_dict_to_entries(report.provenance),
        fetched_at=report.fetched_at,
        requires_review=report.requires_review,
    )


def schema_to_report(schema: CommissionReportSchema) -> CommissionReport:
    """Convert a schema instance back into a :class:`CommissionReport` dataclass.

    Provenance entries are stored under the ``_entries`` key of the dataclass
    ``provenance`` dict so that
    ``schema_to_report(report_to_schema(r)).provenance`` round-trips losslessly.
    """
    report = CommissionReport(
        report_id=schema.report_id,
        opportunity_id=schema.opportunity_id,
        principal_name=schema.principal_name,
        report_type=_enum_value(schema.report_type),
        period_start=schema.period_start,
        period_end=schema.period_end,
        currency=schema.currency,
        gross_amount=schema.gross_amount,
        net_amount=schema.net_amount,
        status=_enum_value(schema.status),
        source_url=schema.source_url,
        raw_fingerprint=schema.raw_fingerprint,
        # ``__post_init__`` skips rehashing when ``report_hash`` is non-empty.
        report_hash=schema.report_hash or compute_schema_hash(schema),
        provenance={
            _ENTRIES_KEY: [entry.model_dump(mode="json") for entry in schema.provenance],
        },
        fetched_at=schema.fetched_at,
        requires_review=schema.requires_review,
    )
    return report



# ---------------------------------------------------------------------------
# Registry snapshot + metadata engine
# ---------------------------------------------------------------------------


class ReportRegistrySnapshot(BaseModel):
    """Serialisable snapshot of an entire ``ReportRegistry``.

    Mirrors the JSON structure written by ``ReportRegistry.save()`` and is the
    typed interchange format for downstream analytics or operator dashboards.
    """

    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    path: str = ""
    count: int = 0
    reports: list[CommissionReportSchema] = Field(default_factory=list)
    conflicts: list[Any] = Field(default_factory=list)


class ReportMetadataEngine:
    """Validate and enrich report metadata, including provenance and lineage hashes."""

    @staticmethod
    def validate_provenance(
        provenance: list[dict[str, Any]] | dict[str, Any] | None,
    ) -> list[ReportProvenanceEntry]:
        """Normalise provenance data into a list of typed entries.

        Accepts legacy flat dictionaries, already-typed entries, or raw lists.
        """
        if provenance is None:
            return []
        if isinstance(provenance, dict):
            provenance = [provenance]
        entries: list[ReportProvenanceEntry] = []
        for item in provenance:
            if isinstance(item, ReportProvenanceEntry):
                entries.append(item)
            elif isinstance(item, dict):
                entries.append(ReportProvenanceEntry(**item))
            else:
                entries.append(ReportProvenanceEntry(source=str(item), route="unknown"))
        return entries

    @staticmethod
    def compute_report_hash(report: CommissionReportSchema | dict[str, Any]) -> str:
        """Compute the canonical deduplication hash for a schema or raw dict."""
        if isinstance(report, CommissionReportSchema):
            return compute_schema_hash(report)
        # Raw dict path for callers without a schema instance.
        data = dict(report)
        period_start = data.get("period_start")
        period_end = data.get("period_end")
        payload: dict[str, Any] = {
            "opportunity_id": str(data.get("opportunity_id", "")),
            "principal_name": str(data.get("principal_name", "")),
            "report_type": _enum_value(data.get("report_type", "")),
            "period_start": (
                period_start.isoformat()
                if isinstance(period_start, date)
                else str(period_start or "")
            ),
            "period_end": (
                period_end.isoformat()
                if isinstance(period_end, date)
                else str(period_end or "")
            ),
            "currency": str(data.get("currency", "USD")),
            "status": _enum_value(data.get("status", "pending")),
            "source_url": str(data.get("source_url", "")),
            "raw_fingerprint": str(data.get("raw_fingerprint", "")),
        }
        canonical = json.dumps(
            payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def snapshot_from_dict(data: dict[str, Any]) -> ReportRegistrySnapshot:
        """Rebuild a typed registry snapshot from a raw dictionary."""
        return ReportRegistrySnapshot(**data)


__all__ = [
    "CommissionReportSchema",
    "ReportMetadataEngine",
    "ReportProvenanceEntry",
    "ReportRegistrySnapshot",
    "ReportStatus",
    "ReportType",
    "build_provenance",
    "compute_report_hash",
    "compute_schema_hash",
    "report_to_schema",
    "schema_to_report",
]

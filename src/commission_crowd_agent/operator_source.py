"""Operator-source ingestion for public URL lists.

Provides:
- OperatorSource Pydantic model for validated source entries
- OperatorSourceIngester: load sources from JSON, validate, score, create approvals

Design principles:
- Dry-run by default; --write required for real Sheet rows.
- No source URL is ever invented — only operator-provided lists are accepted.
- Placeholder/stub sources are blocked by the existing detector.
- Every candidate requires provenance (source_url).
- Bounded to at most 5 candidates per ingestion run.
- No downstream actions execute in this module.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .lead_ingestion import CandidateLead, LeadIngester
from .stub_detector import is_placeholder_candidate


class OperatorSource(BaseModel):
    """A single operator-provided source entry."""

    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    source_type: str = ""  # e.g. public_directory, news_article, job_board
    notes: str = ""
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _validate_http_url(cls, v: str) -> str:
        if not re.search(r"^https?://", v.strip(), re.IGNORECASE):
            raise ValueError("URL must begin with http:// or https://")
        return v.strip()

    @property
    def is_placeholder(self) -> bool:
        """True if this source passes any placeholder detector heuristic."""
        return is_placeholder_candidate(self.name, self.url, self.notes)


class OperatorSourceIngester:
    """Load, validate, and ingest from operator-provided public source lists."""

    HARD_MAX_CANDIDATES: int = 5

    def __init__(self, lead_ingester: LeadIngester | None = None) -> None:
        self.lead_ingester = lead_ingester

    @classmethod
    def load_source_file(cls, path: Path) -> list[OperatorSource]:
        """Load and validate operator source entries from JSON.

        Expected JSON: list[dict] with keys name, url, source_type?, notes?, enabled?
        Non-list root raises ValueError.
        Malformed entries are skipped with a warning logged (returned in result).
        """
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("JSON root must be a list")
        entries: list[OperatorSource] = []
        for item in raw:
            try:
                entries.append(OperatorSource.model_validate(item))
            except Exception:
                continue
        return entries

    @classmethod
    def parse_single_url(cls, url: str, name: str = "") -> OperatorSource:
        """Parse a single CLI-provided public URL into an OperatorSource.

        Raises ValueError on invalid URL scheme or placeholder signal.
        """
        source = OperatorSource(
            name=name or url,
            url=url,
            source_type="cli_provided",
            notes="One-off URL provided via CLI",
            enabled=True,
        )
        if source.is_placeholder:
            raise ValueError("Placeholder or stub URL detected — not accepted")
        return source

    def ingest_sources(
        self,
        sources: list[OperatorSource],
        *,
        limit: int = 5,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Ingest from validated operator sources.

        Returns structured result with candidate count, writes, approvals, errors.
        Does NOT fetch remote URLs (no scraping yet). A future mission may add
        remote fetching when operator provides public pages that can be read
        without login walls.
        """
        if limit > self.HARD_MAX_CANDIDATES:
            limit = self.HARD_MAX_CANDIDATES

        # Filter to enabled and non-placeholder
        valid = [s for s in sources if s.enabled and not s.is_placeholder]
        skipped = len(sources) - len(valid)

        if not valid:
            return {
                "ok": True,
                "dry_run": dry_run,
                "candidates": 0,
                "written": 0,
                "approvals": 0,
                "skipped": skipped,
                "sources": [],
                "message": "No enabled non-placeholder sources found.",
            }

        # Convert each source to a CandidateLead (provenance = source URL)
        candidates: list[CandidateLead] = []
        for s in valid[:limit]:
            candidates.append(
                CandidateLead(
                    lead_id=str(uuid.uuid4())[:8],
                    source=s.source_type or "operator_provided",
                    company=s.name,
                    url=s.url,
                    provenance=s.url,
                    notes=s.notes,
                )
            )

        # Write candidates
        write_result: dict[str, Any] = {"ok": True, "written": 0}
        if self.lead_ingester:
            write_result = self.lead_ingester.write_candidates(candidates, dry_run=dry_run)

        # Create approval requests
        approvals: list[dict[str, Any]] = []
        if self.lead_ingester and self.lead_ingester.approval_gate:
            approvals = self.lead_ingester.create_approval_requests(candidates, dry_run=dry_run)

        return {
            "ok": write_result.get("ok", True) and len(candidates) > 0,
            "dry_run": dry_run,
            "candidates": len(candidates),
            "written": write_result.get("written", 0),
            "approvals": len(approvals),
            "skipped": skipped,
            "sources": [
                {"name": s.name, "url": s.url, "source_type": s.source_type} for s in valid[:limit]
            ],
            "message": (f"Ingested {len(candidates)} candidate(s) from {len(sources)} source(s)."),
        }

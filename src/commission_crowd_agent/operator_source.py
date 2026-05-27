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

import httpx
from pydantic import BaseModel, Field, field_validator

from .directory_extractor import extract_candidates
from .lead_ingestion import CandidateLead, LeadIngester
from .stub_detector import is_placeholder_candidate


class OperatorSource(BaseModel):
    """A single operator-provided source entry."""

    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    source_type: str = ""  # e.g. public_directory, news_article, job_board
    notes: str = ""
    enabled: bool = True
    per_source_limit: int = 0  # 0 = no per-source cap (falls back to global limit)

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

    def _fetch_html(self, url: str) -> str:
        """Fetch public HTML with bounded timeout and clear UA."""
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; CCA-Bot/1.0; +https://syntaxis-labs.dev/bot-info)",
            "Accept": "text/html",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def _get_existing_urls(self) -> set[str]:
        """Read existing lead URLs from the 'leads' tab for deduplication."""
        if not self.lead_ingester or not self.lead_ingester.sheets_adapter:
            return set()
        adapter = self.lead_ingester.sheets_adapter
        result = adapter.read_last_rows("leads", count=200)
        if not result.get("ok"):
            return set()
        rows = result.get("rows", [])
        if not rows:
            return set()
        # Determine schema: header row present or not
        # If first row starts with 'lead_id' treat as header
        data_rows = rows[1:] if rows[0] and rows[0][0] == "lead_id" else rows
        existing: set[str] = set()
        for row in data_rows:
            if len(row) > 4 and row[4]:
                existing.add(str(row[4]).strip())
            if len(row) > 3 and row[3]:
                existing.add(str(row[3]).strip())
        return existing

    def ingest_sources(
        self,
        sources: list[OperatorSource],
        *,
        limit: int = 5,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Ingest from validated operator sources with per-source caps.

        1. Fetch each source page HTML (public read-only).
        2. Extract candidate companies with per-source_max limit.
        3. If extraction yields zero, fall back to source-page-as-lead.
        4. Dedup against existing leads.
        5. Respect global limit across all sources.
        6. Write candidates and create pending approvals.
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

        # Read existing URLs for deduplication (if we have an adapter)
        existing_urls = self._get_existing_urls()

        candidates: list[CandidateLead] = []
        source_reports: list[dict[str, Any]] = []

        for s in valid:
            if len(candidates) >= limit:
                source_reports.append(
                    {
                        "name": s.name,
                        "status": "skipped_global_cap",
                        "extracted": 0,
                        "duplicates_skipped": 0,
                        "placeholders_blocked": 0,
                        "written": 0,
                    }
                )
                continue

            # Per-source cap: 0 means "fall back to global limit"
            per_cap = s.per_source_limit if s.per_source_limit > 0 else limit
            remaining = limit - len(candidates)
            source_max = min(per_cap, remaining)

            extracted_raw: list[Any] = []
            status = "error"
            error_msg = ""
            try:
                html = self._fetch_html(s.url)
                extracted_raw = extract_candidates(
                    html,
                    source_url=s.url,
                    source_name=s.name,
                    source_type=s.source_type,
                    max_candidates=source_max,
                )
                extracted = [c.to_dict() for c in extracted_raw]
                status = "success" if extracted else "fallback"
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                status = "error"
                extracted = []

            source_extracted = 0
            source_duplicates = 0
            source_placeholders = 0
            source_written = 0

            if extracted:
                for ec in extracted:
                    if len(candidates) >= limit:
                        break
                    if source_written >= source_max:
                        break
                    candidate_url = ec.get("url", "")
                    if candidate_url in existing_urls:
                        source_duplicates += 1
                        continue
                    # Block placeholders
                    if is_placeholder_candidate(
                        name=ec.get("company", ""),
                        url=candidate_url,
                        notes=ec.get("notes", ""),
                    ):
                        source_placeholders += 1
                        continue

                    extraction_method = ec.get("extraction_method", "")
                    extraction_confidence = ec.get("extraction_confidence", "")
                    extra_notes = ec.get("notes", "")
                    candidates.append(
                        CandidateLead(
                            lead_id=ec["lead_id"],
                            source=ec.get("source_type") or s.source_type or "operator_provided",
                            company=ec["company"],
                            url=candidate_url,
                            provenance=s.url,
                            notes=(
                                f"Extraction: {extraction_method}"
                                f" (confidence={extraction_confidence})."
                                f" {extra_notes}"
                            ),
                        )
                    )
                    source_extracted += 1
                    source_written += 1
                    if candidate_url:
                        existing_urls.add(candidate_url)
            elif status != "error":
                # Fallback: treat source page itself as a lead (only if fetch succeeded)
                if len(candidates) < limit and s.url not in existing_urls:
                    candidates.append(
                        CandidateLead(
                            lead_id=str(uuid.uuid4())[:8],
                            source=s.source_type or "operator_provided",
                            company=s.name,
                            url=s.url,
                            provenance=s.url,
                            notes=s.notes
                            or "Fallback source-page lead (no child candidates extracted).",
                        )
                    )
                    source_written += 1
                    existing_urls.add(s.url)
                    status = "fallback"
                elif s.url in existing_urls:
                    source_duplicates += 1

            source_reports.append(
                {
                    "name": s.name,
                    "status": status,
                    "error": error_msg if status == "error" else "",
                    "extracted": source_extracted,
                    "duplicates_skipped": source_duplicates,
                    "placeholders_blocked": source_placeholders,
                    "written": source_written,
                    "per_source_limit": per_cap,
                }
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
                {
                    "name": s.name,
                    "url": s.url,
                    "source_type": s.source_type,
                    "per_source_limit": s.per_source_limit,
                }
                for s in valid
            ],
            "message": (f"Ingested {len(candidates)} candidate(s) from {len(sources)} source(s)."),
            "source_reports": source_reports,
        }

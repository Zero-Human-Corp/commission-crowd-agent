"""Lead ingestion service for read-only candidate discovery.

Provides:
- CandidateLead Pydantic model with provenance tracking
- LeadIngester: discover from search or JSON, write to Sheets, create approvals

Design principles:
- Dry-run by default; --write required for real Sheet rows.
- Never invent emails.
- Always record provenance (source URL or search query).
- Limit live discovery to small batches (≤5 per mission).
- Every written candidate gets a pending approval request.
- No downstream actions execute in this module.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .adapters import GoogleSheetsAdapter
    from .approval_gate import ApprovalGate


class CandidateLead(BaseModel):
    """A discovered candidate lead before it enters the pipeline."""

    lead_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    source: str = ""  # e.g. web_search, manual, referral
    full_name: str = ""
    company: str = ""
    url: str = ""
    email: str = ""  # Only if publicly discovered; never invented
    status: str = "discovered"  # discovered | needs_review | qualified | rejected
    created_at: datetime = Field(default_factory=datetime.utcnow)
    notes: str = ""
    provenance: str = ""  # Search query or source URL that produced this lead

    def to_sheets_lead_row(self) -> list[str]:
        """Serialise to ordered list[str] aligned with adapter SCHEMA['leads']."""
        return [
            self.lead_id,
            self.created_at.isoformat() if self.created_at else "",
            self.source,
            self.url,  # source_url
            self.company,
            self.full_name,
            self.email,
            "",  # role_title
            "",  # market
            "",  # country
            "",  # problem_signal
            "",  # commission_signal
            "",  # fit_score
            self.status,
            self.notes,
        ]


class LeadIngester:
    """Discover, normalise, and persist candidate leads with full provenance."""

    def __init__(
        self,
        sheets_adapter: GoogleSheetsAdapter | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self.sheets_adapter = sheets_adapter
        self.approval_gate = approval_gate

    def discover_from_json(self, path: Path) -> list[CandidateLead]:
        """Load candidates from a local JSON file.

        Expected JSON shape: list[dict] with keys:
            company, full_name?, url?, email?, source?, notes?, provenance?
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("JSON root must be a list")
        candidates: list[CandidateLead] = []
        for raw in data[:5]:  # Hard safety cap
            candidates.append(
                CandidateLead(
                    source=raw.get("source", "manual"),
                    company=raw.get("company", ""),
                    full_name=raw.get("full_name", ""),
                    url=raw.get("url", ""),
                    email=raw.get("email", ""),
                    status=raw.get("status", "discovered"),
                    notes=raw.get("notes", ""),
                    provenance=raw.get("provenance", str(path)),
                )
            )
        return candidates

    def discover_from_search(
        self,
        query: str,
        *,
        limit: int = 3,
    ) -> list[CandidateLead]:
        """Discover candidates via public web search.

        Currently a stub that returns an empty list.
        A future mission can wire real search (DuckDuckGo, Bing, etc.)
        while respecting robots.txt and rate limits.
        """
        return []

    def write_candidates(
        self,
        candidates: list[CandidateLead],
        *,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Write candidate leads to the 'leads' tab.

        Returns structured result with counts and any errors.
        """
        if self.sheets_adapter is None:
            return {"ok": False, "error": "No sheets adapter", "written": 0}
        if dry_run:
            return {"ok": True, "dry_run": True, "written": 0, "candidates": len(candidates)}

        # Validate header before any writes
        header_result = self.sheets_adapter.validate_tab_header("leads")
        if not header_result["ok"]:
            return {
                "ok": False,
                "error": f"Schema validation failed: {header_result['error']}",
                "written": 0,
            }

        written = 0
        errors: list[str] = []
        for c in candidates:
            result = self.sheets_adapter.append_row("leads", c.to_sheets_lead_row())
            if result.get("ok"):
                written += 1
            else:
                errors.append(result.get("error", "unknown"))
        return {"ok": len(errors) == 0, "written": written, "errors": errors}

    def create_approval_requests(
        self,
        candidates: list[CandidateLead],
        *,
        dry_run: bool = True,
    ) -> list[dict[str, Any]]:
        """Create pending approval requests for each candidate.

        Approval asks the operator to approve *research/scoring*, not outreach.
        """
        if self.approval_gate is None:
            return []
        results: list[dict[str, Any]] = []
        for c in candidates:
            action = f"Approve research/scoring for {c.company} ({c.full_name or 'no contact'})"
            req = self.approval_gate.create_approval(
                entity_type="lead",
                entity_id=c.lead_id,
                requested_action=action,
                risk_level="low",
                source_url=c.provenance,
                notes="",
                dry_run=dry_run,
            )
            results.append(
                {
                    "approval_id": req.approval_id,
                    "lead_id": c.lead_id,
                    "company": c.company,
                    "dry_run": dry_run,
                }
            )
        return results

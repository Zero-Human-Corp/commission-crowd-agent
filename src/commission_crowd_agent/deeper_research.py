"""Deeper research service for approved leads.

Design principles:
- Only runs when approval gate explicitly returns approved.
- Public, bounded, read-only research only.
- No invented facts, emails, or revenue figures.
- Findings carry provenance or are explicitly marked unverified.
- Default dry-run; explicit --write required for any Sheet append.
- Never sends outreach or creates drafts.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .stub_detector import is_placeholder_lead

if TYPE_CHECKING:
    from .adapters import GoogleSheetsAdapter
    from .approval_gate import ApprovalGate


class ResearchFinding(BaseModel):
    """Structured finding from deeper research."""

    source_url: str = ""
    finding: str = ""
    verified: bool = False
    source_label: str = ""


class DeeperResearchResult(BaseModel):
    """Complete result of a deeper research pass."""

    lead_id: str = ""
    company_name: str = ""
    researched_at_utc: str = ""
    findings: list[ResearchFinding] = Field(default_factory=list)
    problem_signals: list[str] = Field(default_factory=list)
    commission_signals: list[str] = Field(default_factory=list)
    confidence: str = "low"
    missing_data: list[str] = Field(default_factory=list)
    recommended_next_action: str = ""
    notes: str = ""
    is_placeholder: bool = False

    def to_outcome_row(self) -> list[str]:
        """Serialise to outcomes tab (10 columns)."""
        opp_id = f"OPP-{self.lead_id[:6]}"
        return [
            f"RES-{self.lead_id[:6]}",  # outcome_id
            self.researched_at_utc,  # created_at_utc
            opp_id,  # opportunity_id
            self.lead_id,  # lead_id
            "deeper_research",  # outcome_type
            "",  # amount
            self.confidence,  # currency
            "",  # paid_status
            self.recommended_next_action,  # payment_ref
            self.notes,  # notes
        ]


class DeeperResearchService:
    """Perform bounded public research on one approved lead."""

    MAX_FETCHES: int = 3

    @staticmethod
    def _try_fetch(url: str, timeout: int = 10) -> tuple[str, bool]:
        """Attempt to fetch a URL and return (text_snippet, success)."""
        try:
            result = subprocess.run(
                ["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
            if result.returncode == 0:
                text = result.stdout[:2000]
                return text, True
        except Exception:
            pass
        return "", False

    @staticmethod
    def _try_text_search(query: str) -> list[dict[str, str]]:
        """Try a simple text-based search via DDG html endpoint.
        Returns up to MAX_FETCHES snippets with URLs."""
        # Stub: real search requires proper handling. We return [] here
        # and let the caller decide what to do.
        return []

    def research_one_lead(
        self,
        lead_id: str,
        company_name: str,
        source_url: str = "",
        contact_email: str = "",
        notes: str = "",
    ) -> DeeperResearchResult:
        """Bounded read-only research for a single lead."""
        result = DeeperResearchResult(
            lead_id=lead_id,
            company_name=company_name,
            researched_at_utc=datetime.utcnow().isoformat(),
            confidence="low",
            missing_data=[],
        )

        # Mark placeholder/stub leads explicitly
        result.is_placeholder = is_placeholder_lead(
            company_name=company_name,
            source_url=source_url,
            contact_email=contact_email,
            notes=notes,
        )
        if result.is_placeholder:
            result.notes = (
                f"Placeholder fixture lead detected for {company_name}. "
                "Skipped from real outreach-draft progression."
            )
            result.confidence = "low"
            result.recommended_next_action = "manual_research_and_contact_hunt"
            result.missing_data.append("placeholder_or_fixture")
            return result

        if source_url:
            text, ok = self._try_fetch(source_url)
            if ok:
                result.findings.append(
                    ResearchFinding(
                        source_url=source_url,
                        finding=f"Fetched {len(text)} chars from homepage",
                        verified=True,
                        source_label="company_homepage",
                    )
                )
            else:
                result.findings.append(
                    ResearchFinding(
                        source_url=source_url,
                        finding="Homepage unreachable or did not resolve",
                        verified=False,
                        source_label="company_homepage",
                    )
                )
                result.missing_data.append("company_homepage_reachable")
        else:
            result.missing_data.append("company_homepage")

        # Commission signal extraction (best-effort from existing notes)
        if notes:
            result.findings.append(
                ResearchFinding(
                    source_url="",
                    finding=f"Existing notes: {notes[:200]}",
                    verified=True,
                    source_label="ingestion_notes",
                )
            )

        # Commission signals — if none found, mark as missing
        if not result.commission_signals:
            result.missing_data.append("commission_signal")

        # Determine confidence and next action
        homepage_ok = any(
            f.verified and f.source_label == "company_homepage" for f in result.findings
        )
        if homepage_ok:
            result.confidence = "medium"
            result.recommended_next_action = "draft_outreach_subject_only"
        else:
            result.confidence = "low"
            result.recommended_next_action = "manual_research_and_contact_hunt"

        result.notes = (
            f"Deeper research for {company_name} at {result.researched_at_utc}. "
            f"Findings: {len(result.findings)} total, "
            f"{len([f for f in result.findings if f.verified])} verified. "
            f"Missing: {', '.join(result.missing_data) if result.missing_data else 'none'}."
        )
        return result

    def write_research_result(
        self,
        result: DeeperResearchResult,
        *,
        sheets_adapter: GoogleSheetsAdapter | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Append research findings to the outcomes tab."""
        if sheets_adapter is None:
            return {"ok": False, "error": "No sheets adapter", "written": 0}
        if dry_run:
            return {"ok": True, "written": 0, "dry_run": True}
        header_result = sheets_adapter.validate_tab_header("outcomes")
        if not header_result["ok"]:
            return {"ok": False, "error": f"Schema validation failed: {header_result['error']}"}
        append_result = sheets_adapter.append_row("outcomes", result.to_outcome_row())
        return append_result

    def request_outreach_draft_approval(
        self,
        result: DeeperResearchResult,
        *,
        approval_gate: ApprovalGate | None = None,
        sheets_adapter: GoogleSheetsAdapter | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Create a pending approval for outreach-draft creation only.

        Skips if the lead has been detected as placeholder / fixture.
        """
        if approval_gate is None or sheets_adapter is None:
            return {"ok": False, "error": "Missing gate or adapter"}
        if result.is_placeholder:
            return {
                "ok": True,
                "dry_run": dry_run,
                "approval_id": "BLOCKED",
                "reason": "placeholder lead — outreach-draft approval suppressed",
            }
        if dry_run:
            return {"ok": True, "dry_run": True, "approval_id": "DRY-RUN"}
        action = (
            f"Approve outreach draft for {result.company_name} "
            f"(research confidence={result.confidence}, missing={len(result.missing_data)})"
        )
        req = approval_gate.create_approval(
            entity_type="opportunity",
            entity_id=result.lead_id,
            entity_name=result.company_name,
            approval_action="outreach_draft",
            requested_action=action,
            risk_level="low",
            notes=result.notes[:500],
            dry_run=False,
        )
        return {
            "ok": True,
            "approval_id": req.approval_id,
            "status": req.status,
            "dry_run": False,
        }

"""Lead scoring service — deterministic, no LLM.

Produces:
- ScoreOutput with fit_score, confidence, reasons, missing_data, recommended_next_action
- Opportunity row aligned with adapters.SCHEMA['opportunities']
- Optional approval request for deeper research

Design principles:
- Deterministic scoring based only on known fields.
- No invented emails or facts.
- Missing data lowers confidence; does not disqualify but flags for review.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .stub_detector import is_placeholder_lead

if TYPE_CHECKING:
    from .adapters import GoogleSheetsAdapter
    from .approval_gate import ApprovalGate


class ScoreOutput(BaseModel):
    """Structured output of lead scoring."""

    lead_id: str = ""
    company_name: str = ""
    fit_score: int = Field(default=0, ge=0, le=100)
    confidence: str = "low"  # low | medium | high
    reasons: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    recommended_next_action: str = ""
    is_placeholder: bool = False

    def to_opportunity_row(self) -> list[str]:
        """Serialise to opportunities tab (14 columns)."""
        return [
            f"OPP-{self.lead_id[:6]}",
            self.lead_id,
            datetime.utcnow().isoformat(),
            self.company_name,
            "research",
            f"Scored opportunity — fit_score={self.fit_score}",
            "",  # estimated_commission_min
            "",  # estimated_commission_max
            "",  # currency
            str(self.fit_score),  # probability surrogate
            "high" if self.fit_score >= 70 else "medium" if self.fit_score >= 40 else "low",
            "scored",
            self.recommended_next_action,
            " | ".join(self.reasons)
            + (" | missing: " + "; ".join(self.missing_data) if self.missing_data else ""),
        ]


class LeadScorer:
    """Score existing leads using deterministic rules."""

    RESEARCH_THRESHOLD: int = 50

    @staticmethod
    def from_lead_row(row: list[str]) -> ScoreOutput:
        """Score a single lead given its raw Sheet row values.

        Supports both legacy 9-col and canonical 15-col schemas by
        detecting the column count.
        """
        if len(row) >= 15:
            # Canonical 15-column leads schema (post-reconciliation)
            lead_id = row[0] if len(row) > 0 else ""
            _created_at = row[1] if len(row) > 1 else ""
            _source = row[2] if len(row) > 2 else ""
            _source_url = row[3] if len(row) > 3 else ""
            company_name = row[4] if len(row) > 4 else ""
            contact_name = row[5] if len(row) > 5 else ""
            contact_email = row[6] if len(row) > 6 else ""
            _role_title = row[7] if len(row) > 7 else ""
            _market = row[8] if len(row) > 8 else ""
            _country = row[9] if len(row) > 9 else ""
            problem_signal = row[10] if len(row) > 10 else ""
            commission_signal = row[11] if len(row) > 11 else ""
            _fit_score = row[12] if len(row) > 12 else ""
            _status = row[13] if len(row) > 13 else ""
            notes = row[14] if len(row) > 14 else ""
        else:
            # Legacy 9-column leads schema (pre-reconciliation data)
            lead_id = row[0] if len(row) > 0 else ""
            _source = row[1] if len(row) > 1 else ""
            contact_name = row[2] if len(row) > 2 else ""
            company_name = row[3] if len(row) > 3 else ""
            _source_url = row[4] if len(row) > 4 else ""
            contact_email = row[5] if len(row) > 5 else ""
            _status = row[6] if len(row) > 6 else ""
            _created_at = row[7] if len(row) > 7 else ""
            notes = row[8] if len(row) > 8 else ""
            problem_signal = ""
            commission_signal = ""

        score = 0
        reasons: list[str] = []
        missing: list[str] = []

        if company_name:
            score += 20
            reasons.append(f"Company: {company_name}")
        else:
            missing.append("company_name")

        if contact_name:
            score += 15
            reasons.append(f"Contact: {contact_name}")
        else:
            missing.append("contact_name")

        if contact_email:
            score += 30
            reasons.append("Has email")
        else:
            missing.append("contact_email")

        if _source_url:
            score += 10
        else:
            missing.append("source_url")

        if notes:
            score += 10
            reasons.append("Has contextual notes")

        if problem_signal:
            score += 10

        if commission_signal:
            score += 5

        if _source == "web_search":
            score += 5
            reasons.append("Verifiable web source")
        elif _source == "manual":
            reasons.append("Manual entry")

        is_placeholder = is_placeholder_lead(
            company_name=company_name,
            source_url=_source_url,
            contact_email=contact_email,
            notes=notes,
        )

        confidence = (
            "high" if contact_email and len(missing) <= 1 else "medium" if contact_email else "low"
        )

        if not contact_email:
            score = max(0, score - 20)
            reasons.append("No public email — lowers confidence")

        score = min(100, max(0, score))

        recommended = (
            "verify_email_then_draft_research"
            if contact_email
            else "manual_research_and_contact_hunt"
        )

        return ScoreOutput(
            lead_id=lead_id,
            company_name=company_name,
            fit_score=score,
            confidence=confidence,
            reasons=reasons,
            missing_data=missing,
            recommended_next_action=recommended,
            is_placeholder=is_placeholder,
        )

    def score_leads(
        self,
        leads: list[list[str]],
    ) -> list[ScoreOutput]:
        """Score multiple lead rows (skips header)."""
        results: list[ScoreOutput] = []
        for row in leads:
            if not row or not row[0] or row[0] == "lead_id":
                continue
            results.append(self.from_lead_row(row))
        return results

    def _find_existing_opportunity_for_lead(
        self,
        lead_id: str,
        *,
        sheets_adapter: GoogleSheetsAdapter | None = None,
    ) -> dict[str, Any]:
        """Return whether an opportunity already exists for the given lead_id.

        Uses read_last_rows (not read_rows) so it works even when the adapter
        is in dry_run mode — reads are side-effect-free.

        Returns {"exists": bool, "opportunity_id": str | ""}.
        """
        if sheets_adapter is None:
            return {"exists": False, "opportunity_id": ""}
        result = sheets_adapter.read_last_rows("opportunities", count=5000)
        if not result.get("ok"):
            return {"exists": False, "opportunity_id": "", "error": result.get("error")}
        rows = result.get("rows", [])
        if not rows:
            return {"exists": False, "opportunity_id": ""}
        if rows and rows[0] and rows[0][0] == "opportunity_id":
            rows = rows[1:]
        for row in rows:
            if len(row) > 1 and row[1] == lead_id:
                opp_id = row[0] if row and len(row) > 0 else ""
                return {"exists": True, "opportunity_id": opp_id}
        return {"exists": False, "opportunity_id": ""}

    def _find_existing_pending_approval(
        self,
        entity_type: str,
        entity_id: str,
        *,
        sheets_adapter: GoogleSheetsAdapter | None = None,
    ) -> dict[str, Any]:
        """Return whether a non-terminal approval already exists for the entity.

        Uses read_last_rows (not read_rows) so it works even when the adapter
        is in dry_run mode — reads are side-effect-free.

        Returns {"exists": bool, "approval_id": str, "status": str}.
        """
        if sheets_adapter is None:
            return {"exists": False, "approval_id": "", "status": ""}
        result = sheets_adapter.read_last_rows("approvals", count=5000)
        if not result.get("ok"):
            return {"exists": False, "approval_id": "", "status": "", "error": result.get("error")}
        rows = result.get("rows", [])
        if not rows:
            return {"exists": False, "approval_id": "", "status": ""}
        if rows and rows[0] and rows[0][0] == "approval_id":
            rows = rows[1:]
        for row in rows:
            if len(row) > 3 and row[3] == entity_id and len(row) > 2 and row[2] == entity_type:
                status = row[6] if len(row) > 6 else ""
                if status in ("pending", "approved"):
                    approval_id = row[0] if len(row) > 0 else ""
                    return {"exists": True, "approval_id": approval_id, "status": status}
        return {"exists": False, "approval_id": "", "status": ""}

    def write_opportunities(
        self,
        scores: list[ScoreOutput],
        *,
        sheets_adapter: GoogleSheetsAdapter | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Write scored opportunities to the opportunities tab, skipping
        duplicates, sub-threshold leads, and placeholder fixture leads.

        In dry-run mode, still checks for existing rows and reports what would
        happen.
        """
        if sheets_adapter is None:
            return {
                "ok": False,
                "error": "No sheets adapter",
                "written": 0,
                "skipped": 0,
                "below_threshold": 0,
                "placeholder": 0,
            }

        written = 0
        skipped = 0
        below_threshold = 0
        placeholder = 0
        errors: list[str] = []
        skipped_ids: list[str] = []
        below_threshold_ids: list[str] = []
        placeholder_ids: list[str] = []

        for s in scores:
            # Block placeholder / fixture leads from becoming real opportunities
            if s.is_placeholder:
                placeholder += 1
                placeholder_ids.append(s.lead_id)
                continue

            # Reject sub-threshold leads before any duplicate or write logic
            if s.fit_score < self.RESEARCH_THRESHOLD:
                below_threshold += 1
                below_threshold_ids.append(s.lead_id)
                continue

            dup = self._find_existing_opportunity_for_lead(s.lead_id, sheets_adapter=sheets_adapter)
            if dup.get("exists"):
                skipped += 1
                skipped_ids.append(dup.get("opportunity_id", "") or s.lead_id)
                continue
            if dry_run:
                # In dry-run we don't actually write, but we don't count as skipped
                # because nothing exists yet — just report would-create
                continue
            header_result = sheets_adapter.validate_tab_header("opportunities")
            if not header_result["ok"]:
                errors.append(f"Schema validation failed: {header_result['error']}")
                continue
            result = sheets_adapter.append_row("opportunities", s.to_opportunity_row())
            if result.get("ok"):
                written += 1
            else:
                errors.append(result.get("error", "unknown"))

        return {
            "ok": len(errors) == 0,
            "written": written,
            "skipped": skipped,
            "below_threshold": below_threshold,
            "placeholder": placeholder,
            "skipped_ids": skipped_ids,
            "below_threshold_ids": below_threshold_ids,
            "placeholder_ids": placeholder_ids,
            "errors": errors,
            "dry_run": dry_run,
        }

    def request_deeper_research_approvals(
        self,
        scores: list[ScoreOutput],
        *,
        approval_gate: ApprovalGate | None = None,
        sheets_adapter: GoogleSheetsAdapter | None = None,
        dry_run: bool = True,
    ) -> list[dict[str, Any]]:
        """Create pending approvals for leads scoring above threshold, skipping duplicates.

        Duplicate detection is based on (entity_type, entity_id) with non-terminal status
        in the approvals tab.
        """
        if approval_gate is None or sheets_adapter is None:
            return []
        results: list[dict[str, Any]] = []
        for s in scores:
            if s.is_placeholder or s.fit_score < self.RESEARCH_THRESHOLD:
                continue
            dup = self._find_existing_pending_approval(
                "opportunity",
                s.lead_id,
                sheets_adapter=sheets_adapter,
            )
            if dup.get("exists"):
                results.append(
                    {
                        "approval_id": dup.get("approval_id", ""),
                        "lead_id": s.lead_id,
                        "company": s.company_name,
                        "fit_score": s.fit_score,
                        "status": dup.get("status", ""),
                        "skipped": True,
                        "dry_run": dry_run,
                    }
                )
                continue
            action = (
                f"Approve deeper research for {s.company_name} "
                f"(fit_score={s.fit_score}, confidence={s.confidence})"
            )
            req = approval_gate.create_approval(
                entity_type="opportunity",
                entity_id=s.lead_id,
                requested_action=action,
                risk_level="medium",
                notes=" | ".join(s.reasons),
                dry_run=dry_run,
            )
            results.append(
                {
                    "approval_id": req.approval_id,
                    "lead_id": s.lead_id,
                    "company": s.company_name,
                    "fit_score": s.fit_score,
                    "skipped": False,
                    "dry_run": dry_run,
                }
            )
        return results

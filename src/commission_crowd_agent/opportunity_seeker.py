"""Autonomous opportunity seeking for commission-only sales roles.

Design:
- Source: public CommissionCrowd industry listing pages.
- Extraction: directory_extractor.py safe HTML extraction.
- Scoring: LeadScorer deterministic rules (+ commission rate filter).
- CRM writes: Google Sheets adapter (dry-run default).
- Approvals: pending for high-fit before any outreach.
- No real emails sent without operator approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from . import stub_detector
from .adapters import GoogleSheetsAdapter
from .approval_gate import ApprovalGate
from .directory_extractor import ExtractedCandidate, extract_candidates
from .lead_scoring import LeadScorer, ScoreOutput


@dataclass
class OpportunityRow:
    """Structured row for CRM opportunities tab."""

    opportunity_id: str = ""
    lead_id: str = ""
    created_at_utc: str = ""
    company_name: str = ""
    opportunity_type: str = "commission-only"
    offer_summary: str = ""
    estimated_commission_min: str = ""
    estimated_commission_max: str = ""
    currency: str = "USD"
    probability: str = ""
    priority: str = "medium"
    status: str = "sourced"
    next_action: str = "operator_review"
    notes: str = ""

    def to_sheets_row(self) -> list[str]:
        return [
            self.opportunity_id,
            self.lead_id,
            self.created_at_utc,
            self.company_name,
            self.opportunity_type,
            self.offer_summary,
            self.estimated_commission_min,
            self.estimated_commission_max,
            self.currency,
            self.probability,
            self.priority,
            self.status,
            self.next_action,
            self.notes,
        ]


@dataclass
class SeekResult:
    total_discovered: int = 0
    scored: int = 0
    above_threshold: int = 0
    written: int = 0
    approvals_created: int = 0
    skipped_duplicates: int = 0
    skipped_placeholders: int = 0
    dry_run: bool = True
    candidates: list[ExtractedCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_reports: list[dict[str, Any]] = field(default_factory=list)


class OpportunitySeeker:
    """Seek, extract, score, and stage commission-only opportunities."""

    DEFAULT_MIN_COMMISSION_PCT: float = 20.0
    FIT_THRESHOLD: int = 40
    MAX_SOURCES: int = 10
    MAX_PER_SOURCE: int = 5
    HARD_MAX: int = 20

    def __init__(
        self,
        sheets_adapter: GoogleSheetsAdapter | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self.sheets_adapter = sheets_adapter
        self.approval_gate = approval_gate
        self.scorer = LeadScorer()

    @staticmethod
    def load_sources(path: Path) -> list[dict[str, Any]]:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []

    def _fetch_html(self, url: str, timeout: float = 15.0) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; CCA-Bot/1.0; +https://syntaxis-labs.dev/bot-info)"
            ),
            "Accept": "text/html",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def _extract_commission_rate(notes: str) -> float:
        import re

        numeric_pct = r"(\d+\.?\d*)\s*%"
        matches = re.findall(numeric_pct, notes, flags=re.IGNORECASE)
        if matches:
            return max(float(v) for v in matches)
        commission_signals = {
            "50": 50.0,
            "45": 45.0,
            "40": 40.0,
            "30": 30.0,
            "25": 25.0,
            "20": 20.0,
        }
        for sig, val in commission_signals.items():
            if sig in notes:
                return val
        return 0.0

    def _is_target_industry(self, notes: str, title: str) -> bool:
        keywords = {
            "saas",
            "software",
            "cloud",
            "cybersecurity",
            "security",
            "ai",
            "automation",
            "api",
            "platform",
            "b2b",
            "enterprise",
        }
        text = f"{title} {notes}".lower()
        return any(kw in text for kw in keywords)

    def _build_lead_row(self, candidate: ExtractedCandidate) -> list[str]:
        now = datetime.utcnow().isoformat()
        return [
            f"LEAD-{candidate.lead_id}",
            now,
            candidate.source_type or "commissioncrowd",
            candidate.source_url,
            candidate.company,
            "",
            "",
            "",
            "",
            "",
            "",
            f"{self._extract_commission_rate(candidate.notes)}%",
            "",
            "new",
            candidate.notes,
        ]

    def discover_and_score(
        self,
        sources: list[dict[str, Any]],
        *,
        limit: int = 10,
        min_commission_pct: float | None = None,
        dry_run: bool = True,
    ) -> SeekResult:
        result = SeekResult(dry_run=dry_run)
        min_pct = min_commission_pct or self.DEFAULT_MIN_COMMISSION_PCT
        cap = min(limit, self.HARD_MAX)

        enabled = [s for s in sources if s.get("enabled", True)]
        if not enabled:
            result.errors.append("No enabled sources")
            return result

        existing: set[str] = set()
        if self.sheets_adapter and not dry_run:
            rr = self.sheets_adapter.read_last_rows("leads", count=200)
            if rr.get("ok"):
                rows = rr.get("rows", [])
                data = rows[1:] if rows and rows[0] and rows[0][0] == "lead_id" else rows
                for row in data:
                    if len(row) > 3 and row[3]:
                        existing.add(str(row[3]).strip())

        all_candidates: list[ExtractedCandidate] = []
        for source in enabled[: self.MAX_SOURCES]:
            if len(all_candidates) >= cap:
                break
            name = source.get("name", "")
            url = source.get("url", "")
            source_type = source.get("source_type", "operator_provided")
            per_cap = int(source.get("per_source_limit", self.MAX_PER_SOURCE))
            remaining = cap - len(all_candidates)
            source_max = min(per_cap, remaining)
            report: dict[str, Any] = {
                "name": name,
                "extracted": 0,
                "duplicates_skipped": 0,
                "placeholders_blocked": 0,
                "written": 0,
            }
            try:
                html = self._fetch_html(url)
                extracted = extract_candidates(
                    html,
                    source_url=url,
                    source_name=name,
                    source_type=source_type,
                    max_candidates=source_max,
                )
            except Exception as exc:
                report["error"] = f"{type(exc).__name__}: {exc}"
                result.source_reports.append(report)
                continue

            for ec in extracted:
                if ec.url in existing or ec.url in {c.url for c in all_candidates}:
                    report["duplicates_skipped"] += 1
                    continue
                if stub_detector.is_placeholder_candidate(ec.company, ec.url, ec.notes):
                    report["placeholders_blocked"] += 1
                    continue
                all_candidates.append(ec)
                report["extracted"] += 1

            report["written"] = report["extracted"]
            result.source_reports.append(report)

        result.total_discovered = len(all_candidates)
        result.candidates = all_candidates

        # Scoring pass
        scored: list[ScoreOutput] = []
        for ec in all_candidates:
            row = self._build_lead_row(ec)
            score = self.scorer.from_lead_row(row)
            # Commission bonus: add 0-15 points
            rate = self._extract_commission_rate(ec.notes)
            if rate >= min_pct:
                score.fit_score = min(100, score.fit_score + 10)
                score.reasons.append(f"Commission {rate}% >= {min_pct}%")
            elif rate > 0:
                score.fit_score = min(100, score.fit_score + 5)
                score.reasons.append(f"Commission {rate}% (below target)")
            else:
                score.missing_data.append("commission_rate")

            # Industry bonus
            if self._is_target_industry(ec.notes, ec.company):
                score.fit_score = min(100, score.fit_score + 5)
                score.reasons.append("B2B SaaS/AI/automation/cybersecurity keyword match")
            else:
                score.missing_data.append("target_industry_match")

            scored.append(score)

        result.scored = len(scored)
        result.above_threshold = sum(1 for s in scored if s.fit_score >= self.FIT_THRESHOLD)

        # Write opportunities to CRM
        if self.sheets_adapter:
            for ec, score in zip(all_candidates, scored, strict=False):
                if score.fit_score < self.FIT_THRESHOLD or score.is_placeholder:
                    continue
                # Deduplicate opportunities
                dup = self.scorer._find_existing_opportunity_for_lead(
                    f"LEAD-{ec.lead_id}", sheets_adapter=self.sheets_adapter
                )
                if dup.get("exists"):
                    result.skipped_duplicates += 1
                    continue

                if dry_run:
                    result.written += 1
                    continue

                opp_row = OpportunityRow(
                    opportunity_id=f"OPP-{ec.lead_id}",
                    lead_id=f"LEAD-{ec.lead_id}",
                    created_at_utc=datetime.utcnow().isoformat(),
                    company_name=ec.company,
                    offer_summary=ec.notes[:200],
                    estimated_commission_min=str(self._extract_commission_rate(ec.notes)),
                    estimated_commission_max="",
                    currency="USD",
                    probability=str(score.fit_score),
                    priority="high" if score.fit_score >= 70 else "medium",
                    status="sourced",
                    next_action="operator_review",
                    notes=" | ".join(score.reasons)
                    + (
                        " | missing: " + "; ".join(score.missing_data) if score.missing_data else ""
                    ),
                )
                wr = self.sheets_adapter.append_row("opportunities", opp_row.to_sheets_row())
                if wr.get("ok"):
                    result.written += 1
                else:
                    result.errors.append(wr.get("error", "unknown write error"))

                # Also append to leads tab
                lr = self.sheets_adapter.append_row("leads", self._build_lead_row(ec))
                if not lr.get("ok"):
                    result.errors.append(lr.get("error", "lead write error"))

                # Approval request
                if self.approval_gate:
                    opp_rate = self._extract_commission_rate(ec.notes)
                    try:
                        self.approval_gate.create_and_write_approval(
                            entity_type="opportunity",
                            entity_id=f"OPP-{ec.lead_id}",
                            entity_name=ec.company,
                            approval_action="research_scoring",
                            requested_action=(
                                f"Review opportunity {ec.company} "
                                f"(fit={score.fit_score}, commission={opp_rate}%+)"
                            ),
                            risk_level="medium",
                            source_url=ec.url,
                            notes=" | ".join(score.reasons)
                            + (
                                " | missing: " + "; ".join(score.missing_data)
                                if score.missing_data
                                else ""
                            ),
                        )
                        result.approvals_created += 1
                    except RuntimeError as exc:
                        result.errors.append(f"Approval failed: {exc}")

        return result

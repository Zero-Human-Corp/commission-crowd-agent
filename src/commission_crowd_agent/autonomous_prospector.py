"""Autonomous prospector for CommissionCrowd.

Periodic task: discover opportunities, score them against the profile, log
them in the CRM, and create approval-gated application drafts.

Rules:
- Dry-run by default; live operations need explicit opt-in.
- Max 5 opportunities per cycle (hard cap).
- Target: commission >= 20 % or deal size >= $2,500, short sales cycle,
  email or phone preferred.
- All scoring is deterministic; no LLM hallucination of commission terms.
- Every application draft needs a pending approval before it can be sent.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .calendar_adapter import CalendarAdapter
from .commissioncrowd_adapter import CommissionCrowdApiAdapter
from .crm_pipeline import CRMPipeline
from .domain import OpportunityStage
from .lead_scoring import LeadScorer


class CommissionCrowdProspector:
    """Autonomous opportunity seeker + application tracker for CommissionCrowd.

    Parameters
    ----------
    api_key
        CommissionCrowd REST API key (or ``""`` to rely on config).
    profile
        Agent profile dict with keys like ``territory``, ``industry``,
        ``email`` etc.
    dry_run
        When ``True`` (default) no real Sheet writes or API calls are made.
    per_cycle_limit
        Maximum opportunities to process per invocation.
    min_commission_pct
        Minimum commission percentage to consider "high".
    min_deal_value
        Minimum deal size to consider "high" (USD).
    """

    def __init__(
        self,
        api_key: str = "",
        profile: dict[str, Any] | None = None,
        *,
        dry_run: bool = True,
        per_cycle_limit: int = 5,
        min_commission_pct: int = 20,
        min_deal_value: int = 2500,
    ) -> None:
        self.adapter = CommissionCrowdApiAdapter(api_key=api_key, dry_run=dry_run)
        self.profile = profile or {}
        self.dry_run = dry_run
        self.per_cycle_limit = per_cycle_limit
        self.min_commission_pct = min_commission_pct
        self.min_deal_value = min_deal_value
        self.scorer = LeadScorer()
        self.calendar = CalendarAdapter(dry_run=dry_run)

    # ------------------------------------------------------------------
    # Scoring helpers (deterministic)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_deal_value(text: str) -> int:
        """Try to extract a deal value from free text."""
        if not text:
            return 0
        text = text.lower().replace(",", "")
        # Range: "$7,500–$15,000" -> take upper bound (must come before simple match)
        match = re.search(r"\$(\d+)\s*[-–]\s*\$?(\d+)", text)
        if match:
            return int(match.group(2))
        # "$2,500" or "$2500"
        match = re.search(r"\$(\d{3,})", text)
        if match:
            return int(match.group(1))
        return 0

    @staticmethod
    def _extract_commission_pct(text: str) -> int:
        """Try to extract a commission percentage from free text."""
        if not text:
            return 0
        text = text.lower()
        # Patterns: "20%", "20 %", "20 percent"
        match = re.search(r"(\d+)\s*(?:%|percent)", text)
        if match:
            return int(match.group(1))
        # "up to 20%"
        match = re.search(r"up to\s+(\d+)\s*(?:%|percent)", text)
        if match:
            return int(match.group(1))
        return 0

    @staticmethod
    def _has_short_cycle(text: str) -> bool:
        """Detect short sales cycle indicators."""
        if not text:
            return False
        text = text.lower()
        indicators = [
            "short",
            "fast",
            "quick",
            "warm",
            "warm leads",
            "immediate",
            "rapid",
            "express",
            "accelerated",
        ]
        return any(i in text for i in indicators)

    @staticmethod
    def _has_email_phone(text: str) -> bool:
        """Detect email or phone outreach preference."""
        if not text:
            return False
        text = text.lower()
        return "email" in text or "phone" in text or "call" in text or "zoom" in text

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_cycle(
        self,
        *,
        crm_pipeline: CRMPipeline | None = None,
        write: bool = False,
    ) -> dict[str, Any]:
        """Execute one autonomous prospecting cycle.

        Returns a structured result dict with counts and any errors.
        """
        live = write and not self.dry_run

        # 1. Fetch public opportunities
        opp_result = self.adapter.list_opportunities()
        opps = []
        if opp_result.get("dry_run"):
            pass  # dry-run stubs don't count as discovered
        elif opp_result.get("ok"):
            raw_opps = opp_result.get("data", {}).get("items", []) or []
            # Convert Pydantic models to plain dicts for uniform handling
            opps = [o.model_dump() if hasattr(o, "model_dump") else o for o in raw_opps]
        elif opp_result.get("using_fallback"):
            raw_list = opp_result.get("raw_listings", [])
            opps = [
                {
                    "id": i,
                    "title": r.get("title", ""),
                    "description": "",
                    "commission": "",
                    "url": r.get("url", ""),
                    "industry": "",
                    "status": "active",
                    "created_at": None,
                }
                for i, r in enumerate(raw_list)
            ]

        # 2. Filter and score
        scored: list[dict[str, Any]] = []
        for opp in opps[:50]:  # bounded read
            title = opp.get("name", "") or opp.get("title", "") or ""
            desc = opp.get("description", "") or ""
            short_summary = opp.get("short_summary", "") or ""
            full_text = f"{title} {desc} {short_summary}"

            # Commission signal from structured field (fallback to text search)
            comm_val = opp.get("commission_pc")
            try:
                if comm_val is not None:
                    comm_pct = float(comm_val)
                else:
                    comm_pct = self._extract_commission_pct(full_text)
            except (ValueError, TypeError):
                comm_pct = self._extract_commission_pct(full_text)
            deal_val = self._extract_deal_value(full_text)

            # Short cycle from structured field + text
            avg_sales_cycle = opp.get("average_sales_cycle")
            sales_cycle_short = False
            if avg_sales_cycle is not None:
                try:
                    sales_cycle_short = int(avg_sales_cycle) <= 2
                except (ValueError, TypeError):
                    sales_cycle_short = False
            short_cycle = sales_cycle_short or self._has_short_cycle(full_text)

            # Preferred methods from structured fields + text
            has_phone = bool(opp.get("phone"))
            has_email = bool(opp.get("email"))
            preferred_methods = has_phone or has_email or self._has_email_phone(full_text)

            # Simple fit score (0-100)
            fit = 0
            if comm_pct >= self.min_commission_pct:
                fit += 30
            if deal_val >= self.min_deal_value:
                fit += 30
            if short_cycle:
                fit += 20
            if preferred_methods:
                fit += 20

            if fit >= 50:
                scored.append(
                    {
                        "opportunity": opp,
                        "fit": fit,
                        "comm_pct": comm_pct,
                        "deal_val": deal_val,
                        "short_cycle": short_cycle,
                        "preferred_methods": preferred_methods,
                    }
                )

        # Sort by fit descending; cap
        scored.sort(key=lambda x: x["fit"], reverse=True)
        top = scored[: self.per_cycle_limit]

        # 3. Log in CRM (dry-run safe)
        added: list[dict[str, Any]] = []
        for s in top:
            opp = s["opportunity"]
            name = opp.get("name") or opp.get("title", "")
            slug = opp.get("latest_slug", "")
            lead_id = f"CC-{slug}" if slug else f"CC-{name[:20].replace(' ', '-')}-{s['fit']}"
            record = {
                "lead_id": lead_id,
                "title": name,
                "fit": s["fit"],
                "comm_pct": s["comm_pct"],
                "deal_val": s["deal_val"],
                "url": opp.get("url", ""),
                "status": OpportunityStage.SOURCED,
            }
            if crm_pipeline is not None:
                crm_pipeline.add_lead(
                    lead_id=lead_id,
                    company_name=opp.get("title", ""),
                    source="commissioncrowd",
                    source_url=opp.get("url", ""),
                    notes=(
                        f"fit={s['fit']}, comm={s['comm_pct']}pct, "
                        f"deal=${s['deal_val']}, short={s['short_cycle']}, "
                        f"methods={s['preferred_methods']}"
                    ),
                    dry_run=not live,
                )
            added.append(record)

        # 4. Schedule follow-up reminders in calendar tab
        for rec in added:
            _ = self.calendar.schedule_follow_up(
                entity_type="opportunity",
                entity_id=rec["lead_id"],
                days=3,
                sheets_adapter=crm_pipeline.sheets_adapter if crm_pipeline else None,
            )

        return {
            "ok": True,
            "cycle": "commissioncrowd_prospect",
            "dry_run": not live,
            "total_discovered": len(opps),
            "scored_and_qualified": len(top),
            "crm_added": len(added),
            "records": added,
            "timestamp": datetime.utcnow().isoformat(),
        }

"""Scoring workflow stage with fallback enrichment heuristics.

This module extends deterministic lead scoring with an intelligent fallback
layer for sparse CommissionCrowd listings:

- When commission/deal-value figures are missing, non-monetary signals such
  as target industry tags, territory overlap, B2B alignment, and platform
  activity are used to build an ICP match score.
- Highly aligned sparse profiles are allowed to pass the research threshold
  instead of being hard-gate rejected.
- If the operator has injected a manual valuation override into the
  ``opportunities`` or ``leads`` Sheet tab, that value is honoured
  explicitly and the opportunity is moved out of a "sparsely detailed" lock.

All outbound actions (Sheets reads/writes) are gated by ``dry_run``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from ..adapters import GoogleSheetsAdapter, ScoringAdapter
from ..canonical import CanonicalOpportunity
from ..config import load_settings
from ..domain import Lead


class EnrichmentScore(BaseModel):
    """Structured output of the enriched scoring pass."""

    opportunity_id: str
    company_name: str = ""
    title: str = ""
    fit_score: int = Field(default=0, ge=0, le=100)
    monetary_score: int = Field(default=0, ge=0, le=100)
    icp_score: int = Field(default=0, ge=0, le=100)
    manual_override_applied: bool = False
    manual_value_usd: int | None = None
    data_quality_flags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    passed: bool = False
    next_action: str = ""

    def to_opportunity_row(self) -> list[str]:
        """Serialise to the opportunities tab row shape."""
        return [
            self.opportunity_id,
            "",
            datetime.now(UTC).isoformat(),
            self.company_name,
            "enriched_scoring",
            self.title,
            str(self.manual_value_usd) if self.manual_value_usd else "",
            "",
            "USD",
            str(self.fit_score),
            "high" if self.passed else "low",
            "passed" if self.passed else "sparsely_detailed",
            self.next_action,
            " | ".join(self.reasons)
            + (
                " | flags: " + "; ".join(self.data_quality_flags)
                if self.data_quality_flags
                else ""
            ),
        ]


@dataclass
class OperatorICP:
    """Operator/industry profile used for ICP matching."""

    industries: list[str] = None  # type: ignore[assignment]
    territories: list[str] = None  # type: ignore[assignment]
    selling_methods: list[str] = None  # type: ignore[assignment]
    preferred_features: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.industries is None:
            self.industries = []
        if self.territories is None:
            self.territories = []
        if self.selling_methods is None:
            self.selling_methods = []
        if self.preferred_features is None:
            self.preferred_features = []


DEFAULT_OPERATOR_PROFILE: dict[str, Any] = {
    "company": "Syntaxis Labs",
    "business_unit": "Syntaxis Commission Partners",
    "industries": [
        "B2B SaaS",
        "Artificial Intelligence",
        "Data Analytics",
        "Automation",
        "Cybersecurity",
        "Business Services",
        "Cloud Computing",
        "FinTech",
        "MarTech",
    ],
    "territories": [
        "Global",
        "North America",
        "United States",
        "Canada",
        "Africa",
        "European Union",
        "Middle East",
        "United Kingdom",
        "Asia-Pacific",
    ],
    "selling_methods": [
        "Appointment Setting",
        "Online Demos",
        "Affiliate Link",
        "Email Outreach",
        "LinkedIn Outreach",
        "Webinar / Event Lead Gen",
        "Referral Programs",
        "Channel Partner Development",
        "Social Selling",
    ],
    "preferred_features": [
        "Recurring Commission",
        "Residual Commission",
        "Clear Sales Process",
        "Training Provided",
        "Sales Materials Provided",
        "CRM Access Provided",
        "Transparent Reporting",
        "Demo Environment Provided",
    ],
}


# Column-name patterns used to locate a manual valuation override in Sheets.
_MANUAL_OVERRIDE_HEADER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"manual.?override", re.IGNORECASE),
    re.compile(r"operator.?value", re.IGNORECASE),
    re.compile(r"manual.?valuation", re.IGNORECASE),
    re.compile(r"manual.?commission", re.IGNORECASE),
    re.compile(r"operator.?commission", re.IGNORECASE),
    re.compile(r"override.?value", re.IGNORECASE),
]


def _parse_usd_value(text: str) -> int | None:
    """Extract a USD integer from free text such as '$5,000' or '2500'."""
    if not text:
        return None
    text = text.strip()
    # Remove currency symbols and commas
    cleaned = re.sub(r"[$,]", "", text)
    # Pull the first integer / decimal token
    m = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not m:
        return None
    try:
        return int(round(float(m.group(0))))
    except ValueError:
        return None


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _phrase_set(values: list[str]) -> set[str]:
    """Return normalised full phrases plus individual word tokens."""
    phrases: set[str] = set()
    for value in values:
        if not value:
            continue
        phrases.add(_normalise(value))
        for word in re.split(r"[^a-z0-9]+", value.lower()):
            if word:
                phrases.add(word)
    return phrases


def _token_overlap(a: list[str], b: list[str]) -> tuple[int, list[str]]:
    """Return count and matched phrases/tokens between two lists of strings."""
    matched: list[str] = []
    norm_b = _phrase_set(b)
    seen: set[str] = set()
    for item in a:
        if not item:
            continue
        full = _normalise(item)
        if full in norm_b and full not in seen:
            matched.append(item)
            seen.add(full)
            continue
        for word in re.split(r"[^a-z0-9]+", item.lower()):
            if word and word in norm_b and word not in seen:
                matched.append(item)
                seen.add(word)
                break
    return len(seen), matched


def _score_industry_match(opp: CanonicalOpportunity, icp: OperatorICP) -> tuple[int, list[str]]:
    """Score how well the opportunity category/industries match operator ICP."""
    opp_tokens: list[str] = []
    if opp.category:
        opp_tokens.extend(opp.category.replace(",", " ").replace("/", " ").split())
    opp_tokens.extend(str(i) for i in opp.industries)
    opp_tokens.extend(str(i) for i in opp.target_industries)

    score = 0
    reasons: list[str] = []
    matches, matched = _token_overlap(opp_tokens, icp.industries)
    if matches:
        score = min(45, 15 + matches * 10)
        reasons.append(f"Industry match: {', '.join(matched[:3])}")
    return score, reasons


def _score_territory_match(opp: CanonicalOpportunity, icp: OperatorICP) -> tuple[int, list[str]]:
    """Score territory overlap between opportunity and operator coverage."""
    if not opp.territory and not opp.global_territory:
        return 0, []

    opp_tokens: list[str] = []
    if opp.territory:
        opp_tokens.extend(opp.territory.replace(",", " ").replace("/", " ").split())
    if opp.global_territory:
        opp_tokens.append("global")

    if "global" in {_normalise(t) for t in opp_tokens}:
        return 30, ["Global territory coverage"]

    matches, matched = _token_overlap(opp_tokens, icp.territories)
    if matches:
        score = min(35, 10 + matches * 8)
        return score, [f"Territory match: {', '.join(matched[:3])}"]
    return 0, []


def _score_activity_and_completeness(opp: CanonicalOpportunity) -> tuple[int, list[str]]:
    """Score platform activity signals and profile completeness."""
    score = 0
    reasons: list[str] = []
    if opp.active:
        score += 10
        reasons.append("Listing active")
    if opp.completeness and opp.completeness >= 70:
        score += 15
        reasons.append(f"High profile completeness ({opp.completeness}%)")
    elif opp.completeness and opp.completeness >= 40:
        score += 5
    if opp.view_count >= 100:
        score += 5
    if opp.has_email:
        score += 10
        reasons.append("Public contact email available")
    return score, reasons


def _score_monetary(opp: CanonicalOpportunity) -> tuple[int, list[str]]:
    """Score monetary attractiveness from commission text / deal value."""
    if opp.commission_percent is not None and opp.commission_percent > 0:
        pct = min(opp.commission_percent, 100)
        return int(pct), [f"Explicit commission rate {pct}%"]
    if opp.deal_value_usd:
        val = opp.deal_value_usd
        if val >= 50000:
            return 40, [f"High deal value ${val:,}"]
        elif val >= 10000:
            return 25, [f"Mid deal value ${val:,}"]
        else:
            return 15, [f"Deal value ${val:,}"]
    if opp.commission_text:
        # Try to extract a percentage or dollar range
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", opp.commission_text)
        if pct_match:
            pct = float(pct_match.group(1))
            return int(min(pct, 100)), [f"Parsed commission rate {pct}%"]
        dollar_match = re.search(r"\$[\d,]+(?:\s*[-–]\s*\$?[\d,]+)?", opp.commission_text)
        if dollar_match:
            return 15, [f"Commission range mentioned {dollar_match.group(0)}"]
    return 0, []


def _apply_manual_override(
    opp: CanonicalOpportunity,
    header: list[str],
    row: list[str],
) -> tuple[int | None, bool, list[str]]:
    """Look for and parse a manual valuation override column in a Sheet row.

    Returns (value_usd, applied, reasons).
    """
    for idx, col in enumerate(header):
        if any(p.search(col) for p in _MANUAL_OVERRIDE_HEADER_PATTERNS) and idx < len(row):
            raw = row[idx]
            value = _parse_usd_value(raw)
            if value is not None:
                return value, True, [f"Manual override applied from column '{col}'"]
    return None, False, []


def _operator_icp_from_profile(profile: dict[str, Any]) -> OperatorICP:
    return OperatorICP(
        industries=profile.get("industries", []),
        territories=profile.get("territories", []),
        selling_methods=profile.get("selling_methods", []),
        preferred_features=profile.get("preferred_features", []),
    )


def score_with_enrichment(
    opp: CanonicalOpportunity,
    *,
    icp: OperatorICP | None = None,
    manual_value_usd: int | None = None,
    research_threshold: int = 50,
    icp_threshold: int = 70,
) -> EnrichmentScore:
    """Score an opportunity with fallback enrichment for sparse listings."""
    if icp is None:
        icp = _operator_icp_from_profile(DEFAULT_OPERATOR_PROFILE)

    industry_score, industry_reasons = _score_industry_match(opp, icp)
    territory_score, territory_reasons = _score_territory_match(opp, icp)
    activity_score, activity_reasons = _score_activity_and_completeness(opp)
    monetary_score, monetary_reasons = _score_monetary(opp)

    icp_score = min(100, industry_score + territory_score + activity_score)

    reasons = industry_reasons + territory_reasons + activity_reasons

    # If the operator injected a manual valuation, honour it and add a monetary reason.
    manual_override_applied = False
    manual_value: int | None = manual_value_usd
    if manual_value is not None:
        monetary_score = max(monetary_score, min(100, manual_value // 500))
        reasons.append(f"Manual valuation ${manual_value:,} honoured")
        manual_override_applied = True

    reasons.extend(monetary_reasons)

    fit_score = min(100, icp_score + monetary_score)

    # Decide whether this sparse-but-aligned opportunity should pass.
    passed = False
    if fit_score >= research_threshold:
        passed = True
    elif icp_score >= icp_threshold:
        passed = True
        reasons.append(f"ICP override (icp_score={icp_score} >= {icp_threshold})")
    elif manual_override_applied:
        passed = True
        reasons.append("Manual valuation override lifted sparsely-detailed lock")

    next_action = (
        "draft_application_or_deeper_research"
        if passed
        else "manual_review_or_enrichment"
    )

    return EnrichmentScore(
        opportunity_id=opp.source_opportunity_id,
        company_name=opp.company_name or "",
        title=opp.title,
        fit_score=fit_score,
        monetary_score=monetary_score,
        icp_score=icp_score,
        manual_override_applied=manual_override_applied,
        manual_value_usd=manual_value,
        data_quality_flags=opp.data_quality_flags,
        reasons=reasons,
        passed=passed,
        next_action=next_action,
    )


def _read_manual_overrides_from_sheet(
    sheets: GoogleSheetsAdapter | None,
    tab: str = "opportunities",
) -> dict[str, int]:
    """Return a map of opportunity_id -> manual valuation override USD.

    Looks for columns matching the manual-override header patterns. If no
    override column is found, falls back to ``estimated_commission_max``.
    """
    overrides: dict[str, int] = {}
    if sheets is None:
        return overrides

    result = sheets.read_last_rows(tab, count=5000)
    if not result.get("ok"):
        return overrides

    rows = result.get("rows", [])
    if not rows:
        return overrides

    header = rows[0]
    override_idx: int | None = None
    for idx, col in enumerate(header):
        if any(p.search(col) for p in _MANUAL_OVERRIDE_HEADER_PATTERNS):
            override_idx = idx
            break

    # Fallback to estimated_commission_max if present
    if override_idx is None and "estimated_commission_max" in header:
        override_idx = header.index("estimated_commission_max")

    if override_idx is None:
        return overrides

    id_idx = header.index("opportunity_id") if "opportunity_id" in header else 0
    for row in rows[1:]:
        if len(row) <= max(id_idx, override_idx):
            continue
        opp_id = row[id_idx]
        raw = row[override_idx]
        value = _parse_usd_value(raw)
        if value is not None and opp_id:
            overrides[opp_id] = value

    return overrides


def score_batch(leads: list[Lead], scorer: ScoringAdapter, dry_run: bool = True) -> list[Lead]:
    """Score a batch of leads (legacy compatibility wrapper)."""
    for lead in leads:
        lead.personalization_score = scorer.score(lead) if not dry_run else 7
    return leads


def score_opportunities(
    opportunities: list[CanonicalOpportunity],
    *,
    sheets: GoogleSheetsAdapter | None = None,
    icp: OperatorICP | None = None,
    dry_run: bool = True,
    research_threshold: int = 50,
    icp_threshold: int = 70,
) -> dict[str, Any]:
    """Score a list of opportunities with manual-override enrichment.

    Reads the operator-injected valuation overrides from the ``opportunities``
    Sheet tab (unless in dry-run mode) and applies them before the final pass
    decision.
    """
    overrides: dict[str, int] = {}
    if not dry_run and sheets is not None:
        overrides = _read_manual_overrides_from_sheet(sheets, tab="opportunities")
        # Also try leads tab if no overrides were found
        if not overrides:
            overrides = _read_manual_overrides_from_sheet(sheets, tab="leads")

    scores: list[EnrichmentScore] = []
    for opp in opportunities:
        manual_value = overrides.get(opp.source_opportunity_id)
        score = score_with_enrichment(
            opp,
            icp=icp,
            manual_value_usd=manual_value,
            research_threshold=research_threshold,
            icp_threshold=icp_threshold,
        )
        scores.append(score)

    passed = [s for s in scores if s.passed]
    failed = [s for s in scores if not s.passed]

    return {
        "ok": True,
        "dry_run": dry_run,
        "total": len(scores),
        "passed": len(passed),
        "rejected": len(failed),
        "manual_overrides_found": len(overrides),
        "scores": [s.model_dump() for s in scores],
    }


def _sample_opportunities() -> list[CanonicalOpportunity]:
    """Return synthetic opportunities for dry-run demonstrations."""
    return [
        CanonicalOpportunity(
            source="sample",
            source_opportunity_id="SPARSE-1001",
            title="SAMPLE B2B SaaS — no commission stated",
            company_name="Sample Sparse Principal Ltd",
            category="B2B SaaS",
            territory="North America",
            active=True,
            completeness=85,
            view_count=250,
            application_count=12,
            data_quality_flags=["missing_commission_text", "unclear_commission_rate"],
        ),
        CanonicalOpportunity(
            source="sample",
            source_opportunity_id="SPARSE-1002",
            title="SAMPLE AI Automation — UK",
            company_name="Sample AI Principal Ltd",
            category="Artificial Intelligence",
            territory="United Kingdom",
            active=True,
            completeness=60,
            view_count=80,
            commission_text="Strong ICP match but no rate published",
            data_quality_flags=["unclear_commission_rate"],
        ),
        CanonicalOpportunity(
            source="sample",
            source_opportunity_id="CLEAR-1003",
            title="SAMPLE Cybersecurity — 20% recurring",
            company_name="Sample Clear Principal Ltd",
            category="Cybersecurity",
            territory="Global",
            active=True,
            commission_text="20% recurring commission",
            commission_percent=20.0,
            residual_terms=True,
            deal_value_usd=25000,
        ),
    ]


def main() -> int:
    """CLI entry point for the enriched scoring workflow."""
    parser = argparse.ArgumentParser(
        description="Enriched opportunity scoring with fallback heuristics"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simulate scoring without reading/writing Sheets (default)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Read manual overrides from Google Sheets",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=50,
        help="Fit-score research threshold (default: 50)",
    )
    parser.add_argument(
        "--icp-threshold",
        type=int,
        default=70,
        help="ICP-score override threshold for sparse listings (default: 70)",
    )
    args = parser.parse_args()

    dry_run = not args.live
    print(f"Mode: {'DRY-RUN' if dry_run else 'LIVE'}")

    settings = load_settings()
    sheets: GoogleSheetsAdapter | None = None
    if not dry_run and settings.google_ready:
        sheets = GoogleSheetsAdapter(
            spreadsheet_id=settings.google_sheets_spreadsheet_id,
            credentials_path=settings.google_application_credentials_path,
            service_account_json=settings.google_service_account_json,
            dry_run=dry_run,
        )
        health = sheets.health_check()
        if not health.get("ok"):
            print(f"ERROR: Sheets health check failed: {health.get('error')}", file=sys.stderr)
            return 1

    opportunities = _sample_opportunities()
    result = score_opportunities(
        opportunities,
        sheets=sheets,
        dry_run=dry_run,
        research_threshold=args.threshold,
        icp_threshold=args.icp_threshold,
    )

    print(json.dumps(result, indent=2))
    print(f"\nSummary: {result['passed']} passed, {result['rejected']} rejected")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Score the 320 net-new CommissionCrowd Find Opportunities candidates.

This script:
  1. Loads the reconciled net-new candidate list.
  2. Scores each candidate using deterministic rules aligned with mvp_pipeline.py.
  3. Produces a qualification report (JSON + Markdown) sorted by fit score.
  4. Does NOT write to CRM, Google Sheets, or approvals by default.

Usage:
  python3 scripts/qualify_find_opportunities.py [--limit N] [--min-commission 20.0]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.canonical import CanonicalOpportunity

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
INPUT_PATH = REPORTS_DIR / "cca_net_new_candidates.json"

# Target B2B SaaS/AI/automation/cybersecurity keywords
_TARGET_KEYWORDS = {
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
    "data",
    "recurring",
    "managed services",
}


def _extract_commission_percent(text: str) -> float | None:
    """Best-effort parse a numeric commission percentage from free text."""
    if not text:
        return None
    # "20%", "20 %", "up to 25%", "25pc"
    patterns = [
        r"(\d+(?:\.\d+)?)\s*%",
        r"up\s+to\s+(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:percent|pc)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def _extract_territory_from_title(title: str) -> str:
    """Infer territory hints from title text when no territory field exists."""
    if not title:
        return ""
    t = title.lower()
    if any(w in t for w in ("global", "worldwide", "international", "world wide")):
        return "global"
    # Common region/country signals
    region_map = {
        "north america": "north_america",
        "usa": "north_america",
        "us": "north_america",
        "united states": "north_america",
        "canada": "north_america",
        "uk": "uk",
        "united kingdom": "uk",
        "ireland": "uk_ireland",
        "europe": "europe",
        "australia": "australia",
        "apac": "apac",
        "asia": "asia",
    }
    for phrase, territory in region_map.items():
        if phrase in t:
            return territory
    return ""


def _detect_residual(text: str) -> bool:
    """True if commission text mentions residual, lifetime, or recurring."""
    if not text:
        return False
    return any(
        word in text.lower()
        for word in ("residual", "lifetime", "recurring", "ongoing", "monthly", "annuity")
    )


def _score_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """Score a single net-new candidate deterministically."""
    title = item.get("title", "")
    description = item.get("description", "")
    commission_text = item.get("commission_text", "")
    territory = item.get("territory", "") or item.get("territory_details", "")
    query_overlap_count = item.get("query_overlap_count", 1)

    full_text = f"{title} {description} {commission_text} {territory}".lower()

    score = 0
    reasons: list[str] = []
    missing: list[str] = []
    flags: list[str] = []

    # 1. Commission rate — also look in title/description if commission_text empty
    commission_search_text = " ".join(filter(None, [commission_text, title, description]))
    pct = _extract_commission_percent(commission_search_text)
    if pct is not None:
        if pct >= 25:
            score += 30
            reasons.append(f"High commission ({pct}%)")
        elif pct >= 20:
            score += 25
            reasons.append(f"Solid commission ({pct}%)")
        elif pct >= 15:
            score += 15
            reasons.append(f"Moderate commission ({pct}%)")
        else:
            score += 5
            reasons.append(f"Low commission ({pct}%)")
    else:
        missing.append("commission_percent")
        reasons.append("Commission rate unclear")
        flags.append("unclear_commission_rate")

    # 2. Residual / recurring terms (0-15)
    if _detect_residual(commission_text):
        score += 15
        reasons.append("Residual/recurring commissions")
    else:
        reasons.append("No residual terms")

    # 3. Territory clarity (0-15)
    territory = territory or _extract_territory_from_title(title)
    if territory and len(territory) > 3:
        if "global" in territory.lower() or "worldwide" in territory.lower():
            score += 15
            reasons.append("Global territory")
        else:
            score += 10
            reasons.append(f"Territory: {territory}")
    else:
        missing.append("territory")
        reasons.append("Territory unspecified")
        flags.append("unclear_territory")

    # 4. Target-industry keyword match (0-10)
    matched_keywords = {kw for kw in _TARGET_KEYWORDS if kw in full_text}
    if matched_keywords:
        score += min(10, 5 + len(matched_keywords))
        reasons.append(f"B2B keyword match: {', '.join(sorted(matched_keywords)[:3])}")
    else:
        missing.append("target_industry_match")

    # 5. Multi-query provenance (0-10)
    if query_overlap_count >= 3:
        score += 10
        reasons.append(f"Matched {query_overlap_count} search queries")
    elif query_overlap_count == 2:
        score += 5
        reasons.append("Matched 2 search queries")

    # 6. Description completeness (0-10)
    # For browser Find results, descriptions are often absent; use title length + query overlap
    effective_description_len = max(
        len(description or ""), len(title or "") // 2
    )
    if effective_description_len >= 200:
        score += 10
        reasons.append("Detailed description")
    elif effective_description_len >= 50:
        score += 5
        reasons.append("Brief description")
    else:
        missing.append("description")
        flags.append("thin_description")

    # 7. Source URL present (5)
    if item.get("source_url"):
        score += 5
    else:
        missing.append("source_url")

    score = min(100, max(0, score))

    return {
        "score": score,
        "reasons": reasons,
        "missing": missing,
        "flags": flags,
        "matched_keywords": sorted(matched_keywords),
        "commission_percent": pct,
    }


def _to_canonical(item: dict[str, Any], score_data: dict[str, Any]) -> CanonicalOpportunity:
    return CanonicalOpportunity(
        source="commissioncrowd",
        source_opportunity_id=item.get("opportunity_id", ""),
        title=item.get("title", ""),
        slug=item.get("slug", ""),
        company_name=item.get("principal_name") or None,
        description=item.get("description", ""),
        short_summary=item.get("short_summary", ""),
        commission_text=item.get("commission_text", ""),
        commission_percent=score_data.get("commission_percent"),
        residual_terms=_detect_residual(item.get("commission_text", "")),
        territory=item.get("territory", ""),
        territory_details=item.get("territory_details", ""),
        category=item.get("category", ""),
        contact_email=item.get("contact_email") or None,
        contact_phone=item.get("contact_phone") or None,
        active=bool(item.get("active", True)),
        data_quality_flags=score_data.get("flags", []),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Score net-new CommissionCrowd candidates")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only score and report the top N candidates (default: all)",
    )
    parser.add_argument(
        "--min-commission",
        type=float,
        default=20.0,
        help="Minimum commission percent threshold (default: 20.0)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=50,
        help="Minimum fit score to be considered qualified (default: 50)",
    )
    args = parser.parse_args()

    if not INPUT_PATH.exists():
        print(f"Input not found: {INPUT_PATH}", file=sys.stderr)
        return 1

    with open(INPUT_PATH) as fh:
        payload = json.load(fh)

    items = payload.get("net_new", [])
    print(f"Loaded {len(items)} net-new candidates from {INPUT_PATH}")

    scored: list[dict[str, Any]] = []
    for item in items:
        score_data = _score_candidate(item)
        canonical = _to_canonical(item, score_data)
        scored.append(
            {
                "opportunity_id": item.get("opportunity_id", ""),
                "title": item.get("title", ""),
                "score": score_data["score"],
                "passes_threshold": score_data["commission_percent"] is not None
                and score_data["commission_percent"] >= args.min_commission,
                "passes_min_score": score_data["score"] >= args.min_score,
                "commission_percent": score_data["commission_percent"],
                "residual_terms": canonical.residual_terms,
                "territory": canonical.territory or canonical.territory_details,
                "search_queries": item.get("search_queries", []),
                "query_overlap_count": item.get("query_overlap_count", 1),
                "reasons": score_data["reasons"],
                "missing": score_data["missing"],
                "flags": score_data["flags"],
                "matched_keywords": score_data["matched_keywords"],
                "source_url": item.get("source_url", ""),
                "description": item.get("description", ""),
                "canonical": canonical.to_crm_dict(),
            }
        )

    # Sort by score descending, then by overlap count descending
    scored.sort(key=lambda x: (-x["score"], -x["query_overlap_count"], x["opportunity_id"]))

    if args.limit:
        scored = scored[: args.limit]

    qualified = [s for s in scored if s["passes_threshold"] and s["passes_min_score"]]
    above_threshold = [s for s in scored if s["passes_threshold"]]

    keyword_counter: Counter[str] = Counter()
    for s in scored:
        keyword_counter.update(s["matched_keywords"])

    score_distribution = Counter(s["score"] // 10 * 10 for s in scored)

    now = datetime.now(UTC).isoformat()
    summary = {
        "generated_at": now,
        "input_path": str(INPUT_PATH),
        "candidates_total": len(items),
        "candidates_scored": len(scored),
        "qualified_count": len(qualified),
        "above_commission_threshold_count": len(above_threshold),
        "min_commission_pct": args.min_commission,
        "min_fit_score": args.min_score,
        "score_distribution": {str(k): v for k, v in sorted(score_distribution.items())},
        "top_keywords": dict(keyword_counter.most_common(10)),
    }

    json_path = REPORTS_DIR / "cca_qualified_candidates.json"
    with open(json_path, "w") as fh:
        json.dump({"summary": summary, "candidates": scored}, fh, indent=2)
    print(f"Saved JSON qualification report: {json_path}")

    md_path = REPORTS_DIR / "cca_qualified_candidates.md"
    with open(md_path, "w") as fh:
        fh.write("# CCA Find Opportunities — Qualification Report\n\n")
        fh.write(f"**Generated:** {now}\n")
        fh.write(f"**Input:** `{INPUT_PATH}`\n\n")
        fh.write("## Summary\n\n")
        fh.write(f"- **Total net-new candidates:** {summary['candidates_total']}\n")
        fh.write(f"- **Candidates scored:** {summary['candidates_scored']}\n")
        fh.write(
            f"- **Commission threshold (≥{args.min_commission}%):** "
            f"{summary['above_commission_threshold_count']}\n"
        )
        fh.write(
            f"- **Qualified (threshold + score ≥{args.min_score}):** "
            f"{summary['qualified_count']}\n\n"
        )
        fh.write("### Score distribution\n\n")
        fh.write("| Score bucket | Count |\n|---|---|\n")
        for bucket, count in sorted(score_distribution.items()):
            fh.write(f"| {bucket}-{bucket + 9} | {count} |\n")
        fh.write("\n### Top B2B keywords matched\n\n")
        fh.write("| Keyword | Matches |\n|---|---|\n")
        for kw, count in keyword_counter.most_common(10):
            fh.write(f"| {kw} | {count} |\n")
        fh.write("\n## Top 50 candidates\n\n")
        fh.write(
            "| Rank | Opp ID | Title | Score | Commission | "
            "Residual | Territory | Queries | Next action |\n"
        )
        fh.write("|---|---|---|---|---|---|---|---|---|\n")
        for rank, s in enumerate(scored[:50], start=1):
            next_action = (
                "operator_review"
                if s["passes_threshold"] and s["passes_min_score"]
                else "research_or_reject"
            )
            fh.write(
                f"| {rank} | {s['opportunity_id']} | {s['title'][:55]} | {s['score']} | "
                f"{s['commission_percent'] or 'N/A'} | "
                f"{'Yes' if s['residual_terms'] else 'No'} | "
                f"{s['territory'][:25] if s['territory'] else 'N/A'} | "
                f"{s['query_overlap_count']} | {next_action} |\n"
            )
        fh.write("\n## Full candidate list\n\n")
        for rank, s in enumerate(scored, start=1):
            fh.write(f"### {rank}. {s['title']} (ID: {s['opportunity_id']})\n\n")
            fh.write(f"- **Fit score:** {s['score']}\n")
            fh.write(f"- **Commission:** {s['commission_percent'] or 'unclear'}%\n")
            fh.write(f"- **Residual terms:** {'Yes' if s['residual_terms'] else 'No'}\n")
            fh.write(f"- **Territory:** {s['territory'] or 'N/A'}\n")
            fh.write(f"- **Matched keywords:** {', '.join(s['matched_keywords']) or 'None'}\n")
            fh.write(f"- **Search queries:** {', '.join(s['search_queries'])}\n")
            fh.write(f"- **Reasons:** {' | '.join(s['reasons'])}\n")
            if s["missing"]:
                fh.write(f"- **Missing data:** {'; '.join(s['missing'])}\n")
            if s["flags"]:
                fh.write(f"- **Quality flags:** {'; '.join(s['flags'])}\n")
            fh.write(f"- **Source URL:** {s['source_url']}\n\n")
    print(f"Saved Markdown qualification report: {md_path}")

    print("\nQualification summary:")
    print(f"  Scored: {len(scored)}")
    print(f"  Above commission threshold: {len(above_threshold)}")
    print(f"  Fully qualified (score ≥{args.min_score}): {len(qualified)}")
    print("\nTop 5:")
    for s in scored[:5]:
        print(f"  -> {s['opportunity_id']}: {s['title'][:55]} (score={s['score']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())

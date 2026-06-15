#!/usr/bin/env python3
"""Capture detail-level opportunity data from CommissionCrowd via browser SPA.

This script:
  1. Loads the qualified candidate report.
  2. Selects the top N fully qualified candidates (default 20).
  3. Logs into CommissionCrowd through the browser, navigates to each opportunity
     detail page via SPA hash, and extracts rich fields from the DOM.
  4. Writes a read-only detail report (JSON + Markdown).

No state-changing actions are performed (no apply, no favourite, no message,
no connect, no approve).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.config import load_settings

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
QUALIFIED_PATH = REPORTS_DIR / "cca_qualified_candidates.json"
BASE_URL = "https://www.commissioncrowd.com"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture opportunity detail for top qualified candidates"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Number of top qualified candidates to enrich (default: 20)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=50,
        help="Minimum fit score to include (default: 50)",
    )
    return parser.parse_args()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_truncate(text: str | None, max_len: int = 1000) -> str:
    if not text:
        return ""
    return str(text)[:max_len]


def _extract_category(description: str) -> str:
    """Naive category inference from description text (best-effort)."""
    text = description.lower()
    categories: list[str] = []
    if any(k in text for k in ("saas", "software", "platform", "api")):
        categories.append("SaaS / Software")
    if any(k in text for k in ("cybersecurity", "security", "threat", "breach")):
        categories.append("Cybersecurity")
    if any(k in text for k in ("ai", "machine learning", "ml ", "artificial intelligence")):
        categories.append("AI / ML")
    if any(k in text for k in ("automation", "automate", "workflow")):
        categories.append("Automation")
    if any(k in text for k in ("data", "analytics", "insights")):
        categories.append("Data / Analytics")
    if any(k in text for k in ("managed service", "services", "consulting")):
        categories.append("Services")
    return " / ".join(categories) if categories else ""


def _login(page, settings: Any) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill('input[type="email"]', settings.commissioncrowd_username)
    page.fill('input[type="password"]', settings.commissioncrowd_password)
    page.click('button[type="submit"]')
    for _ in range(25):
        page.wait_for_timeout(1000)
        if "#/agent" in page.url:
            break
    page.wait_for_timeout(3000)


def _navigate_opportunity(page: Any, opp_id: str) -> None:
    """Use SPA hash navigation to open an opportunity detail page."""
    page.evaluate(f"window.location.hash = '#/opportunities/{opp_id}'")
    page.wait_for_timeout(7000)


def _extract_detail(page: Any, opp_id: str) -> dict[str, Any]:
    """Extract opportunity detail fields from the rendered SPA page.

    Uses a progressive extraction strategy:
      1. Try structured selectors for title/description.
      2. Fall back to heuristics on innerText lines.
    """
    structured = page.evaluate(
        """() => {
            const h1 = document.querySelector('h1');
            const h2 = document.querySelector('h2');
            const title = (h1 ? h1.innerText.trim() : '') || (h2 ? h2.innerText.trim() : '');

            const descSelectors = [
                '[data-testid="opportunity-description"]',
                '.opportunity-description',
                '.description',
                '[class*="description"]',
                'p'
            ];
            let description = '';
            for (const sel of descSelectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.trim().length > 50) {
                    description = el.innerText.trim();
                    break;
                }
            }

            const allLinks = Array.from(document.querySelectorAll('a'));
            const websiteLink = allLinks.find(a => {
                const t = a.innerText.toLowerCase();
                return (
                    t.includes('visit website') ||
                    t.includes('company website') ||
                    t.includes('learn more') ||
                    t.includes('visit')
                );
            });

            return {
                title: title,
                description: description,
                website_url: websiteLink ? websiteLink.href : ''
            };
        }"""
    )

    text = page.evaluate("() => document.body.innerText || ''")
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    title = structured.get("title", "")
    if not title:
        title = lines[1] if len(lines) > 1 else (lines[0] if lines else "")

    # Description: prefer structured; fall back to longest line after title
    description = structured.get("description", "")
    if not description:
        for line in lines:
            if len(line) >= 120 and line != title:
                description = line
                break

    # Commission text: prefer lines with % near commission keywords
    commission_text = ""
    for line in lines[:100]:
        lower = line.lower()
        if "%" in line and any(
            k in lower for k in ("commission", "comm", "earn", "payout", "residual", "upfront")
        ):
            commission_text = line
            break
    if not commission_text:
        for line in lines[:100]:
            if "%" in line and len(line) < 250:
                commission_text = line
                break

    # Territory / location
    territory = ""
    for line in lines[:100]:
        lower = line.lower()
        if any(k in lower for k in ("territory", "location", "region", "countries", "worldwide")):
            territory = line
            break

    # Principal/company: line near "about the company" or "company name"
    principal = ""
    for i, line in enumerate(lines[:80]):
        lower = line.lower()
        if any(k in lower for k in ("about the company", "about us", "who we are", "company name")):
            principal = lines[i + 1] if i + 1 < len(lines) else ""
            break

    return {
        "title": title[:300],
        "commission_text": commission_text[:300],
        "territory": territory[:200],
        "description": description[:2000],
        "principal": principal[:200],
        "website_url": structured.get("website_url", ""),
        "raw_text_sample": _safe_truncate(text, 2000),
    }


def _extract_commission_percent(text: str) -> float | None:
    import re

    if not text:
        return None
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


def _detect_residual(text: str) -> bool:
    if not text:
        return False
    return any(
        word in text.lower()
        for word in ("residual", "lifetime", "recurring", "ongoing", "monthly", "annuity")
    )


def main() -> int:
    args = _parse_args()

    if not QUALIFIED_PATH.exists():
        print(f"Qualified report not found: {QUALIFIED_PATH}", file=sys.stderr)
        return 1

    with open(QUALIFIED_PATH) as fh:
        qualified_payload = json.load(fh)

    candidates = qualified_payload.get("candidates", [])
    top_candidates = [
        c
        for c in candidates
        if c.get("passes_threshold")
        and c.get("passes_min_score")
        and c.get("score", 0) >= args.min_score
    ][: args.limit]

    print(f"Selected {len(top_candidates)} candidates for detail capture (limit={args.limit})")

    settings = load_settings()
    enriched: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _login(page, settings)
        print(f"Logged in: {page.url}")

        for c in top_candidates:
            opp_id = c.get("opportunity_id", "")
            if not opp_id:
                errors.append({"candidate": c, "error": "missing opportunity_id"})
                continue

            print(f"  Opening {opp_id}: {c.get('title', '')[:50]}")
            try:
                _navigate_opportunity(page, opp_id)
                extracted = _extract_detail(page, opp_id)

                combined_text = " ".join(
                    filter(
                        None,
                        [
                            extracted["title"],
                            extracted["commission_text"],
                            extracted["description"],
                            extracted["territory"],
                        ],
                    )
                )
                pct = _extract_commission_percent(combined_text)
                residual = _detect_residual(combined_text)
                category = _extract_category(extracted["description"])

                enriched.append(
                    {
                        "opportunity_id": opp_id,
                        "fit_score": c.get("score", 0),
                        "score_reasons": c.get("reasons", []),
                        "matched_keywords": c.get("matched_keywords", []),
                        "search_queries": c.get("search_queries", []),
                        "query_overlap_count": c.get("query_overlap_count", 1),
                        "title": extracted["title"],
                        "commission_text": extracted["commission_text"],
                        "commission_percent": pct,
                        "residual_terms": residual,
                        "territory": extracted["territory"],
                        "description": extracted["description"],
                        "principal": extracted["principal"],
                        "website_url": extracted["website_url"],
                        "source_url": f"{BASE_URL}/app/#/opportunities/{opp_id}",
                        "category": category,
                        "raw_text_sample": extracted["raw_text_sample"],
                        "fetched_at": _now(),
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "opportunity_id": opp_id,
                        "title": c.get("title", ""),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        browser.close()

    now = _now()
    summary = {
        "generated_at": now,
        "qualified_report": str(QUALIFIED_PATH),
        "requested_limit": args.limit,
        "min_score": args.min_score,
        "attempted": len(top_candidates),
        "succeeded": len(enriched),
        "failed": len(errors),
    }

    json_path = REPORTS_DIR / "cca_detail_capture.json"
    with open(json_path, "w") as fh:
        json.dump({"summary": summary, "enriched": enriched, "errors": errors}, fh, indent=2)
    print(f"Saved JSON detail report: {json_path}")

    md_path = REPORTS_DIR / "cca_detail_capture.md"
    with open(md_path, "w") as fh:
        fh.write("# CCA Top Qualified Candidates — Browser Detail Capture Report\n\n")
        fh.write(f"**Generated:** {now}\n")
        fh.write(f"**Source:** `{QUALIFIED_PATH}`\n\n")
        fh.write("## Summary\n\n")
        fh.write(f"- **Requested limit:** {summary['requested_limit']}\n")
        fh.write(f"- **Minimum fit score:** {summary['min_score']}\n")
        fh.write(f"- **Attempted:** {summary['attempted']}\n")
        fh.write(f"- **Succeeded:** {summary['succeeded']}\n")
        fh.write(f"- **Failed:** {summary['failed']}\n\n")

        if errors:
            fh.write("## Errors\n\n")
            for e in errors:
                fh.write(f"- `{e.get('opportunity_id', 'N/A')}`: {e.get('error', 'unknown')}\n")
            fh.write("\n")

        fh.write("## Enriched Candidates\n\n")
        for rank, rec in enumerate(enriched, start=1):
            fh.write(f"### {rank}. {rec['title']} (ID: {rec['opportunity_id']})\n\n")
            fh.write(f"- **Fit score:** {rec['fit_score']}\n")
            fh.write(f"- **Commission:** {rec['commission_text'] or 'N/A'} ")
            if rec["commission_percent"] is not None:
                fh.write(f"({rec['commission_percent']}%)\n")
            else:
                fh.write("(rate unclear)\n")
            fh.write(f"- **Residual terms:** {'Yes' if rec['residual_terms'] else 'No'}\n")
            fh.write(f"- **Territory:** {rec['territory'] or 'N/A'}\n")
            fh.write(f"- **Category:** {rec['category'] or 'N/A'}\n")
            fh.write(f"- **Principal:** {rec['principal'] or 'N/A'}\n")
            fh.write(f"- **Source queries:** {', '.join(rec['search_queries'])}\n")
            fh.write(f"- **Matched keywords:** {', '.join(rec['matched_keywords'])}\n")
            fh.write(f"- **Website URL:** {rec['website_url'] or 'N/A'}\n")
            fh.write(f"- **Source URL:** {rec['source_url']}\n")
            fh.write(f"- **Description:**\n\n{_safe_truncate(rec['description'], 500)}\n\n")
            if rec["score_reasons"]:
                fh.write(f"- **Score reasons:** {' | '.join(rec['score_reasons'])}\n")
            fh.write("\n")
    print(f"Saved Markdown detail report: {md_path}")

    print("\nDetail capture summary:")
    print(f"  Attempted: {summary['attempted']}")
    print(f"  Succeeded: {summary['succeeded']}")
    print(f"  Failed: {summary['failed']}")
    if enriched:
        print("\nTop 3 enriched:")
        for rec in enriched[:3]:
            pct = rec["commission_percent"]
            pct_str = f"{pct}%" if pct is not None else "N/A"
            print(
                f"  -> {rec['opportunity_id']}: {rec['title'][:55]} "
                f"(commission={pct_str}, territory={rec['territory'] or 'N/A'})"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())

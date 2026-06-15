#!/usr/bin/env python3
"""Run deeper web research on top qualified CommissionCrowd candidates.

This script:
  1. Loads the detail-capture report.
  2. For each enriched candidate, performs read-only web searches on the
     principal/company name and opportunity title.
  3. Summarizes findings into a JSON + Markdown report.

No outbound emails, CRM writes, or platform actions are performed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.config import load_settings

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
DETAIL_PATH = REPORTS_DIR / "cca_detail_capture.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deeper web research on top qualified candidates"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Number of detail-enriched candidates to research (default: 20)",
    )
    parser.add_argument(
        "--search-hits",
        type=int,
        default=5,
        help="Search hits per candidate (default: 5)",
    )
    parser.add_argument(
        "--extract-pages",
        action="store_true",
        help="Also extract text from the first non-generic domain page found",
    )
    return parser.parse_args()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clean_name(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", " ", name).strip()


def _search_query(rec: dict[str, Any]) -> str:
    """Build a focused research query from the captured detail record."""
    parts: list[str] = []

    principal = _clean_name(rec.get("principal"))
    if principal and len(principal) > 3:
        parts.append(principal)

    title = _clean_name(rec.get("title"))
    if title and title.lower() != "commissioncrowd":
        title = re.sub(r"\s+[-–|].*", "", title)
        title = re.sub(r"\b\d+%.*", "", title)
        parts.append(title)

    if not parts:
        title = _clean_name(rec.get("commission_text"))
        if title:
            title = re.sub(r"\s+[-–|].*", "", title)
            title = re.sub(r"\b\d+%.*", "", title)
            parts.append(title)

    query = " ".join(parts)
    if not query:
        query = rec.get("description", "")[:80]
    return query[:120]


def _summarize(hits: list[dict[str, str]]) -> dict[str, Any]:
    """Build a structured summary from search result descriptions."""
    ignore = {
        "commissioncrowd.com",
        "linkedin.com",
        "facebook.com",
        "twitter.com",
        "instagram.com",
        "youtube.com",
        "tiktok.com",
        "crunchbase.com",
        "trustpilot.com",
        "glassdoor.com",
    }

    signals: dict[str, Any] = {
        "company_website_found": False,
        "has_about_page": False,
        "has_contact_page": False,
        "mentions_commission": False,
        "mentions_b2b": False,
        "mentions_software": False,
        "mentions_ai": False,
        "estimated_employee_count": "",
        "geography": "",
        "key_pages": [],
        "search_hit_count": len(hits),
    }

    combined = " ".join(h.get("description", "") for h in hits).lower()
    if not combined:
        return signals

    signals["mentions_commission"] = any(
        word in combined
        for word in ("commission", "affiliate", "partner", "sales partner")
    )
    signals["mentions_b2b"] = any(
        word in combined
        for word in ("b2b", "enterprise", "business to business", "corporate", "smb")
    )
    signals["mentions_software"] = any(
        word in combined for word in ("saas", "software", "platform", "api", "cloud")
    )
    signals["mentions_ai"] = any(
        word in combined
        for word in ("ai", "artificial intelligence", "machine learning", "ml ")
    )

    for h in hits:
        url = h.get("url", "").lower()
        title = h.get("title", "").lower()
        if any(k in url or k in title for k in ("/about", "/company", "about us")):
            signals["has_about_page"] = True
        if any(k in url or k in title for k in ("/contact", "contact us")):
            signals["has_contact_page"] = True

        domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
        domain = domain_match.group(1).lower() if domain_match else ""
        if domain and not any(ignored in domain for ignored in ignore):
            signals["key_pages"].append(
                {"url": h.get("url", ""), "title": h.get("title", "")[:100]}
            )

    if signals["key_pages"]:
        signals["company_website_found"] = True

    for phrase in ("based in", "headquartered in", "located in"):
        idx = combined.find(phrase)
        if idx != -1:
            signals["geography"] = (
                combined[idx : idx + 80].strip().replace("\n", " ")
            )
            break

    return signals


def _web_search(query: str, limit: int) -> list[dict[str, str]]:
    """Use Hermes web_search tool via hermes_tools import."""
    from hermes_tools import web_search

    result = web_search(query, limit=limit)
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": item.get("description", ""),
        }
        for item in result.get("data", {}).get("web", [])
    ]


def _web_extract(urls: list[str]) -> list[dict[str, Any]]:
    """Use Hermes web_extract tool via hermes_tools import."""
    from hermes_tools import web_extract

    if not urls:
        return []
    result = web_extract(urls=urls[:3])
    return [
        {
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "content": item.get("content", "")[:2000],
            "error": item.get("error", ""),
        }
        for item in result.get("results", [])
    ]


def _select_domain_url(hits: list[dict[str, str]]) -> str | None:
    """Pick the first non-generic company website URL from search hits."""
    ignore = {
        "commissioncrowd.com",
        "linkedin.com",
        "facebook.com",
        "twitter.com",
        "instagram.com",
        "youtube.com",
        "tiktok.com",
        "crunchbase.com",
        "trustpilot.com",
        "glassdoor.com",
    }
    for h in hits:
        url = h.get("url", "")
        m = re.search(r"https?://(?:www\.)?([^/]+)", url)
        if not m:
            continue
        domain = m.group(1).lower()
        if any(ignored in domain for ignored in ignore):
            continue
        return url
    return None


def main() -> int:
    args = _parse_args()
    _ = load_settings()

    if not DETAIL_PATH.exists():
        print(f"Detail report not found: {DETAIL_PATH}", file=sys.stderr)
        return 1

    with open(DETAIL_PATH) as fh:
        detail_payload = json.load(fh)

    enriched = detail_payload.get("enriched", [])[: args.limit]
    print(
        f"Running deeper web research on {len(enriched)} candidates "
        f"(limit={args.limit}, search_hits={args.search_hits})"
    )

    researched: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for rank, rec in enumerate(enriched, start=1):
        opp_id = rec.get("opportunity_id", "")
        query = _search_query(rec)
        print(f"  {rank:2}. ID={opp_id} query={query!r}")

        if not query:
            errors.append({"opportunity_id": opp_id, "error": "no research query derived"})
            continue

        try:
            hits = _web_search(query, limit=args.search_hits)
        except Exception as exc:
            print(f"    web_search error: {exc}", file=sys.stderr)
            errors.append({"opportunity_id": opp_id, "error": str(exc)})
            continue

        candidate_rec = dict(rec)
        candidate_rec["research_query"] = query
        candidate_rec["web_search_hits"] = hits
        candidate_rec["findings"] = _summarize(hits)

        extracted: list[dict[str, Any]] = []
        if args.extract_pages:
            domain_url = _select_domain_url(hits)
            if domain_url:
                print(f"      Extracting {domain_url}")
                try:
                    extracted = _web_extract([domain_url])
                except Exception as exc:
                    print(f"      web_extract error: {exc}", file=sys.stderr)
        candidate_rec["web_extracted_pages"] = extracted
        candidate_rec["researched_at"] = _now()

        researched.append(candidate_rec)

    now = _now()
    summary = {
        "generated_at": now,
        "detail_report": str(DETAIL_PATH),
        "candidates_researched": len(researched),
        "errors": len(errors),
        "search_hits_per_candidate": args.search_hits,
        "extracted_pages": args.extract_pages,
    }

    json_path = REPORTS_DIR / "cca_web_research.json"
    with open(json_path, "w") as fh:
        json.dump(
            {"summary": summary, "researched": researched, "errors": errors},
            fh,
            indent=2,
        )
    print(f"Saved JSON research report: {json_path}")

    md_path = REPORTS_DIR / "cca_web_research.md"
    with open(md_path, "w") as fh:
        fh.write(
            "# CCA Top Qualified Candidates — Deeper Web Research Report\n\n"
        )
        fh.write(f"**Generated:** {now}\n")
        fh.write(f"**Source detail report:** `{DETAIL_PATH}`\n\n")
        fh.write("## Summary\n\n")
        fh.write(f"- **Candidates researched:** {summary['candidates_researched']}\n")
        fh.write(f"- **Errors:** {summary['errors']}\n")
        fh.write(f"- **Search hits per candidate:** {summary['search_hits_per_candidate']}\n")
        fh.write(f"- **Domain pages extracted:** {summary['extracted_pages']}\n\n")

        if errors:
            fh.write("## Errors\n\n")
            for e in errors:
                fh.write(
                    f"- `{e.get('opportunity_id', 'N/A')}`: {e.get('error', 'unknown')}\n"
                )
            fh.write("\n")

        for rank, rec in enumerate(researched, start=1):
            findings = rec.get("findings", {})
            fh.write(f"## {rank}. {rec['title']} (ID: {rec['opportunity_id']})\n\n")
            fh.write(f"**Research query:** `{rec.get('research_query', '')}`\n\n")
            fh.write(f"- **Fit score:** {rec['fit_score']}\n")
            fh.write(
                f"- **Commission:** {rec['commission_text']} "
                f"({rec['commission_percent']}%)\n"
            )
            fh.write(f"- **Territory:** {rec['territory'] or 'N/A'}\n")
            fh.write(f"- **Principal:** {rec['principal'] or 'N/A'}\n")
            fh.write(f"- **Category:** {rec['category'] or 'N/A'}\n")
            fh.write(
                f"- **Web signals:** B2B={findings.get('mentions_b2b')}, "
                f"software={findings.get('mentions_software')}, "
                f"AI={findings.get('mentions_ai')}, "
                f"commission={findings.get('mentions_commission')}\n"
            )
            fh.write(
                f"- **Company web presence:** "
                f"{'Found' if findings.get('company_website_found') else 'Not found'} "
                f"(about={findings.get('has_about_page')}, "
                f"contact={findings.get('has_contact_page')})\n"
            )
            fh.write(f"- **Geography hint:** {findings.get('geography') or 'N/A'}\n")

            fh.write("\n### Search hits\n\n")
            for i, hit in enumerate(rec.get("web_search_hits", [])[:5], start=1):
                fh.write(f"{i}. [{hit.get('title', 'Untitled')}]({hit.get('url', '')})\n")
                fh.write(f"   \u003e {hit.get('description', '')[:180]}\n\n")

            if rec.get("web_extracted_pages"):
                fh.write("\n### Extracted domain page\n\n")
                for e in rec["web_extracted_pages"]:
                    fh.write(f"- [{e.get('title', 'Untitled')}]({e.get('url', '')})\n")
                    fh.write(
                        f"  \u003e {e.get('content', '').replace(chr(10), ' ')[:240]}\n\n"
                    )

            fh.write("\n---\n\n")
    print(f"Saved Markdown research report: {md_path}")

    print("\nResearch summary:")
    print(f"  Candidates: {summary['candidates_researched']}")
    print(f"  Errors: {summary['errors']}")
    for rec in researched[:5]:
        sig = rec.get("findings", {})
        print(
            f"  -> {rec['opportunity_id']}: "
            f"website_found={sig.get('company_website_found')}, "
            f"b2b={sig.get('mentions_b2b')}, "
            f"commission_mentioned={sig.get('mentions_commission')}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

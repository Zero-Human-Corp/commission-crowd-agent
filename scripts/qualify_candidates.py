#!/usr/bin/env python3
"""CCA qualification script — open top candidates and extract details.

Targets:
  1. Favourites (3 items) — click links to get opp IDs and full details
  2. Conversations (2 items) — click rows to get linked opp IDs and full details
  3. Featured/Matching (top 5) — click cards to get full details

Extracts: opp_id, title, principal, commission, residuals, territory, description, URL.
"""

from __future__ import annotations
import json, sys, re
from pathlib import Path
from datetime import UTC, datetime
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from commission_crowd_agent.config import load_settings

SETTINGS = load_settings()
BASE_URL = "https://www.commissioncrowd.com"
REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")


def _now():
    return datetime.now(UTC).isoformat()


def _login(page):
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill('input[type="email"]', SETTINGS.commissioncrowd_username)
    page.fill('input[type="password"]', SETTINGS.commissioncrowd_password)
    page.click('button[type="submit"]')
    for _ in range(25):
        page.wait_for_timeout(1000)
        if "#/agent" in page.url:
            break
    page.wait_for_timeout(3000)


def _extract_detail(page, opp_url: str) -> dict:
    """Navigate to opportunity detail via SPA hash change and extract key fields."""
    # Navigate via SPA hash change to preserve auth state
    m = re.search(r"#/opportunities?/(\d+)", opp_url)
    opp_id = m.group(1) if m else ""
    if not opp_id:
        return {"opportunity_id": "", "title": "", "url": opp_url, "error": "no_opp_id"}

    page.evaluate(f"window.location.hash = '#/opportunities/{opp_id}'")
    page.wait_for_timeout(7000)

    # Extract text content
    text = page.evaluate("() => document.body.innerText")
    url = page.url

    lines = text.split("\n")
    # Find a meaningful title (not just "CommissionCrowd")
    title = ""
    for line in lines[:30]:
        line = line.strip()
        if (
            line
            and line != "CommissionCrowd"
            and len(line) > 20
            and (
                "%" in line or "$" in line or "£" in line or "Commission" in line or "Deal" in line
            )
        ):
            title = line[:200]
            break
    if not title:
        title = lines[1][:200] if len(lines) > 1 else (lines[0][:200] if lines else "")

    # Look for commission, residual, territory in text
    commission_match = re.search(r"(\d+%)\s*(?:commission|commissions)", text, re.I)
    residual_match = re.search(r"(\d+%)\s*(?:residual|residuals|recurring)", text, re.I)
    territory_match = re.search(r"(?:territor(?:y|ies)|global|worldwide|international)", text, re.I)

    # Principal/company name
    principal = ""
    for i, line in enumerate(lines[:50]):
        if "about the company" in line.lower():
            principal = lines[i + 1].strip() if i + 1 < len(lines) else ""
            break

    return {
        "opportunity_id": opp_id,
        "title": title,
        "url": url,
        "principal": principal[:100],
        "commission": commission_match.group(1) if commission_match else "",
        "residuals": residual_match.group(1) if residual_match else "",
        "territory_hint": "global" if territory_match else "",
        "text_sample": text[:1000],
        "retrieved_at": _now(),
    }


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _login(page)
        print(f"logged in: {page.url}")

        # Load inventory to get URLs
        with open(REPORTS_DIR / "cca_opportunity_state_registry.json") as fh:
            registry = json.load(fh)

        candidates = []

        # Favourites — look for any link with /opportunities/ in the dashboard sidebar
        print("\n=== FAVOURITES ===")
        # First, get all links from sidebar
        sidebar_links = page.evaluate("""
        () => {
            const items = [];
            const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6, .section-title, .panel-title');
            let container = null;
            for (const h of headings) {
                if (h.innerText.toLowerCase().includes('favourite') || h.innerText.toLowerCase().includes('favorite')) {
                    container = h.closest('.panel, .card, .widget, .sidebar-section, section, div[class*="sidebar"]') || h.parentElement;
                    break;
                }
            }
            if (!container) return items;
            const links = container.querySelectorAll('a[href*="/opportunities/"]');
            for (const link of links) {
                const m = link.href.match(/\\/opportunities\\/(\\d+)/);
                const oppId = m ? m[1] : '';
                items.push({opp_id: oppId, href: link.href, text: link.innerText.trim()});
            }
            return items;
        }
        """)
        seen_fav = set()
        for fav in sidebar_links:
            opp_id = fav.get("opp_id", "")
            url = fav.get("href", "")
            if not opp_id or not url or opp_id in seen_fav:
                continue
            seen_fav.add(opp_id)
            print(f"  OPEN: {url}")
            detail = _extract_detail(page, url)
            print(f"    -> opp_id={detail['opportunity_id']} title={detail['title'][:50]}")
            candidates.append(
                {
                    **detail,
                    "source": "favourite",
                    "original_title": fav.get("text", ""),
                }
            )

        # Conversations
        print("\n=== CONVERSATIONS ===")
        for msg in registry.get("conversations", {}).get("messages", []):
            # Try to infer opp URL from subject text
            subject = msg.get("subject", "")
            opp_id = msg.get("linked_opportunity_id", "")
            if not opp_id:
                # Search for numeric ID in subject
                m = re.search(r"\b(\d{5,})\b", subject)
                if m:
                    opp_id = m.group(1)
            if opp_id:
                url = f"{BASE_URL}/app/#/opportunities/{opp_id}"
            else:
                print(f"  SKIP (no opp_id): {subject[:50]}")
                continue
            print(f"  OPEN: {url}")
            detail = _extract_detail(page, url)
            print(f"    -> opp_id={detail['opportunity_id']} title={detail['title'][:50]}")
            candidates.append(
                {
                    **detail,
                    "source": "conversation",
                    "message_id": msg.get("message_id", ""),
                    "sender": msg.get("sender", ""),
                    "classification": msg.get("classification", ""),
                }
            )

        # Featured/Matching — top 5
        print("\n=== FEATURED/MATCHING ===")
        for feat in registry.get("featured_matching", [])[:5]:
            url = feat.get("source_url", "")
            if not url or not re.search(r"/opportunities?/\d+", url):
                print(f"  SKIP (no opp URL): {feat.get('title', '')[:50]}")
                continue
            print(f"  OPEN: {url}")
            detail = _extract_detail(page, url)
            print(f"    -> opp_id={detail['opportunity_id']} title={detail['title'][:50]}")
            candidates.append(
                {
                    **detail,
                    "source": "featured_matching",
                    "original_title": feat.get("title", ""),
                }
            )

        browser.close()

    # Save candidates
    path = REPORTS_DIR / "cca_qualified_candidates.json"
    with open(path, "w") as fh:
        json.dump({"candidates": candidates, "retrieved_at": _now()}, fh, indent=2)
    print(f"\nSaved {len(candidates)} candidates to {path}")


if __name__ == "__main__":
    sys.exit(main() or 0)

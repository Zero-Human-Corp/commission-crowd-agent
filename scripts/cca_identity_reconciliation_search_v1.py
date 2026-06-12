#!/usr/bin/env python3
"""
cca_identity_reconciliation_search_v1.py
Authenticated read-only search for candidate identity reconciliation.
Hard safety: no Apply, Submit, Save, Favourite, Message, Connect clicks.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://www.commissioncrowd.com"
LOGIN_URL = f"{BASE_URL}/login"
DASHBOARD_URL = f"{BASE_URL}/app/#/agent/dashboard"
SEARCH_URL = f"{BASE_URL}/app/#/agent/opportunities/search_opportunities"

# Target candidates
TARGETS = {
    "39292": {
        "historical_title": "$1920+/Year Per Enterprise Deal | GDPR-Compliant AI Chatbots | Fast Sales Cycle | Earn 20% Recurring",
        "fragments": ["GDPR-Compliant AI Chatbots", "GDPR", "AI Chatbots"],
    },
    "39452": {
        "historical_title": "20% LIFETIME Residuals! Managed IT & Cybersecurity Services for SMBs | 100% Retention | Fast Sales Cycle",
        "fragments": ["Managed IT", "Cybersecurity", "Bonelli"],
    },
    "15256": {
        "historical_title": "Anonymous Incident Reporting and Case Management platform offering 20-30% commission and 15% on annual renewals for the lifetime of client.",
        "fragments": ["Anonymous Incident Reporting", "Incident Reporting"],
    },
    "36575": {
        "historical_title": "Earn $1K–$18K Per Deal | 20–30% Commission + 5% Lifetime Residuals | AI & Predictive Analytics Consulting.",
        "fragments": ["Predictive Analytics", "AI & Predictive"],
    },
    "11419": {
        "historical_title": "Earn Up to $1M in Commissions while Helping Eye Care Practices TRANSFORM Patient Care! ...",
        "fragments": ["Eye Care", "AI Software for Eye Care", "Sustainable Skincare"],
    },
}


def _safe_hash_nav(page, hash_path: str, wait_ms: int = 5000) -> None:
    """SPA-safe hash navigation preserving auth."""
    page.evaluate(f"window.location.hash = '{hash_path}'")
    page.wait_for_timeout(wait_ms)


def _extract_visible_cards(page) -> list[dict]:
    """Read-only card extraction. No clicks."""
    js = """
    () => {
        const cards = document.querySelectorAll('.search-results .card, .opportunity-card, .opportunity-item, [class*="opportunity"]');
        const items = [];
        for (const card of cards) {
            const text = card.innerText.trim();
            const link = card.querySelector('a[href*="/opportunities/"]');
            let oppId = '';
            let href = '';
            if (link) {
                const m = link.href.match(/\\/opportunities\\/(\\d+)/);
                if (m) oppId = m[1];
                href = link.href;
            }
            const title = text.split('\\n')[0].trim();
            if (title.length > 10 && !title.toLowerCase().includes('close') && !title.toLowerCase().includes('there were errors')) {
                items.push({title, full_text: text, opp_id: oppId, href});
            }
        }
        return items;
    }
    """
    return page.evaluate(js)


def _search_by_fragment(page, fragment: str) -> list[dict]:
    """Use the Find Opportunities search box with a text fragment."""
    # Ensure we are on search route
    if "search_opportunities" not in page.url:
        _safe_hash_nav(page, "#/agent/opportunities/search_opportunities", 5000)

    # Try to locate and fill search input
    try:
        # Common selectors for CommissionCrowd search
        selectors = [
            'input[placeholder*="Search"]',
            'input[type="search"]',
            'input[name="search"]',
            'input[placeholder*="search"]',
            'input[placeholder*="Search"]',
        ]
        inp = None
        for sel in selectors:
            if page.locator(sel).count() > 0:
                inp = page.locator(sel).first
                break
        if inp:
            inp.fill("")
            inp.fill(fragment)
            page.wait_for_timeout(500)
            # Trigger search via Enter
            inp.press("Enter")
            page.wait_for_timeout(4000)
    except Exception as e:
        print(f"Search input interaction error: {e}", file=sys.stderr)

    return _extract_visible_cards(page)


def _search_by_id_in_url(page, opp_id: str) -> list[dict]:
    """Try direct hash navigation to opportunity detail."""
    _safe_hash_nav(page, f"#/opportunities/{opp_id}", 7000)
    # Extract any visible title from body
    js = """
    () => {
        const text = document.body.innerText;
        const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 10);
        // Look for lines with commission signals
        const commissionLines = lines.filter(l => /[%$£€]|Commission|Earn|Residual|Deal/.test(l));
        return {
            url: window.location.href,
            title_line: lines[0] || '',
            commission_lines: commissionLines.slice(0, 5),
            all_lines: lines.slice(0, 30),
        };
    }
    """
    result = page.evaluate(js)
    return [
        {
            "title": result.get("title_line", ""),
            "full_text": "\n".join(result.get("all_lines", [])),
            "opp_id": opp_id,
            "href": result.get("url", ""),
            "detail_extraction": True,
        }
    ]


def main() -> int:
    # Load credentials from shared.env
    env_path = Path("/home/ubuntu/hermes-control/secrets/shared.env")
    creds = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("COMMISSIONCROWD_USERNAME="):
                creds["username"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("COMMISSIONCROWD_PASSWORD="):
                creds["password"] = line.split("=", 1)[1].strip().strip('"').strip("'")

    if not creds.get("username") or not creds.get("password"):
        print("Missing CommissionCrowd credentials in shared.env", file=sys.stderr)
        return 1

    results: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # Login
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.fill('input[type="email"]', creds["username"])
        page.fill('input[type="password"]', creds["password"])
        page.click('button[type="submit"]')
        page.wait_for_timeout(7000)

        # MFA guard
        if page.locator("input[name='code'], input[name='verification_code']").count() > 0:
            print("MFA required — stopping", file=sys.stderr)
            browser.close()
            return 1

        for opp_id, meta in TARGETS.items():
            candidate_results = {
                "historical_title": meta["historical_title"],
                "searches": [],
                "found_cards": [],
                "timestamp": datetime.now(UTC).isoformat(),
            }

            # Strategy 1: search by each title fragment
            for frag in meta["fragments"]:
                cards = _search_by_fragment(page, frag)
                candidate_results["searches"].append(
                    {
                        "query": frag,
                        "card_count": len(cards),
                        "cards": cards,
                    }
                )
                candidate_results["found_cards"].extend(cards)

            # Strategy 2: direct URL by ID
            detail_cards = _search_by_id_in_url(page, opp_id)
            candidate_results["direct_url_attempt"] = detail_cards[0] if detail_cards else {}

            results[opp_id] = candidate_results

            # Navigate back to search for next candidate
            _safe_hash_nav(page, "#/agent/opportunities/search_opportunities", 4000)

        browser.close()

    out_path = Path(
        "/home/ubuntu/hermes-control/reports/cca_identity_reconciliation_platform_search_v1.json"
    )
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Results written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

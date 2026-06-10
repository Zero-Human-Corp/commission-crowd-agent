#!/usr/bin/env python3
"""Diagnostic: Find Opportunities page inspection."""

from __future__ import annotations
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from commission_crowd_agent.config import load_settings

SETTINGS = load_settings()
BASE_URL = "https://www.commissioncrowd.com"
REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
        page.fill('input[type="email"]', SETTINGS.commissioncrowd_username)
        page.fill('input[type="password"]', SETTINGS.commissioncrowd_password)
        page.click('button[type="submit"]')
        for _ in range(25):
            page.wait_for_timeout(1000)
            if "#/agent" in page.url:
                break
        page.wait_for_timeout(3000)

        # Navigate to Find Opportunities
        page.evaluate("window.location.hash = '#/opportunities/search'")
        page.wait_for_timeout(8000)
        print(f"url: {page.url}")
        print(f"text length: {len(page.evaluate('() => document.body.innerText'))}")

        # Try search
        try:
            inp = page.locator('input[placeholder*="search" i], input[type="search"]').first
            if inp.count() > 0:
                inp.fill("AI")
                page.keyboard.press("Enter")
                page.wait_for_timeout(5000)
                print(
                    f"after search text length: {len(page.evaluate('() => document.body.innerText'))}"
                )
        except Exception as e:
            print(f"search error: {e}")

        # Dump all cards
        cards = page.evaluate("""
        () => {
            const items = [];
            const cards = document.querySelectorAll('.opportunity-card, .opportunity-item, [class*="opportunity"], .card, [class*="result"]');
            for (const card of cards) {
                items.push({text: card.innerText.trim().slice(0,200), html: card.outerHTML.slice(0,500)});
            }
            return items;
        }
        """)
        print(f"cards found: {len(cards)}")
        for c in cards[:10]:
            print(f"  -> {c['text'][:100]}")

        page.screenshot(path=str(REPORTS_DIR / "diag_find_v2.png"), full_page=True)
        browser.close()


if __name__ == "__main__":
    sys.exit(main() or 0)

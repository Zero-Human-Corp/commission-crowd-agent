#!/usr/bin/env python3
"""Diagnostic: Dashboard conversations table structure."""

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

        # Dashboard
        page.evaluate("window.location.hash = '#/agent/dashboard'")
        page.wait_for_timeout(6000)

        tables = page.evaluate("""
        () => {
            const out = [];
            document.querySelectorAll('table').forEach((table, idx) => {
                const headers = Array.from(table.querySelectorAll('th, thead td')).map(h => h.innerText.trim());
                const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr => {
                    const tds = Array.from(tr.querySelectorAll('td')).map(td => ({
                        text: td.innerText.trim(),
                        html: td.innerHTML.slice(0,200),
                        title: td.getAttribute('title') || '',
                        aria: td.getAttribute('aria-label') || ''
                    }));
                    return {tds};
                });
                out.push({idx, headers, rows});
            });
            return out;
        }
        """)

        for t in tables:
            htext = " ".join(t["headers"]).lower()
            if "date" in htext and "from" in htext and "subject" in htext:
                print(f"\n=== CONVERSATIONS TABLE (index {t['idx']}) ===")
                print(f"headers: {t['headers']}")
                for r in t["rows"]:
                    for i, td in enumerate(r["tds"]):
                        print(
                            f"  td[{i}]: text='{td['text']}' title='{td['title']}' aria='{td['aria']}'"
                        )
                        print(f"         html={td['html'][:80]}")

        browser.close()


if __name__ == "__main__":
    sys.exit(main() or 0)

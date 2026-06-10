#!/usr/bin/env python3
"""Diagnostic v8 — dump dashboard tables and sidebar favourites verbatim."""

from __future__ import annotations
import json, sys
from datetime import UTC, datetime
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
        print(f"logged in: {page.url}")

        # Dump ALL tables with their header text
        tables = page.evaluate("""
        () => {
            const out = [];
            document.querySelectorAll('table').forEach((table, idx) => {
                const headers = Array.from(table.querySelectorAll('th, thead td')).map(h => h.innerText.trim());
                const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr =>
                    Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())
                );
                out.push({index: idx, headers, rows});
            });
            return out;
        }
        """)
        with open(REPORTS_DIR / "diag_tables.json", "w") as fh:
            json.dump(tables, fh, indent=2)
        print(f"tables dumped: {len(tables)}")
        for t in tables:
            print(f"  Table {t['index']}: headers={t['headers']}, rows={len(t['rows'])}")
            for r in t["rows"][:3]:
                print(f"    -> {r}")

        # Dump all headings and their next sibling text
        headings = page.evaluate("""
        () => {
            const out = [];
            document.querySelectorAll('h1, h2, h3, h4, h5, h6, .section-title, .panel-title').forEach(h => {
                const parent = h.closest('.panel, .card, .widget, section, div[class*="sidebar"]') || h.parentElement;
                const links = Array.from(parent.querySelectorAll('a')).map(a => ({text: a.innerText.trim(), href: a.href}));
                out.push({text: h.innerText.trim(), tag: h.tagName, links: links.slice(0, 10)});
            });
            return out;
        }
        """)
        with open(REPORTS_DIR / "diag_headings.json", "w") as fh:
            json.dump(headings, fh, indent=2)
        print(f"headings dumped: {len(headings)}")
        for h in headings:
            print(f"  {h['tag']}: {h['text']}")

        # Dump right sidebar specifically
        sidebar = page.evaluate("""
        () => {
            const sidebar = document.querySelector('.sidebar-right, [class*="sidebar"], aside') || document.body;
            const text = sidebar.innerText;
            const links = Array.from(sidebar.querySelectorAll('a[href*="/opportunities/"]')).map(a => ({text: a.innerText.trim(), href: a.href}));
            return {text_sample: text.slice(0, 3000), links};
        }
        """)
        with open(REPORTS_DIR / "diag_sidebar.json", "w") as fh:
            json.dump(sidebar, fh, indent=2)
        print(f"sidebar links: {len(sidebar['links'])}")
        for link in sidebar["links"]:
            print(f"  -> {link['text'][:60]} ({link['href']})")

        browser.close()


if __name__ == "__main__":
    sys.exit(main() or 0)

#!/usr/bin/env python3
"""Diagnostic: Fix Applications opp IDs and Conversation subjects."""

from __future__ import annotations
import json, sys, re
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from commission_crowd_agent.config import load_settings

SETTINGS = load_settings()
BASE_URL = "https://www.commissioncrowd.com"
REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")


def _infer_opp_id(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"/opportunit(?:y|ies)/(\d+)", text)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{5,})\b", text)
    if m:
        return m.group(1)
    return ""


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

        # --- Applications page deep dive ---
        page.evaluate("window.location.hash = '#/agent/applications'")
        page.wait_for_timeout(6000)

        # Extract all table rows with full cell HTML
        apps = page.evaluate("""
        () => {
            const items = [];
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const headers = Array.from(table.querySelectorAll('th, thead td')).map(h => h.innerText.trim().toLowerCase());
                const htext = headers.join(' ');
                if (htext.includes('status') && htext.includes('opportunity') && htext.includes('date')) {
                    const rows = table.querySelectorAll('tbody tr');
                    for (const row of rows) {
                        const tds = row.querySelectorAll('td');
                        if (tds.length >= 3) {
                            const status = tds[0].innerText.trim();
                            const title = tds[1].innerText.trim();
                            const date = tds[2] ? tds[2].innerText.trim() : '';
                            const link = tds[1].querySelector('a[href*="/opportunities/"]');
                            let oppId = '';
                            let href = '';
                            if (link) {
                                href = link.href;
                                const m = link.href.match(/\\/opportunities\\/(\\d+)/);
                                oppId = m ? m[1] : '';
                            }
                            // Also check for any data-id or id attribute
                            if (!oppId && row.dataset && row.dataset.id) oppId = row.dataset.id;
                            if (!oppId && row.id) oppId = row.id;
                            items.push({status, title, date, opp_id: oppId, href, html: tds[1].innerHTML.slice(0,300)});
                        }
                    }
                }
            }
            return items;
        }
        """)
        print(f"\n=== APPLICATIONS ({len(apps)}) ===")
        for a in apps:
            print(
                f"  opp_id={a['opp_id']} | status={a['status']} | date={a['date']} | title={a['title'][:60]}"
            )
            print(f"    href={a['href']}")

        # --- Conversations page deep dive ---
        page.evaluate("window.location.hash = '#/agent/conversations'")
        page.wait_for_timeout(6000)

        # Extract all table rows with full cell HTML
        convs = page.evaluate("""
        () => {
            const items = [];
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const headers = Array.from(table.querySelectorAll('th, thead td')).map(h => h.innerText.trim().toLowerCase());
                const htext = headers.join(' ');
                if (htext.includes('date') && htext.includes('from') && htext.includes('subject')) {
                    const rows = table.querySelectorAll('tbody tr');
                    for (const row of rows) {
                        const tds = row.querySelectorAll('td');
                        if (tds.length >= 3) {
                            const date = tds[0].innerText.trim();
                            const from = tds[1].innerText.trim();
                            const subject = tds[2].innerText.trim();
                            const subjectHTML = tds[2].innerHTML.slice(0,300);
                            // Also check title/aria-label/tooltip on subject cell
                            const titleAttr = tds[2].getAttribute('title') || '';
                            const ariaLabel = tds[2].getAttribute('aria-label') || '';
                            items.push({date, from, subject, subjectHTML, titleAttr, ariaLabel});
                        }
                    }
                }
            }
            return items;
        }
        """)
        print(f"\n=== CONVERSATIONS ({len(convs)}) ===")
        for c in convs:
            print(f"  from={c['from']} | date={c['date']}")
            print(
                f"    subject='{c['subject']}' | titleAttr='{c['titleAttr']}' | ariaLabel='{c['ariaLabel']}'"
            )
            print(f"    html={c['subjectHTML'][:100]}")

        # Also try clicking a conversation row to see the actual subject
        if convs:
            try:
                # Click first conversation row
                row = page.locator("table tbody tr").first
                if row.count() > 0:
                    row.click()
                    page.wait_for_timeout(3000)
                    detail_text = page.evaluate("() => document.body.innerText")
                    print(f"\n=== AFTER CLICK (first conversation) ===")
                    print(f"text length: {len(detail_text)}")
                    # Find lines that look like a subject or title
                    for line in detail_text.split("\\n")[:30]:
                        line = line.strip()
                        if line and len(line) > 10 and len(line) < 200:
                            print(f"  line: {line}")
            except Exception as e:
                print(f"click error: {e}")

        browser.close()


if __name__ == "__main__":
    sys.exit(main() or 0)

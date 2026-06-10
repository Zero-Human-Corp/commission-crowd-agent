#!/usr/bin/env python3
"""Diagnostic: save per-section screenshots and dump raw content text."""

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
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
        page.fill('input[type="email"]', SETTINGS.commissioncrowd_username)
        page.fill('input[type="password"]', SETTINGS.commissioncrowd_password)
        page.click('button[type="submit"]')
        for _ in range(20):
            page.wait_for_timeout(1000)
            if "#/agent" in page.url:
                break
        page.wait_for_timeout(3000)
        print(f"logged in: {page.url}")

        for route in [
            "dashboard",
            "my-opportunities",
            "applications",
            "favourites",
            "conversations",
        ]:
            page.evaluate(f"window.location.hash = '#/agent/{route}'")
            page.wait_for_timeout(6000)
            path = REPORTS_DIR / f"diag_{route}.png"
            page.screenshot(path=str(path), full_page=True)
            # dump all text in main content area
            text = page.evaluate("() => document.body.innerText")
            json_path = REPORTS_DIR / f"diag_{route}_text.json"
            with open(json_path, "w") as fh:
                json.dump(
                    {"url": page.url, "text_sample": text[:5000], "len": len(text)}, fh, indent=2
                )
            print(f"{route}: url={page.url} len={len(text)} img={path}")

        # Find opportunities
        page.evaluate("window.location.hash = '#/opportunities/search'")
        page.wait_for_timeout(6000)
        path = REPORTS_DIR / "diag_find.png"
        page.screenshot(path=str(path), full_page=True)
        text = page.evaluate("() => document.body.innerText")
        json_path = REPORTS_DIR / "diag_find_text.json"
        with open(json_path, "w") as fh:
            json.dump({"url": page.url, "text_sample": text[:5000], "len": len(text)}, fh, indent=2)
        print(f"find: url={page.url} len={len(text)} img={path}")

        browser.close()


if __name__ == "__main__":
    sys.exit(main() or 0)

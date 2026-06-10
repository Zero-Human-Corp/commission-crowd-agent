#!/usr/bin/env python3
"""Diagnostic script for Applications opp IDs and Conversations subjects."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Load credentials from config
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from commission_crowd_agent.config import load_settings

settings = load_settings()

BASE_URL = "https://www.commissioncrowd.com"


def classify_subject(subject: str) -> str:
    """Classify a conversation subject string."""
    subj_lower = subject.lower()
    explicit_keywords = ["invite", "invitation", "apply", "represent", "join", "connect"]
    likely_keywords = ["opportunity", "interested", "discuss"]
    if any(kw in subj_lower for kw in explicit_keywords):
        return "explicit_invitation"
    if any(kw in subj_lower for kw in likely_keywords):
        return "likely_net_new_invitation"
    return "uncertain"


def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        # Login
        page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
        page.fill('input[type="email"]', settings.commissioncrowd_username)
        page.fill('input[type="password"]', settings.commissioncrowd_password)
        page.click('button[type="submit"]')
        page.wait_for_timeout(5000)

        # Wait for dashboard
        for _ in range(20):
            url = page.url
            if "#/agent" in url:
                break
            if (
                page.locator("text=Dashboard").count() > 0
                or page.locator("text=My Opportunities").count() > 0
            ):
                break
            page.wait_for_timeout(1000)
        else:
            print("WARN: dashboard not fully detected, continuing anyway")

        # ── DIAGNOSE APPLICATIONS ──
        print("\n=== APPLICATIONS PAGE ===")
        page.goto(f"{BASE_URL}/app/#/agent/applications", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(4000)

        apps_data = []
        # Snapshot raw HTML around the table for debugging
        raw_html = page.content()
        # Save a snippet for inspection
        snippet_path = REPORTS_DIR / "applications_raw_snippet.html"
        snippet_path.write_text(raw_html, encoding="utf-8")

        # Try multiple strategies for table rows
        rows = page.locator("table tbody tr, .application-row, [class*='application']").all()
        print(f"Found {len(rows)} candidate rows")

        for i, row in enumerate(rows[:10]):
            cells = row.locator("td").all_inner_texts()
            print(f"  Row {i}: cells={cells}")

            # Try to get links inside the row
            links = row.locator("a").all()
            link_hrefs = []
            link_texts = []
            for link in links:
                href = link.get_attribute("href") or ""
                text = link.inner_text() or ""
                if href:
                    link_hrefs.append(href)
                if text.strip():
                    link_texts.append(text.strip())

            # Extract opp_id from any link containing /opportunity/
            opp_id = ""
            for href in link_hrefs:
                m = re.search(r"/opportunity[s/]*(\d+)", href)
                if m:
                    opp_id = m.group(1)
                    break
                # Also try query params like ?id=12345
                m2 = re.search(r"[?&]id=(\d+)", href)
                if m2:
                    opp_id = m2.group(1)
                    break

            # Fallback: any standalone 5-digit number in link text or cell text
            if not opp_id:
                combined_text = " ".join(link_texts + cells)
                m3 = re.search(r"\b(\d{5,})\b", combined_text)
                if m3:
                    opp_id = m3.group(1)

            title = ""
            if link_texts:
                title = link_texts[0]
            elif cells:
                title = cells[0]

            status = ""
            date_str = ""
            if len(cells) >= 2:
                # Heuristic: look for status keywords in later cells
                for c in cells[1:]:
                    c_upper = c.upper()
                    if any(
                        k in c_upper
                        for k in [
                            "AWAITING",
                            "APPROVED",
                            "REJECTED",
                            "PENDING",
                            "ACCEPTED",
                            "DECLINED",
                        ]
                    ):
                        status = c.strip()
                        break
                # Heuristic: look for date-like strings
                for c in cells[1:]:
                    if (
                        re.search(
                            r"\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
                            c,
                            re.IGNORECASE,
                        )
                        or re.search(r"\d{1,2}/\d{1,2}/\d{4}", c)
                        or re.search(r"\d{4}-\d{2}-\d{2}", c)
                    ):
                        date_str = c.strip()
                        break

            if title.strip():
                apps_data.append(
                    {
                        "opportunity_id": opp_id,
                        "title": title.strip()[:300],
                        "status": status,
                        "date": date_str,
                        "source_url": f"{BASE_URL}{link_hrefs[0]}" if link_hrefs else "",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )
                print(
                    f"    → opp_id={opp_id!r} title={title.strip()[:80]!r} status={status!r} date={date_str!r}"
                )

        # ── DIAGNOSE CONVERSATIONS ──
        print("\n=== CONVERSATIONS PAGE ===")
        page.goto(f"{BASE_URL}/app/#/agent/conversations", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(4000)

        conv_html = page.content()
        conv_snippet_path = REPORTS_DIR / "conversations_raw_snippet.html"
        conv_snippet_path.write_text(conv_html, encoding="utf-8")

        conv_data = []
        # Try multiple selectors
        rows = page.locator(
            "table tbody tr, .conversation-list-item, .message-row, [class*='conversation']"
        ).all()
        print(f"Found {len(rows)} candidate rows")

        for i, row in enumerate(rows[:10]):
            # Get all cell texts
            cells = row.locator("td").all_inner_texts()
            print(f"  Row {i}: cells={cells}")

            # Also get any title/tooltip attributes from links or spans inside the row
            inner_html = row.inner_html()
            # Try to extract subject from title attributes
            title_attrs = re.findall(r'title=["\']([^"\']+)["\']', inner_html)
            # Try aria-label
            aria_labels = re.findall(r'aria-label=["\']([^"\']+)["\']', inner_html)

            subject = ""
            sender = ""
            date_str = ""

            # Heuristic mapping depending on number of cells
            if len(cells) >= 4:
                # Typical: Date | From | Subject | Preview/Action
                date_str = cells[0].strip()
                sender = cells[1].strip()
                subject = cells[2].strip()
            elif len(cells) == 3:
                date_str = cells[0].strip()
                sender = cells[1].strip()
                subject = cells[2].strip()
            elif len(cells) == 2:
                sender = cells[0].strip()
                subject = cells[1].strip()
            elif len(cells) == 1:
                # Could be a compact card with everything in one cell
                full_text = cells[0]
                # Try to split on newlines
                parts = [p.strip() for p in full_text.split("\n") if p.strip()]
                if len(parts) >= 3:
                    date_str = parts[0]
                    sender = parts[1]
                    subject = parts[2]
                elif len(parts) == 2:
                    sender = parts[0]
                    subject = parts[1]

            # If subject still empty, look at title attributes
            if not subject and title_attrs:
                subject = title_attrs[0]
            if not subject and aria_labels:
                subject = aria_labels[0]

            # Try to extract from any link text that isn't the sender
            links = row.locator("a").all_inner_texts()
            for lt in links:
                lt = lt.strip()
                if lt and lt != sender and lt != date_str and len(lt) > 3:
                    if not subject:
                        subject = lt
                    break

            classification = classify_subject(subject)

            if sender or subject:
                conv_data.append(
                    {
                        "sender": sender,
                        "date": date_str,
                        "subject": subject,
                        "classification": classification,
                        "title_attributes": title_attrs,
                        "aria_labels": aria_labels,
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )
                print(
                    f"    → sender={sender!r} date={date_str!r} subject={subject!r} classification={classification}"
                )

        # Save JSON reports
        apps_path = REPORTS_DIR / "applications_corrected.json"
        conv_path = REPORTS_DIR / "conversations_corrected.json"
        apps_path.write_text(json.dumps(apps_data, indent=2), encoding="utf-8")
        conv_path.write_text(json.dumps(conv_data, indent=2), encoding="utf-8")

        print(f"\nSaved {apps_path} ({len(apps_data)} items)")
        print(f"Saved {conv_path} ({len(conv_data)} items)")

        browser.close()


if __name__ == "__main__":
    run()

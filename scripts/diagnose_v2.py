#!/usr/bin/env python3
"""Robust diagnostic script for Applications opp IDs and Conversations subjects."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from commission_crowd_agent.config import load_settings

settings = load_settings()
BASE_URL = "https://www.commissioncrowd.com"


def classify_subject(subject: str) -> str:
    subj_lower = subject.lower()
    explicit_keywords = ["invite", "invitation", "apply", "represent", "join", "connect"]
    likely_keywords = ["opportunity", "interested", "discuss"]
    if any(kw in subj_lower for kw in explicit_keywords):
        return "explicit_invitation"
    if any(kw in subj_lower for kw in likely_keywords):
        return "likely_net_new_invitation"
    return "uncertain"


def wait_for_spa(page, url_path, check_selectors, timeout_ms=20000):
    """Navigate to an SPA route and wait until one of the check selectors appears."""
    page.goto(f"{BASE_URL}{url_path}", wait_until="domcontentloaded", timeout=30000)
    # Wait for Ember/DataTables to render
    for _ in range(timeout_ms // 500):
        for sel in check_selectors:
            if page.locator(sel).count() > 0:
                # Ensure it's actually visible
                try:
                    if page.locator(sel).first.is_visible():
                        page.wait_for_timeout(1000)
                        return sel
                except Exception:
                    pass
        page.wait_for_timeout(500)
    return None


def extract_applications(page):
    print("\n=== APPLICATIONS ===")
    found_sel = wait_for_spa(
        page,
        "/app/#/agent/applications",
        check_selectors=[
            "table tbody tr",
            ".dataTables_wrapper tbody tr",
            "[class*='application'] tbody tr",
            ".opportunity-title",
            "a[href*='opportunity']",
        ],
        timeout_ms=25000,
    )
    print(f"Detected selector: {found_sel}")
    page.wait_for_timeout(3000)

    # Save screenshot
    shot_path = REPORTS_DIR / "applications_screenshot.png"
    page.screenshot(path=str(shot_path), full_page=True)
    print(f"Screenshot saved: {shot_path}")

    apps = []

    # Strategy 1: DataTables rows
    rows = page.locator("table tbody tr, .dataTables_wrapper tbody tr").all()
    print(f"Table rows found: {len(rows)}")

    for row in rows:
        cells = row.locator("td").all_inner_texts()
        if len(cells) < 2:
            continue
        # Heuristic: skip header-like rows
        if any(h in cells[0].upper() for h in ["STATUS", "TITLE", "DATE", "ACTION"]):
            continue

        title = ""
        opp_id = ""
        status = ""
        date_str = ""
        source_url = ""

        # Find all links in row
        links = row.locator("a").all()
        for link in links:
            href = link.get_attribute("href") or ""
            text = (link.inner_text() or "").strip()
            if not text:
                text = (link.get_attribute("title") or "").strip()
            if href and not source_url:
                source_url = f"{BASE_URL}{href}" if not href.startswith("http") else href
            # Extract opp_id from href patterns
            m = re.search(r"/opportunity[s/]*(\d+)", href)
            if m and not opp_id:
                opp_id = m.group(1)
            m2 = re.search(r"[?&]id=(\d+)", href)
            if m2 and not opp_id:
                opp_id = m2.group(1)
            if text and len(text) > 10 and not title:
                title = text

        # If still no title, use first substantial cell text
        if not title:
            for c in cells:
                c = c.strip()
                if len(c) > 15 and c not in ["Action", "trash", "close"]:
                    title = c
                    break

        # Extract status from cells
        for c in cells:
            c_upper = c.upper()
            if any(
                k in c_upper
                for k in ["AWAITING", "APPROVED", "REJECTED", "PENDING", "ACCEPTED", "DECLINED"]
            ):
                status = c.strip()
                break

        # Extract date from cells
        for c in cells:
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

        # Final fallback opp_id extraction from title text
        if not opp_id and title:
            m3 = re.search(r"\b(\d{5,})\b", title)
            if m3:
                opp_id = m3.group(1)

        if title.strip():
            apps.append(
                {
                    "opportunity_id": opp_id,
                    "title": title.strip()[:300],
                    "status": status,
                    "date": date_str,
                    "source_url": source_url,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            )
            print(
                f"  APP opp_id={opp_id!r} title={title.strip()[:80]!r} status={status!r} date={date_str!r}"
            )

    # Strategy 2: if no table rows, scan all links with opportunity in href
    if not apps:
        links = page.locator('a[href*="/opportunity/"]').all()
        print(f"Fallback links found: {len(links)}")
        for link in links:
            href = link.get_attribute("href") or ""
            text = (link.inner_text() or "").strip()
            if not text:
                text = (link.get_attribute("title") or "").strip()
            m = re.search(r"/opportunity[s/]*(\d+)", href)
            opp_id = m.group(1) if m else ""
            if text:
                apps.append(
                    {
                        "opportunity_id": opp_id,
                        "title": text[:300],
                        "status": "",
                        "date": "",
                        "source_url": f"{BASE_URL}{href}" if not href.startswith("http") else href,
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )

    return apps


def extract_conversations(page):
    print("\n=== CONVERSATIONS ===")
    found_sel = wait_for_spa(
        page,
        "/app/#/agent/conversations",
        check_selectors=[
            "table tbody tr",
            ".conversation-list-item",
            ".message-row",
            "[class*='conversation']",
            "[class*='message']",
        ],
        timeout_ms=25000,
    )
    print(f"Detected selector: {found_sel}")
    page.wait_for_timeout(3000)

    shot_path = REPORTS_DIR / "conversations_screenshot.png"
    page.screenshot(path=str(shot_path), full_page=True)
    print(f"Screenshot saved: {shot_path}")

    convs = []

    # Try multiple row selectors
    selectors = [
        "table tbody tr",
        ".conversation-list-item",
        ".message-row",
        "[class*='conversation-item']",
        "[class*='message-item']",
        "[class*='inbox-row']",
    ]
    all_rows = []
    for sel in selectors:
        rows = page.locator(sel).all()
        if rows:
            print(f"Selector '{sel}' matched {len(rows)} rows")
            all_rows.extend(rows)

    # Deduplicate by inner_html hash
    seen_html = set()
    rows = []
    for r in all_rows:
        try:
            h = r.inner_html()
        except Exception:
            continue
        if h not in seen_html:
            seen_html.add(h)
            rows.append(r)

    print(f"Unique rows to process: {len(rows)}")

    for i, row in enumerate(rows[:20]):
        cells = row.locator("td").all_inner_texts()
        inner_html = row.inner_html()
        inner_text = row.inner_text()
        print(f"\n  Row {i}:")
        print(f"    cells={cells}")
        print(f"    inner_text preview={inner_text[:200]!r}")

        sender = ""
        date_str = ""
        subject = ""

        # Try to extract from structured cells first
        if len(cells) >= 4:
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
            parts = [p.strip() for p in cells[0].split("\n") if p.strip()]
            if len(parts) >= 3:
                date_str = parts[0]
                sender = parts[1]
                subject = parts[2]
            elif len(parts) == 2:
                sender = parts[0]
                subject = parts[1]

        # Try title/aria attributes
        if not subject:
            title_attrs = re.findall(r'title=["\']([^"\']+)["\']', inner_html)
            if title_attrs:
                subject = title_attrs[0]
                print(f"    -> subject from title attr: {subject!r}")
        if not subject:
            aria_labels = re.findall(r'aria-label=["\']([^"\']+)["\']', inner_html)
            if aria_labels:
                subject = aria_labels[0]
                print(f"    -> subject from aria-label: {subject!r}")

        # Try link texts
        if not subject:
            link_texts = row.locator("a").all_inner_texts()
            for lt in link_texts:
                lt = lt.strip()
                if (
                    lt
                    and lt != sender
                    and lt != date_str
                    and len(lt) > 3
                    and lt.lower() not in ["action", "trash", "close"]
                ):
                    subject = lt
                    print(f"    -> subject from link text: {subject!r}")
                    break

        # Try span/div texts that look like a subject (heuristic: contains relevant keywords)
        if not subject:
            all_texts = row.locator("span, div").all_inner_texts()
            for t in all_texts:
                t = t.strip()
                if any(
                    k in t.lower()
                    for k in [
                        "opportunity",
                        "commission",
                        "supply chain",
                        "interested",
                        "discuss",
                        "invite",
                        "invitation",
                        "apply",
                        "represent",
                        "join",
                        "connect",
                    ]
                ):
                    if t != sender and t != date_str and len(t) > 5:
                        subject = t
                        print(f"    -> subject from span/div heuristic: {subject!r}")
                        break

        # Last resort: any non-date, non-sender text in inner_text lines
        if not subject:
            lines = [l.strip() for l in inner_text.split("\n") if l.strip()]
            for l in lines:
                if l == sender or l == date_str or l in ["Action", "trash", "close"]:
                    continue
                if len(l) > 5:
                    subject = l
                    print(f"    -> subject from inner_text line: {subject!r}")
                    break

        classification = classify_subject(subject)

        if sender or subject:
            convs.append(
                {
                    "sender": sender,
                    "date": date_str,
                    "subject": subject,
                    "classification": classification,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            )
            print(
                f"    → FINAL sender={sender!r} date={date_str!r} subject={subject!r} class={classification}"
            )

    return convs


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
        # Wait for dashboard hash
        for _ in range(25):
            if "#/agent" in page.url:
                break
            if (
                page.locator("text=Dashboard").count() > 0
                or page.locator("text=My Opportunities").count() > 0
            ):
                break
            page.wait_for_timeout(1000)
        else:
            print("WARN: dashboard not fully detected, continuing anyway")

        # Give extra time for SPA to fully bootstrap
        page.wait_for_timeout(4000)

        apps = extract_applications(page)
        convs = extract_conversations(page)

        # Save JSON
        apps_path = REPORTS_DIR / "applications_corrected.json"
        conv_path = REPORTS_DIR / "conversations_corrected.json"
        apps_path.write_text(json.dumps(apps, indent=2), encoding="utf-8")
        conv_path.write_text(json.dumps(convs, indent=2), encoding="utf-8")

        print(f"\nSaved {apps_path} ({len(apps)} items)")
        print(f"Saved {conv_path} ({len(convs)} items)")

        browser.close()


if __name__ == "__main__":
    run()

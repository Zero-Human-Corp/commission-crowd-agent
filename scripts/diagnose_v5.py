#!/usr/bin/env python3
"""v5 diagnostic: Click into application links and conversation threads to get full data."""

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


def login(page):
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill('input[type="email"]', settings.commissioncrowd_username)
    page.fill('input[type="password"]', settings.commissioncrowd_password)
    page.click('button[type="submit"]')
    for _ in range(25):
        if "#/agent" in page.url:
            break
        if (
            page.locator("text=Dashboard").count() > 0
            or page.locator("text=My Opportunities").count() > 0
        ):
            break
        page.wait_for_timeout(1000)
    page.wait_for_timeout(3000)
    print(f"Logged in. URL: {page.url}")


def switch_route(page, hash_route: str, expected_texts: list[str], max_wait_ms: int = 15000):
    page.evaluate(f"window.location.hash = '{hash_route}'")
    waited = 0
    while waited < max_wait_ms:
        page.wait_for_timeout(500)
        waited += 500
        body_text = (page.locator("body").inner_text() or "").lower()
        if any(t.lower() in body_text for t in expected_texts):
            print(f"Route {hash_route} loaded after {waited}ms")
            page.wait_for_timeout(1500)
            return True
    body_text = (page.locator("body").inner_text() or "").lower()
    print(f"WARNING: Route {hash_route} text not detected. Snippet: {body_text[:200]}")
    page.wait_for_timeout(2000)
    return False


def extract_applications(page):
    print("\n=== APPLICATIONS ===")
    switch_route(page, "#/agent/applications", ["applications", "awaiting approval", "commission"])
    page.wait_for_timeout(3000)

    shot_path = REPORTS_DIR / "applications_v5.png"
    page.screenshot(path=str(shot_path), full_page=True)

    apps = []
    rows = page.locator("table tbody tr").all()
    print(f"Table rows: {len(rows)}")

    for row in rows:
        cells = row.locator("td").all_inner_texts()
        if len(cells) < 2:
            continue
        if any(h in cells[0].upper() for h in ["STATUS", "TITLE", "DATE", "ACTION"]):
            continue

        title = ""
        opp_id = ""
        status = ""
        date_str = ""
        source_url = ""

        links = row.locator("a").all()
        for link in links:
            href = link.get_attribute("href") or ""
            text = (link.inner_text() or "").strip()
            if not text:
                text = (link.get_attribute("title") or "").strip()
            if href and not source_url:
                source_url = href if href.startswith("http") else f"{BASE_URL}{href}"
            m = re.search(r"/opportunity[s/]*(\d+)", href)
            if m and not opp_id:
                opp_id = m.group(1)
            m2 = re.search(r"[?&]id=(\d+)", href)
            if m2 and not opp_id:
                opp_id = m2.group(1)
            if text and len(text) > 10 and not title:
                title = text

        if not title:
            for c in cells:
                c = c.strip()
                if len(c) > 15 and c not in ["Action", "trash", "close"]:
                    title = c
                    break

        for c in cells:
            c_upper = c.upper()
            if any(
                k in c_upper
                for k in ["AWAITING", "APPROVED", "REJECTED", "PENDING", "ACCEPTED", "DECLINED"]
            ):
                status = c.strip()
                break

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

        if not opp_id and title:
            m3 = re.search(r"\b(\d{5,})\b", title)
            if m3:
                opp_id = m3.group(1)

        # If still no opp_id, try clicking the row title link and capture URL
        if not opp_id and title:
            for link in links:
                href = link.get_attribute("href") or ""
                text = (link.inner_text() or "").strip()
                if text and len(text) > 10 and title in text:
                    try:
                        print(f"  Clicking link to get opp_id: {text[:60]!r}")
                        with page.expect_navigation(wait_until="domcontentloaded", timeout=10000):
                            link.click()
                        page.wait_for_timeout(3000)
                        current_url = page.url
                        print(f"  Navigated to: {current_url}")
                        m = re.search(r"/opportunity[s/]*(\d+)", current_url)
                        if m:
                            opp_id = m.group(1)
                            print(f"  Extracted opp_id from URL: {opp_id}")
                        # Go back
                        page.evaluate("window.location.hash = '#/agent/applications'")
                        page.wait_for_timeout(3000)
                        break
                    except Exception as e:
                        print(f"  Click/navigate failed: {e}")
                        # Try going back anyway
                        try:
                            page.evaluate("window.location.hash = '#/agent/applications'")
                            page.wait_for_timeout(3000)
                        except Exception:
                            pass

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

    return apps


def extract_conversations(page):
    print("\n=== CONVERSATIONS ===")
    page.evaluate("window.location.hash = '#/agent/dashboard'")
    page.wait_for_timeout(2000)
    switch_route(
        page,
        "#/agent/conversations",
        ["conversations", "messages", "vanessa", "jaret", "sender", "subject"],
    )
    page.wait_for_timeout(3000)

    shot_path = REPORTS_DIR / "conversations_v5.png"
    page.screenshot(path=str(shot_path), full_page=True)
    print(f"Screenshot: {shot_path}")

    # Get all table rows and filter to conversation-like ones (have a date with 'at' and a sender arrow)
    all_rows = page.locator("table tbody tr").all()
    print(f"Total table rows: {len(all_rows)}")

    convs = []
    candidate_rows = []
    for row in all_rows:
        cells = row.locator("td").all_inner_texts()
        inner_text = row.inner_text()
        # Conversation rows typically have a date like "5 June 2026 at 18:17" and sender arrow "→"
        if (
            re.search(
                r"\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\s+at\s+\d{1,2}:\d{2}",
                inner_text,
                re.IGNORECASE,
            )
            and "→" in inner_text
        ):
            candidate_rows.append(row)
            print(f"  Candidate row: cells={cells}")

    print(f"Conversation candidate rows: {len(candidate_rows)}")

    for i, row in enumerate(candidate_rows):
        cells = row.locator("td").all_inner_texts()
        inner_text = row.inner_text()
        print(f"\n  Processing conversation {i}: cells={cells}")

        sender = ""
        date_str = ""
        subject = ""

        if len(cells) >= 3:
            date_str = cells[0].strip()
            sender = cells[1].strip()
            subject = cells[2].strip()
        elif len(cells) == 2:
            date_str = cells[0].strip()
            sender = cells[1].strip()
        elif len(cells) == 1:
            parts = [p.strip() for p in cells[0].split("\n") if p.strip()]
            if len(parts) >= 3:
                date_str = parts[0]
                sender = parts[1]
                subject = parts[2]
            elif len(parts) == 2:
                date_str = parts[0]
                sender = parts[1]

        # If subject is truncated "...", try clicking the row to get full subject from conversation detail
        if not subject or subject.endswith("..."):
            links = row.locator("a").all()
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.inner_text() or "").strip()
                    # Only click if it looks like a conversation link (not action icon)
                    if text and len(text) > 5 and text != "trash" and text != "close":
                        print(f"  Clicking conversation link: {text[:60]!r}")
                        with page.expect_navigation(wait_until="domcontentloaded", timeout=10000):
                            link.click()
                        page.wait_for_timeout(3000)

                        # Try to read the full conversation subject from the page
                        page_text = page.locator("body").inner_text() or ""
                        # Look for a subject line near the top
                        lines = [l.strip() for l in page_text.split("\n") if l.strip()]
                        # Heuristic: the conversation subject is often a line that is long-ish and contains opportunity keywords
                        for line in lines[:30]:
                            if len(line) > 20 and any(
                                k in line.lower()
                                for k in [
                                    "commission",
                                    "deal",
                                    "residual",
                                    "opportunity",
                                    "supply chain",
                                    "€",
                                    "$",
                                    "%",
                                ]
                            ):
                                if line != sender and line != date_str:
                                    subject = line
                                    print(f"  Full subject from detail: {subject!r}")
                                    break

                        # Also try to get it from any h1/h2 or title
                        if not subject or subject.endswith("..."):
                            for tag in [
                                "h1",
                                "h2",
                                "h3",
                                ".subject",
                                ".conversation-subject",
                                "[class*='subject']",
                            ]:
                                try:
                                    el_text = page.locator(tag).first.inner_text()
                                    if el_text and len(el_text) > 10:
                                        subject = el_text.strip()
                                        print(f"  Full subject from {tag}: {subject!r}")
                                        break
                                except Exception:
                                    pass
                            if not subject or subject.endswith("..."):
                                page_title = page.title()
                                if page_title and page_title != "CommissionCrowd App":
                                    subject = page_title.strip()
                                    print(f"  Full subject from page title: {subject!r}")

                        # Go back
                        page.evaluate("window.location.hash = '#/agent/conversations'")
                        page.wait_for_timeout(3000)
                        break
                except Exception as e:
                    print(f"  Click/navigate failed: {e}")
                    try:
                        page.evaluate("window.location.hash = '#/agent/conversations'")
                        page.wait_for_timeout(3000)
                    except Exception:
                        pass

        # If still truncated, try to expand by hovering
        if subject.endswith("..."):
            try:
                row.hover()
                page.wait_for_timeout(1000)
                new_text = row.inner_text()
                # See if hover revealed tooltip or expanded text
                # Not much we can do; just keep the truncated one
            except Exception:
                pass

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
        login(page)

        apps = extract_applications(page)
        convs = extract_conversations(page)

        apps_path = REPORTS_DIR / "applications_corrected.json"
        conv_path = REPORTS_DIR / "conversations_corrected.json"
        apps_path.write_text(json.dumps(apps, indent=2), encoding="utf-8")
        conv_path.write_text(json.dumps(convs, indent=2), encoding="utf-8")

        print(f"\nSaved {apps_path} ({len(apps)} items)")
        print(f"Saved {conv_path} ({len(convs)} items)")

        browser.close()


if __name__ == "__main__":
    run()

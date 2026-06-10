#!/usr/bin/env python3
"""v4 diagnostic: Proper SPA hash navigation with wait and verification."""

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
    """Change hash route and wait until one of expected_texts appears."""
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
    print(f"WARNING: Route {hash_route} text not detected. Body snippet: {body_text[:200]}")
    page.wait_for_timeout(2000)
    return False


def extract_applications(page):
    print("\n=== APPLICATIONS ===")
    switch_route(page, "#/agent/applications", ["applications", "awaiting approval", "commission"])
    page.wait_for_timeout(3000)

    shot_path = REPORTS_DIR / "applications_v4.png"
    page.screenshot(path=str(shot_path), full_page=True)
    print(f"Screenshot: {shot_path}")

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
    # Reset to base before switching hash
    page.evaluate("window.location.hash = '#/agent/dashboard'")
    page.wait_for_timeout(2000)
    switch_route(
        page,
        "#/agent/conversations",
        ["conversations", "messages", "vanessa", "jaret", "sender", "subject"],
    )
    page.wait_for_timeout(3000)

    shot_path = REPORTS_DIR / "conversations_v4.png"
    page.screenshot(path=str(shot_path), full_page=True)
    print(f"Screenshot: {shot_path}")

    # Debug: dump full body text
    body_text = page.locator("body").inner_text() or ""
    print(f"Body text preview (first 800 chars):\n{body_text[:800]}")

    convs = []
    selectors = [
        "table tbody tr",
        ".conversation-list-item",
        ".message-row",
        "[class*='conversation'] tbody tr",
        "[class*='message'] tbody tr",
        ".dataTables_wrapper tbody tr",
    ]
    all_rows = []
    for sel in selectors:
        rows = page.locator(sel).all()
        if rows:
            print(f"Selector '{sel}' matched {len(rows)} rows")
            all_rows.extend(rows)

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

    print(f"Unique rows: {len(rows)}")

    for i, row in enumerate(rows[:20]):
        cells = row.locator("td").all_inner_texts()
        inner_html = row.inner_html()
        inner_text = row.inner_text()
        print(f"\n  Row {i}: cells={cells}")
        print(f"    inner_text={inner_text[:200]!r}")

        sender = ""
        date_str = ""
        subject = ""

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

        if not subject:
            title_attrs = re.findall(r'title=["\']([^"\']+)["\']', inner_html)
            if title_attrs:
                subject = title_attrs[0]
                print(f"    subject from title: {subject!r}")
        if not subject:
            aria_labels = re.findall(r'aria-label=["\']([^"\']+)["\']', inner_html)
            if aria_labels:
                subject = aria_labels[0]
                print(f"    subject from aria-label: {subject!r}")

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
                    print(f"    subject from link: {subject!r}")
                    break

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
                        print(f"    subject from span/div heuristic: {subject!r}")
                        break

        if not subject:
            lines = [l.strip() for l in inner_text.split("\n") if l.strip()]
            for l in lines:
                if l == sender or l == date_str or l in ["Action", "trash", "close"]:
                    continue
                if len(l) > 5:
                    subject = l
                    print(f"    subject from inner_text line: {subject!r}")
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

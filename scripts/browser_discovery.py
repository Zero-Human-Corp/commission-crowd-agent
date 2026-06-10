#!/usr/bin/env python3
"""CommissionCrowd browser discovery — robust v3.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from commission_crowd_agent.config import load_settings

SETTINGS = load_settings()
BASE_URL = "https://www.commissioncrowd.com"
REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _infer_opp_id(href_or_text: str) -> str:
    if not href_or_text:
        return ""
    m = re.search(r"/opportunit(?:y|ies)/(\d+)", href_or_text)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{5,})\b", href_or_text)
    if m:
        return m.group(1)
    return ""


def _map_status(status_text: str) -> str:
    s = status_text.strip().lower()
    if s == "active":
        return "active"
    if s == "inactive":
        return "paused"
    if s == "awaiting approval":
        return "application_submitted"
    if s in {"rejected", "declined"}:
        return "application_rejected"
    if s in {"accepted", "approved"}:
        return "principal_accepted"
    return "unknown"


def _esc_js(text: str) -> str:
    """Escape single quotes for embedding in JS string literals."""
    return text.replace("'", "\\'")


def _login(page) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill('input[type="email"]', SETTINGS.commissioncrowd_username)
    page.fill('input[type="password"]', SETTINGS.commissioncrowd_password)
    page.click('button[type="submit"]')
    page.wait_for_timeout(7000)


def _extract_first_matching_table(page, header_keywords: set[str]) -> list[list[str]]:
    """Find the first table whose headers contain ALL keywords, return data rows."""
    tables = page.locator("table").all()
    for table in tables:
        header_cells = table.locator("thead th, tbody tr:first-child td, tbody tr:first-child th").all_inner_texts()
        header_text = " ".join(header_cells).lower()
        if all(kw.lower() in header_text for kw in header_keywords):
            all_rows = table.locator("tr").all()
            data: list[list[str]] = []
            for i, row in enumerate(all_rows):
                cells = row.locator("td, th").all_inner_texts()
                if not cells or not any(c.strip() for c in cells):
                    continue
                joined = " ".join(cells).lower()
                if "opportunity name" in joined or ("status" in joined and "opportunity" in joined):
                    continue
                if "date" in joined and "from" in joined and "subject" in joined:
                    continue
                data.append(cells)
            return data
    return []


def _extract_id_from_table(page, table_kw: str, cell_index: int, title_prefix: str) -> str:
    """Use JS to find opportunity ID in matching table by title prefix."""
    esc = _esc_js(title_prefix)
    js = f"""
    () => {{
        const tables = document.querySelectorAll('table');
        for (const table of tables) {{
            const ths = table.querySelectorAll('th, thead th');
            const htext = Array.from(ths).map(h=>h.innerText).join(' ').toLowerCase();
            if (htext.includes('{table_kw.lower()}')) {{
                const rows = table.querySelectorAll('tr');
                for (const row of rows) {{
                    const tds = row.querySelectorAll('td');
                    if (tds.length > {cell_index} && tds[{cell_index}].innerText.trim().startsWith('{esc}')) {{
                        const link = row.querySelector('a[href*="/opportunities/"]');
                        if (link) {{
                            const m = link.href.match(/\\/opportunities\\/(\\d+)/);
                            return m ? m[1] : '';
                        }}
                    }}
                }}
            }}
        }}
        return '';
    }}
    """
    try:
        result = page.evaluate(js)
        return result if isinstance(result, str) else ""
    except Exception:
        return ""


def _extract_my_opportunities(page) -> list[dict[str, Any]]:
    page.goto(f"{BASE_URL}/app/#/agent/my-opportunities", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    rows = _extract_first_matching_table(page, {"opportunity", "completeness", "status"})
    items: list[dict[str, Any]] = []
    for cells in rows:
        if len(cells) < 2:
            continue
        title = cells[0].strip()
        if not title or len(title) < 10 or "awaiting approval" in title.lower():
            continue
        opp_id = _extract_id_from_table(page, "opportunity", 0, title[:20])
        items.append({
            "opportunity_id": opp_id,
            "title": title[:200],
            "completeness": cells[1] if len(cells) > 1 else "",
            "status": cells[2] if len(cells) > 2 else "",
            "lifecycle_state": _map_status(cells[2] if len(cells) > 2 else ""),
            "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
            "route": "my_opportunities",
            "retrieved_at": datetime.now(UTC).isoformat(),
        })
    return items


def _extract_applications(page) -> list[dict[str, Any]]:
    page.goto(f"{BASE_URL}/app/#/agent/applications", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    rows = _extract_first_matching_table(page, {"status", "opportunity", "date"})
    items: list[dict[str, Any]] = []
    for cells in rows:
        if len(cells) < 2:
            continue
        status = cells[0].strip()
        title = cells[1].strip()
        date_str = cells[2] if len(cells) > 2 else ""
        if not title or len(title) < 10:
            continue
        opp_id = _extract_id_from_table(page, "opportunity", 1, title[:20])
        items.append({
            "opportunity_id": opp_id,
            "title": title[:200],
            "status": status,
            "application_date": date_str,
            "lifecycle_state": _map_status(status),
            "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
            "route": "applications",
            "retrieved_at": datetime.now(UTC).isoformat(),
        })
    return items


def _extract_messages(page) -> list[dict[str, Any]]:
    page.goto(f"{BASE_URL}/app/#/agent/conversations", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    text = page.locator("body").inner_text()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    messages: list[dict[str, Any]] = []
    seen = set()
    for i, line in enumerate(lines):
        if re.match(r"^([A-Z][a-z]{2,8}\s+\d{1,2}|\d{1,2}\s+[A-Z][a-z]{2,8})", line):
            if i + 2 < len(lines):
                sender = lines[i + 1].strip()
                subject = lines[i + 2].strip()
                if "→" in sender or " to " in sender.lower():
                    bad_subjects = {"Reply", "Custom reply", "Block", "Report", "Choose a quick", "Add to favourites", "Quick reply"}
                    if any(skip in subject for skip in bad_subjects):
                        continue
                    msg_id = f"msg-{abs(hash(line + sender)) % 100000}"
                    if msg_id in seen:
                        continue
                    seen.add(msg_id)
                    opp_id = _infer_opp_id(subject + " " + sender)
                    messages.append({
                        "message_id": msg_id,
                        "timestamp": line,
                        "sender": sender[:80],
                        "subject": subject[:200],
                        "linked_opportunity_id": opp_id,
                        "route": "conversations",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    })
    return messages


def _extract_favourites_dashboard(page) -> list[dict[str, Any]]:
    page.goto(f"{BASE_URL}/app", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    text = page.locator("body").inner_text()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    fav_items: list[dict[str, Any]] = []
    in_fav = False
    for line in lines:
        if "favourite opportunities" in line.lower():
            in_fav = True
            continue
        if in_fav:
            if any(kw in line.lower() for kw in [
                "setup steps", "complete your profile",
                "spread the word", "total referrals",
                "unread conversations", "applications",
            ]):
                break
            if line in {"chat", "trash", "View all"}:
                continue
            if len(line) > 20:
                opp_id = _infer_opp_id(line)
                if any(c in line for c in {"%", "$", "£", "Commission", "Earn", "Residual"}):
                    fav_items.append({
                        "opportunity_id": opp_id,
                        "title": line[:200],
                        "route": "favourite_opportunities",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    })
    return fav_items


def _extract_find_opportunities_dashboard(page) -> list[dict[str, Any]]:
    text = page.locator("body").inner_text()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    find_items: list[dict[str, Any]] = []
    in_find = False
    skip_set = {"chat", "trash", "View all", "userIndependent sales agent"}
    for line in lines:
        if "featured" in line.lower() and "matching" in line.lower():
            in_find = True
            continue
        if in_find:
            if any(kw in line.lower() for kw in [
                "favourite opportunities", "unread conversations",
                "setup steps", "my opportunities", "applications",
            ]):
                break
            if line in skip_set or line.lower().startswith("check"):
                continue
            if len(line) > 20:
                opp_id = _infer_opp_id(line)
                if any(c in line for c in {"%", "$", "£", "Commission", "Earn", "Residual"}):
                    find_items.append({
                        "opportunity_id": opp_id,
                        "title": line[:200],
                        "route": "find_opportunities",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    })
    return find_items


def main() -> int:
    inventory: dict[str, Any] = {
        "my_opportunities": [],
        "applications": [],
        "messages": [],
        "invitations": [],
        "favourites": [],
        "find_opportunities": [],
        "retrieved_at": datetime.now(UTC).isoformat(),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        _login(page)
        print("Login successful")

        inventory["my_opportunities"] = _extract_my_opportunities(page)
        print(f"My Opportunities: {len(inventory['my_opportunities'])}")
        for o in inventory["my_opportunities"]:
            print(f"  -> {o['opportunity_id']}: {o['title'][:50]} status={o['status']}")

        inventory["applications"] = _extract_applications(page)
        print(f"Applications: {len(inventory['applications'])}")
        for a in inventory["applications"]:
            print(f"  -> {a['opportunity_id']}: {a['title'][:50]} status={a['status']}")

        inventory["messages"] = _extract_messages(page)
        print(f"Messages: {len(inventory['messages'])}")
        for m in inventory["messages"][:5]:
            print(f"  -> {m['sender'][:30]}: {m['subject'][:50]}")

        invite_keywords = ["invite", "invitation", "apply", "represent", "join", "connect", "review your application"]
        for msg in inventory["messages"]:
            combined = (msg.get("subject", "") + " " + msg.get("sender", "")).lower()
            if any(kw in combined for kw in invite_keywords):
                msg["classification"] = "explicit_invitation"
            else:
                msg["classification"] = "uncertain"
            msg["invitation_confidence"] = msg["classification"]
        inventory["invitations"] = [m for m in inventory["messages"] if m.get("classification") == "explicit_invitation"]
        print(f"Invitations: {len(inventory['invitations'])}")

        inventory["favourites"] = _extract_favourites_dashboard(page)
        print(f"Favourites: {len(inventory['favourites'])}")
        for f in inventory["favourites"][:5]:
            print(f"  -> {f['opportunity_id']}: {f['title'][:60]}")

        inventory["find_opportunities"] = _extract_find_opportunities_dashboard(page)
        print(f"Find Opportunities: {len(inventory['find_opportunities'])}")
        for f in inventory["find_opportunities"][:5]:
            print(f"  -> {f['opportunity_id']}: {f['title'][:60]}")

        browser.close()

    out_path = REPORTS_DIR / "cca_browser_inventory.json"
    with open(out_path, "w") as fh:
        json.dump(inventory, fh, indent=2)
    print(f"\nSaved: {out_path}")

    summary = {
        "retrieved_at": inventory["retrieved_at"],
        "my_opportunities_count": len(inventory["my_opportunities"]),
        "applications_count": len(inventory["applications"]),
        "messages_count": len(inventory["messages"]),
        "invitations_count": len(inventory["invitations"]),
        "favourites_count": len(inventory["favourites"]),
        "find_opportunities_count": len(inventory["find_opportunities"]),
        "my_opportunities_titles": [o["title"][:80] for o in inventory["my_opportunities"]],
        "applications_titles": [a["title"][:80] for a in inventory["applications"]],
        "favourites_titles": [f["title"][:80] for f in inventory["favourites"][:10]],
        "find_titles": [f["title"][:80] for f in inventory["find_opportunities"][:10]],
    }
    summary_path = REPORTS_DIR / "cca_browser_inventory_summary.json"
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"Saved summary: {summary_path}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

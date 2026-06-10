#!/usr/bin/env python3
"""CommissionCrowd deep browser discovery — v4.1 SPA-aware navigation.

Navigates within the SPA by clicking sidebar/topbar links rather than full
page reloads, preserving auth state.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

import sys

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
    return text.replace("'", "\\'")


def _login(page) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill('input[type="email"]', SETTINGS.commissioncrowd_username)
    page.fill('input[type="password"]', SETTINGS.commissioncrowd_password)
    page.click('button[type="submit"]')
    page.wait_for_timeout(10000)
    # Ensure we're on dashboard
    if "dashboard" not in page.url:
        page.goto(f"{BASE_URL}/app/#/agent/dashboard", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)


def _spa_navigate(page, link_text_contains: str) -> None:
    """Click a sidebar/topbar link containing the given text, wait for SPA render."""
    # Try exact text match first
    selectors = [
        f'a:has-text("{link_text_contains}")',
        f"text={link_text_contains}",
        f'[title*="{link_text_contains}"]',
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        if loc.count() > 0:
            try:
                loc.click()
                page.wait_for_timeout(5000)
                return
            except Exception:
                continue
    # Fallback: change window.location.hash via JS
    hash_map = {
        "my opportunities": "#/agent/my-opportunities",
        "applications": "#/agent/applications",
        "favourite": "#/agent/favourites",
        "favorites": "#/agent/favourites",
        "conversations": "#/agent/conversations",
        "messages": "#/agent/conversations",
        "find opportunities": "#/opportunities/search",
    }
    lower = link_text_contains.lower()
    for k, v in hash_map.items():
        if k in lower:
            page.evaluate(f"window.location.hash = '{v}'")
            page.wait_for_timeout(5000)
            return
    raise RuntimeError(f"Could not navigate to '{link_text_contains}' via SPA")


def _extract_first_matching_table(page, header_keywords: set[str]) -> list[list[str]]:
    tables = page.locator("table").all()
    for table in tables:
        header_cells = table.locator(
            "thead th, tbody tr:first-child td, tbody tr:first-child th"
        ).all_inner_texts()
        header_text = " ".join(header_cells).lower()
        if all(kw.lower() in header_text for kw in header_keywords):
            all_rows = table.locator("tr").all()
            data: list[list[str]] = []
            for row in all_rows:
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
    _spa_navigate(page, "My Opportunities")
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
        items.append(
            {
                "opportunity_id": opp_id,
                "title": title[:200],
                "completeness": cells[1] if len(cells) > 1 else "",
                "status": cells[2] if len(cells) > 2 else "",
                "lifecycle_state": _map_status(cells[2] if len(cells) > 2 else ""),
                "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
                "route": "my_opportunities",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )
    return items


def _extract_applications(page) -> list[dict[str, Any]]:
    _spa_navigate(page, "Applications")
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
        items.append(
            {
                "opportunity_id": opp_id,
                "title": title[:200],
                "status": status,
                "application_date": date_str,
                "lifecycle_state": _map_status(status),
                "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
                "route": "applications",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )
    return items


def _extract_favourites(page) -> list[dict[str, Any]]:
    """Navigate via filled star icon or sidebar and extract."""
    # Try clicking the star icon in the top bar first (visual nav recovery)
    try:
        star = page.locator(
            '[class*="star"], svg[class*="star"], button:has(.fa-star), [title*="Favourite"]'
        ).first
        if star.count() > 0:
            star.click()
            page.wait_for_timeout(5000)
    except Exception:
        pass
    # Fallback to sidebar
    try:
        _spa_navigate(page, "Favourite")
    except Exception:
        pass
    page.wait_for_timeout(4000)

    items: list[dict[str, Any]] = []
    rows = _extract_first_matching_table(page, {"opportunity", "completeness", "status"})
    for cells in rows:
        if len(cells) < 2:
            continue
        title = cells[0].strip()
        if not title or len(title) < 10:
            continue
        opp_id = _extract_id_from_table(page, "opportunity", 0, title[:20])
        items.append(
            {
                "opportunity_id": opp_id,
                "title": title[:200],
                "completeness": cells[1] if len(cells) > 1 else "",
                "status": cells[2] if len(cells) > 2 else "",
                "lifecycle_state": _map_status(cells[2] if len(cells) > 2 else ""),
                "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
                "route": "favourite_opportunities",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )

    if not items:
        # Body-text fallback
        text = page.locator("body").inner_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        skip = {
            "chat",
            "trash",
            "View all",
            "userIndependent sales agent",
            "Complete your profile",
            "Setup steps",
            "Spread the word",
            "Total referrals",
            "Unread conversations",
            "Applications",
        }
        for line in lines:
            if line in skip or line.lower().startswith("check"):
                continue
            if len(line) > 20 and any(
                c in line for c in {"%", "$", "£", "Commission", "Earn", "Residual"}
            ):
                opp_id = _infer_opp_id(line)
                items.append(
                    {
                        "opportunity_id": opp_id,
                        "title": line[:200],
                        "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
                        "route": "favourite_opportunities",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )
    return items


def _extract_conversations(page) -> dict[str, Any]:
    """Click speech-bubble icon or navigate via sidebar, extract messages."""
    # Try speech-bubble icon click first
    try:
        bubble = page.locator(
            '[class*="message"], svg[class*="message"], [title*="Message"], [title*="Conversation"]'
        ).first
        if bubble.count() > 0:
            bubble.click()
            page.wait_for_timeout(5000)
    except Exception:
        pass
    # Fallback sidebar
    try:
        _spa_navigate(page, "Conversations")
    except Exception:
        pass
    page.wait_for_timeout(4000)

    # Badge count from top bar before navigating away
    badge_count = None
    try:
        # Look for elements with single digit near top
        top_html = page.content()
        # Search for badge pattern in the HTML
        m = re.search(r'class="[^"]*badge[^"]*"[^>]*\u003e\s*(\d+)\s*\u003c', top_html)
        if m:
            badge_count = int(m.group(1))
    except Exception:
        pass

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
                    bad = {
                        "Reply",
                        "Custom reply",
                        "Block",
                        "Report",
                        "Choose a quick",
                        "Add to favourites",
                        "Quick reply",
                    }
                    if any(skip in subject for skip in bad):
                        continue
                    msg_id = f"msg-{abs(hash(line + sender)) % 100000}"
                    if msg_id in seen:
                        continue
                    seen.add(msg_id)
                    opp_id = _infer_opp_id(subject + " " + sender)
                    messages.append(
                        {
                            "message_id": msg_id,
                            "timestamp": line,
                            "sender": sender[:80],
                            "subject": subject[:200],
                            "linked_opportunity_id": opp_id,
                            "route": "conversations",
                            "retrieved_at": datetime.now(UTC).isoformat(),
                        }
                    )

    # Classification
    invite_keywords = [
        "invite",
        "invitation",
        "apply",
        "represent",
        "join",
        "connect",
        "review your application",
    ]
    for msg in messages:
        combined = (msg.get("subject", "") + " " + msg.get("sender", "")).lower()
        if any(kw in combined for kw in invite_keywords):
            msg["classification"] = "explicit_invitation"
        elif any(kw in combined for kw in ["opportunity", "interested", "discuss"]):
            msg["classification"] = "likely_net_new_invitation"
        else:
            msg["classification"] = "uncertain"
        msg["invitation_confidence"] = msg["classification"]

    invitations = [m for m in messages if m.get("classification") == "explicit_invitation"]
    likely = [m for m in messages if m.get("classification") == "likely_net_new_invitation"]

    return {
        "badge_count": badge_count,
        "messages": messages,
        "invitations": invitations,
        "likely_invitations": likely,
        "retrieved_at": datetime.now(UTC).isoformat(),
    }


def _extract_find_opportunities_search(
    page, query: str = "", max_pages: int = 3
) -> list[dict[str, Any]]:
    _spa_navigate(page, "Find opportunities")
    page.wait_for_timeout(5000)

    if query:
        search_input = page.locator('input[placeholder*="search" i], input[type="search"]').first
        if search_input.count() > 0:
            search_input.fill(query)
            page.keyboard.press("Enter")
            page.wait_for_timeout(4000)

    all_results: list[dict[str, Any]] = []
    for _ in range(max_pages):
        text = page.locator("body").inner_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        skip = {
            "chat",
            "trash",
            "View all",
            "userIndependent sales agent",
            "Complete your profile",
            "Setup steps",
            "Spread the word",
        }
        page_items = []
        for line in lines:
            if line in skip or line.lower().startswith("check"):
                continue
            if len(line) > 20 and any(
                c in line for c in {"%", "$", "£", "Commission", "Earn", "Residual"}
            ):
                opp_id = _infer_opp_id(line)
                page_items.append(
                    {
                        "opportunity_id": opp_id,
                        "title": line[:200],
                        "search_query": query,
                        "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
                        "route": "find_opportunities",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )
        all_results.extend(page_items)

        # Next page
        next_btns = page.locator('button:has-text("Next"), [aria-label="Next"]').all()
        visible_next = None
        for btn in next_btns:
            try:
                if btn.is_visible():
                    visible_next = btn
                    break
            except Exception:
                continue
        if visible_next is None:
            break
        visible_next.click()
        page.wait_for_timeout(4000)

    # Deduplicate
    seen = set()
    deduped = []
    for item in all_results:
        if item["title"] not in seen:
            seen.add(item["title"])
            deduped.append(item)
    return deduped


def _reconcile_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    existing_ids = set()
    existing_titles = set()

    for o in inventory.get("my_opportunities", []):
        if o.get("opportunity_id"):
            existing_ids.add(o["opportunity_id"])
        existing_titles.add(o.get("title", "").lower().strip())

    for a in inventory.get("applications", []):
        if a.get("opportunity_id"):
            existing_ids.add(a["opportunity_id"])
        existing_titles.add(a.get("title", "").lower().strip())

    fav_candidates = []
    fav_excluded = []
    for f in inventory.get("favourites", []):
        fid = f.get("opportunity_id", "")
        if fid in existing_ids or f.get("title", "").lower().strip() in existing_titles:
            f["reconciliation_status"] = "excluded_existing_activity"
            fav_excluded.append(f)
        else:
            f["reconciliation_status"] = "favourite_candidate"
            fav_candidates.append(f)

    conv_candidates = []
    conv_excluded = []
    for c in inventory.get("conversations", {}).get("messages", []):
        cid = c.get("linked_opportunity_id", "")
        if cid in existing_ids:
            c["reconciliation_status"] = "excluded_existing_activity"
            conv_excluded.append(c)
        elif c.get("classification") in ("explicit_invitation", "likely_net_new_invitation"):
            c["reconciliation_status"] = "invitation_candidate"
            conv_candidates.append(c)
        else:
            c["reconciliation_status"] = "uncertain"
            conv_excluded.append(c)

    find_candidates = []
    find_excluded = []
    for f in inventory.get("find_opportunities", []):
        fid = f.get("opportunity_id", "")
        if fid in existing_ids or f.get("title", "").lower().strip() in existing_titles:
            f["reconciliation_status"] = "excluded_existing_activity"
            find_excluded.append(f)
        else:
            f["reconciliation_status"] = "find_candidate"
            find_candidates.append(f)

    return {
        "existing_ids": sorted(existing_ids),
        "existing_titles_count": len(existing_titles),
        "favourite_candidates": fav_candidates,
        "favourite_excluded": fav_excluded,
        "conversation_candidates": conv_candidates,
        "conversation_excluded": conv_excluded,
        "find_candidates": find_candidates,
        "find_excluded": find_excluded,
        "retrieved_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    inventory: dict[str, Any] = {
        "my_opportunities": [],
        "applications": [],
        "favourites": [],
        "conversations": {},
        "find_opportunities": [],
        "retrieved_at": datetime.now(UTC).isoformat(),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        _login(page)
        print(f"Login successful — URL: {page.url}")

        # Screenshot of dashboard for visual verification
        page.screenshot(path=str(REPORTS_DIR / "cca_dashboard_v4.png"), full_page=False)
        print("Dashboard screenshot saved.")

        # My Opportunities
        inventory["my_opportunities"] = _extract_my_opportunities(page)
        print(f"My Opportunities: {len(inventory['my_opportunities'])}")
        for o in inventory["my_opportunities"]:
            print(f"  -> {o['opportunity_id']}: {o['title'][:50]} status={o['status']}")

        # Applications
        inventory["applications"] = _extract_applications(page)
        print(f"Applications: {len(inventory['applications'])}")
        for a in inventory["applications"]:
            print(f"  -> {a['opportunity_id']}: {a['title'][:50]} status={a['status']}")

        # Favourites (star icon or sidebar)
        inventory["favourites"] = _extract_favourites(page)
        print(f"Favourites: {len(inventory['favourites'])}")
        for f in inventory["favourites"][:5]:
            print(f"  -> {f.get('opportunity_id', '')}: {f['title'][:60]}")

        # Conversations (speech bubble or sidebar)
        inventory["conversations"] = _extract_conversations(page)
        conv = inventory["conversations"]
        print(f"Conversations badge_count: {conv.get('badge_count')}")
        print(f"Messages: {len(conv.get('messages', []))}")
        print(f"Invitations: {len(conv.get('invitations', []))}")
        print(f"Likely invitations: {len(conv.get('likely_invitations', []))}")
        for m in conv.get("messages", [])[:5]:
            print(f"  -> {m['sender'][:30]}: {m['subject'][:50]} [{m['classification']}]")

        # Find Opportunities — multiple searches
        search_queries = [
            "B2B SaaS",
            "AI",
            "automation",
            "cybersecurity",
            "software",
            "recurring revenue",
            "data",
            "business services",
        ]
        all_find: list[dict[str, Any]] = []
        for q in search_queries:
            results = _extract_find_opportunities_search(page, query=q, max_pages=2)
            print(f"Find '{q}': {len(results)} results")
            all_find.extend(results)

        seen_titles = set()
        deduped_find = []
        for f in all_find:
            t = f["title"].lower().strip()
            if t not in seen_titles:
                seen_titles.add(t)
                deduped_find.append(f)
        inventory["find_opportunities"] = deduped_find
        print(f"Find Opportunities total (deduped): {len(deduped_find)}")

        browser.close()

    # Save per-source reports
    fav_path = REPORTS_DIR / "cca_favourite_opportunities_inventory.json"
    with open(fav_path, "w") as fh:
        json.dump(
            {
                "favourites": inventory["favourites"],
                "retrieved_at": inventory["retrieved_at"],
            },
            fh,
            indent=2,
        )
    print(f"\nSaved: {fav_path}")

    conv_path = REPORTS_DIR / "cca_conversations_inventory.json"
    with open(conv_path, "w") as fh:
        json.dump(inventory["conversations"], fh, indent=2)
    print(f"Saved: {conv_path}")

    find_path = REPORTS_DIR / "cca_find_opportunities_search_log.json"
    with open(find_path, "w") as fh:
        json.dump(
            {
                "search_queries": search_queries,
                "results_count": len(deduped_find),
                "results": deduped_find,
                "retrieved_at": inventory["retrieved_at"],
            },
            fh,
            indent=2,
        )
    print(f"Saved: {find_path}")

    # Reconcile
    reconciliation = _reconcile_inventory(inventory)

    # Save state registry
    registry = {
        "my_opportunities": inventory["my_opportunities"],
        "applications": inventory["applications"],
        "favourites": inventory["favourites"],
        "conversations": inventory["conversations"],
        "find_opportunities": inventory["find_opportunities"],
        "reconciliation": reconciliation,
        "retrieved_at": inventory["retrieved_at"],
    }
    reg_path = REPORTS_DIR / "cca_opportunity_state_registry.json"
    with open(reg_path, "w") as fh:
        json.dump(registry, fh, indent=2)
    print(f"Saved: {reg_path}")

    # Markdown report
    md_lines = [
        "# CCA Browser Discovery Report",
        "",
        f"**Retrieved:** {inventory['retrieved_at']}",
        "",
        "## My Opportunities",
        f"- Count: {len(inventory['my_opportunities'])}",
    ]
    for o in inventory["my_opportunities"]:
        md_lines.append(
            f"  - `{o['opportunity_id']}` — {o['title'][:80]} — *{o['lifecycle_state']}*"
        )

    md_lines.extend(["", "## Applications", f"- Count: {len(inventory['applications'])}"])
    for a in inventory["applications"]:
        md_lines.append(
            f"  - `{a['opportunity_id']}` — {a['title'][:80]} — *{a['lifecycle_state']}*"
        )

    md_lines.extend(
        [
            "",
            "## Favourite Opportunities",
            f"- Count: {len(inventory['favourites'])}",
            f"- Net-new candidates: {len(reconciliation['favourite_candidates'])}",
            f"- Excluded existing: {len(reconciliation['favourite_excluded'])}",
        ]
    )
    for f in inventory["favourites"][:10]:
        md_lines.append(f"  - `{f.get('opportunity_id', '')}` — {f['title'][:80]}")

    md_lines.extend(
        [
            "",
            "## Conversations / Messages",
            f"- Badge count: {conv.get('badge_count')}",
            f"- Messages inspected: {len(conv.get('messages', []))}",
            f"- Explicit invitations: {len(conv.get('invitations', []))}",
            f"- Likely invitations: {len(conv.get('likely_invitations', []))}",
            f"- Net-new candidates: {len(reconciliation['conversation_candidates'])}",
            f"- Excluded existing: {len(reconciliation['conversation_excluded'])}",
        ]
    )
    for m in conv.get("messages", [])[:10]:
        md_lines.append(
            f"  - `{m['message_id']}` — {m['sender'][:30]} — {m['subject'][:50]} — *{m['classification']}*"
        )

    md_lines.extend(
        [
            "",
            "## Find Opportunities",
            f"- Search queries: {', '.join(search_queries)}",
            f"- Total results (deduped): {len(deduped_find)}",
            f"- Net-new candidates: {len(reconciliation['find_candidates'])}",
            f"- Excluded existing: {len(reconciliation['find_excluded'])}",
        ]
    )
    for f in deduped_find[:10]:
        md_lines.append(
            f"  - `{f.get('opportunity_id', '')}` — {f['title'][:80]} (query: {f.get('search_query', '')})"
        )

    md_lines.extend(
        [
            "",
            "## Reconciliation Summary",
            f"- Existing opportunity IDs: {len(reconciliation['existing_ids'])}",
            f"- Existing titles tracked: {reconciliation['existing_titles_count']}",
            f"- Favourite candidates: {len(reconciliation['favourite_candidates'])}",
            f"- Conversation candidates: {len(reconciliation['conversation_candidates'])}",
            f"- Find candidates: {len(reconciliation['find_candidates'])}",
            "",
            "## Safety Checks",
            "- No applications submitted.",
            "- No invitations accepted.",
            "- No messages sent.",
            "- No emails sent.",
            "- No external calendar invitations created.",
        ]
    )

    md_path = REPORTS_DIR / "cca_browser_discovery_reconciliation.md"
    with open(md_path, "w") as fh:
        fh.write("\n".join(md_lines))
    print(f"Saved: {md_path}")

    # Summary JSON
    summary = {
        "retrieved_at": inventory["retrieved_at"],
        "my_opportunities_count": len(inventory["my_opportunities"]),
        "applications_count": len(inventory["applications"]),
        "favourites_count": len(inventory["favourites"]),
        "conversation_badge_count": conv.get("badge_count"),
        "messages_count": len(conv.get("messages", [])),
        "invitations_count": len(conv.get("invitations", [])),
        "likely_invitations_count": len(conv.get("likely_invitations", [])),
        "find_opportunities_count": len(deduped_find),
        "favourite_candidates": len(reconciliation["favourite_candidates"]),
        "conversation_candidates": len(reconciliation["conversation_candidates"]),
        "find_candidates": len(reconciliation["find_candidates"]),
        "existed_activity_excluded": len(reconciliation["favourite_excluded"])
        + len(reconciliation["conversation_excluded"])
        + len(reconciliation["find_excluded"]),
    }
    summary_path = REPORTS_DIR / "cca_browser_discovery_summary.json"
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"Saved: {summary_path}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

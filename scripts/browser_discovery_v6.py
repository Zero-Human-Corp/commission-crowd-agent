#!/usr/bin/env python3
"""CommissionCrowd deep browser discovery — v6 SPA-safe navigation.

Uses JavaScript hash changes for in-app navigation (no page reloads),
which preserves Ember.js authentication state.
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
import contextlib

from commission_crowd_agent.config import load_settings

SETTINGS = load_settings()
BASE_URL = "https://www.commissioncrowd.com"
REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically with timestamped backup of any existing file."""
    if path.exists():
        backup = path.with_suffix(f".json.backup-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}")
        backup.write_bytes(path.read_bytes())
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    tmp.replace(path)


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


def _login(page) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill('input[type="email"]', SETTINGS.commissioncrowd_username)
    page.fill('input[type="password"]', SETTINGS.commissioncrowd_password)
    page.click('button[type="submit"]')
    # Wait for SPA to initialize and redirect to dashboard
    for _ in range(20):
        page.wait_for_timeout(1000)
        url = page.url
        if "#/agent/dashboard" in url or "#/agent" in url:
            break
    page.wait_for_timeout(3000)


def _spa_hash(page, hash_path: str) -> None:
    """Change hash without reloading the SPA."""
    page.evaluate(f"window.location.hash = '{hash_path}'")
    page.wait_for_timeout(5000)


def _js_extract_table_rows(
    page, required_headers: set[str], title_min_len: int = 10
) -> list[dict[str, Any]]:
    """Generic JS table extractor."""
    js = rf"""
    () => {{
        const rows = [];
        const tables = document.querySelectorAll('table');
        for (const table of tables) {{
            const ths = table.querySelectorAll('th, thead th');
            const htext = Array.from(ths).map(h => h.innerText).join(' ').toLowerCase();
            const required = {json.dumps(list(required_headers))};
            if (required.every(r => htext.includes(r))) {{
                const trs = table.querySelectorAll('tbody tr');
                for (const tr of trs) {{
                    const tds = tr.querySelectorAll('td');
                    if (tds.length >= 3) {{
                        const cells = Array.from(tds).map(td => td.innerText.trim());
                        const title = cells[0];
                        if (title.length >= {title_min_len} && !title.toLowerCase().includes('opportunity name')) {{
                            const link = tds[0].querySelector('a[href*="/opportunities/"]');
                            let oppId = '';
                            if (link) {{
                                const m = link.href.match(/\/opportunities\/(\d+)/);
                                oppId = m ? m[1] : '';
                            }}
                            rows.push({{cells, opp_id: oppId}});
                        }}
                    }}
                }}
            }}
        }}
        return rows;
    }}
    """
    return page.evaluate(js)


def _extract_my_opportunities(page) -> list[dict[str, Any]]:
    _spa_hash(page, "#/agent/my-opportunities")
    raw = _js_extract_table_rows(page, {"opportunity", "completeness", "status"})
    items = []
    for r in raw:
        cells = r["cells"]
        opp_id = r.get("opp_id", "")
        items.append(
            {
                "opportunity_id": opp_id,
                "title": cells[0][:200],
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
    _spa_hash(page, "#/agent/applications")
    raw = _js_extract_table_rows(page, {"status", "opportunity", "date"})
    items = []
    for r in raw:
        cells = r["cells"]
        opp_id = r.get("opp_id", "")
        items.append(
            {
                "opportunity_id": opp_id,
                "title": cells[1][:200] if len(cells) > 1 else cells[0][:200],
                "status": cells[0],
                "application_date": cells[2] if len(cells) > 2 else "",
                "lifecycle_state": _map_status(cells[0]),
                "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
                "route": "applications",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )
    return items


def _extract_favourites(page) -> list[dict[str, Any]]:
    _spa_hash(page, "#/agent/favourites")
    raw = _js_extract_table_rows(page, {"opportunity", "completeness", "status"})
    items = []
    for r in raw:
        cells = r["cells"]
        opp_id = r.get("opp_id", "")
        title = cells[0]
        if title.lower().startswith("awaiting approval"):
            # This might be an applications row leaking in
            continue
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

    # If no table rows, fallback to card extraction
    if not items:
        js = """
        () => {
            const items = [];
            const cards = document.querySelectorAll('.opportunity-card, .opportunity-item, [class*="opportunity"]');
            for (const card of cards) {
                const text = card.innerText.trim();
                if (text.length > 20 && (text.includes('%') || text.includes('$') || text.includes('£') || text.includes('Commission'))) {
                    const link = card.querySelector('a[href*="/opportunities/"]');
                    const href = link ? link.href : '';
                    const m = href.match(/\\/opportunities\\/(\\d+)/);
                    const oppId = m ? m[1] : '';
                    items.push({title: text.split('\\n')[0].trim(), opp_id: oppId, href});
                }
            }
            return items;
        }
        """
        raw_cards = page.evaluate(js)
        for rc in raw_cards:
            title = rc.get("title", "")[:200]
            opp_id = rc.get("opp_id", "")
            if title:
                items.append(
                    {
                        "opportunity_id": opp_id,
                        "title": title,
                        "source_url": rc.get("href", "")
                        or (f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else ""),
                        "route": "favourite_opportunities",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )
    return items


def _extract_conversations(page) -> dict[str, Any]:
    _spa_hash(page, "#/agent/conversations")

    # Badge count from top nav (eval on current page)
    badge_count = None
    with contextlib.suppress(Exception):
        badge_count = page.evaluate("""
            () => {
                const bubbles = document.querySelectorAll('.count-bubble.conversations, .count-bubble');
                for (const b of bubbles) {
                    const text = b.innerText.trim();
                    if (/^\\d+$/.test(text)) return parseInt(text);
                }
                return null;
            }
        """)

    # Extract conversation table
    js = """
    () => {
        const rows = [];
        const tables = document.querySelectorAll('table');
        for (const table of tables) {
            const ths = table.querySelectorAll('th, thead th');
            const htext = Array.from(ths).map(h => h.innerText).join(' ').toLowerCase();
            if (htext.includes('date') && htext.includes('from') && htext.includes('subject')) {
                const trs = table.querySelectorAll('tbody tr');
                for (const tr of trs) {
                    const tds = tr.querySelectorAll('td');
                    if (tds.length >= 3) {
                        const date = tds[0].innerText.trim();
                        const sender = tds[1].innerText.trim();
                        const subject = tds[2].innerText.trim();
                        if (date && sender && subject && sender !== 'From' && !sender.toLowerCase().includes('reply')) {
                            rows.push({date, sender, subject});
                        }
                    }
                }
            }
        }
        return rows;
    }
    """
    raw = page.evaluate(js)
    messages = []
    seen = set()
    for r in raw:
        key = r["date"] + "|" + r["sender"] + "|" + r["subject"]
        if key in seen:
            continue
        seen.add(key)
        msg_id = f"msg-{abs(hash(key)) % 100000}"
        opp_id = _infer_opp_id(r.get("subject", "") + " " + r.get("sender", ""))
        combined = (r.get("subject", "") + " " + r.get("sender", "")).lower()
        if any(
            kw in combined
            for kw in [
                "invite",
                "invitation",
                "apply",
                "represent",
                "join",
                "connect",
                "review your application",
            ]
        ):
            classification = "explicit_invitation"
        elif any(kw in combined for kw in ["opportunity", "interested", "discuss"]):
            classification = "likely_net_new_invitation"
        else:
            classification = "uncertain"
        messages.append(
            {
                "message_id": msg_id,
                "timestamp": r["date"],
                "sender": r["sender"][:80],
                "subject": r["subject"][:200],
                "linked_opportunity_id": opp_id,
                "classification": classification,
                "invitation_confidence": classification,
                "route": "conversations",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )

    invitations = [m for m in messages if m["classification"] == "explicit_invitation"]
    likely = [m for m in messages if m["classification"] == "likely_net_new_invitation"]

    return {
        "badge_count": badge_count,
        "messages": messages,
        "invitations": invitations,
        "likely_invitations": likely,
        "retrieved_at": datetime.now(UTC).isoformat(),
    }


def _navigate_to_find_opportunities(page) -> None:
    """Navigate to Find Opportunities once. Preserves Ember.js auth state."""
    current = page.url
    if "#/agent/opportunities/search_opportunities" in current:
        return  # Already on the page
    try:
        page.click("text=Find opportunities", timeout=10000)
    except Exception:
        page.evaluate("window.location.hash = 'agent/opportunities/search_opportunities'")
    page.wait_for_timeout(4000)


def _js_click(page, selector: str) -> bool:
    """Fallback click via JavaScript when Playwright click times out on viewport issues."""
    return page.evaluate(
        f"""() => {{
            const el = document.querySelector("{selector}");
            if (el) {{ el.click(); return true; }}
            return false;
        }}"""
    )


def _extract_find_opportunities(
    page, query: str = "", max_pages: int = 2, *, navigate: bool = False
) -> list[dict[str, Any]]:
    """Extract Find Opportunities. Set navigate=True for the first call only."""
    if navigate:
        _navigate_to_find_opportunities(page)

    # Check if we got an actual search shell or error
    body_preview = page.evaluate("() => document.body.innerText.slice(0, 300)")
    has_error = (
        "There were errors" in body_preview
        or "404 NOT FOUND" in body_preview
        or "server is not responding" in body_preview
    )
    has_shell = (
        "Advanced search" in body_preview
        or "Search by company name" in body_preview
        or "Target industries" in body_preview
    )

    if has_error and not has_shell:
        # Genuine platform error, not a loadable search page
        return []

    # If search shell is present but results not loaded, trigger Search button
    results_present = page.evaluate(
        "() => !!document.querySelector('.search-results .card')"
    )
    if not results_present:
        # Try to enter query in any visible search field
        if query:
            try:
                # Try global search input first
                search_input = page.locator(
                    'input[placeholder*="search" i], input[type="search"], #id-search-everything'
                ).first
                if search_input.count() > 0:
                    search_input.fill(query)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(4000)
            except Exception:
                pass
            # Also try the "Products / Keyword" or "Search by company name" field
            try:
                keyword_input = page.locator(
                    'input[placeholder*="keyword" i], input[placeholder*="company" i], input#id-products-keyword'
                ).first
                if keyword_input.count() > 0:
                    keyword_input.fill(query)
                    page.wait_for_timeout(500)
            except Exception:
                pass
        try:
            # Click the actual orange Search button — JS fallback for viewport issues
            search_btn = page.locator('button.carrot.stretch, button:has-text("Search")').first
            if search_btn.count() > 0:
                try:
                    search_btn.click()
                except Exception:
                    _js_click(page, "button.carrot.stretch")
                page.wait_for_timeout(6000)
        except Exception:
            pass

    # Wait for spinner to disappear if present
    for _ in range(10):
        spinner_visible = page.evaluate(
            "() => !!document.querySelector('.loading-spinner, .spinner, .ember-loading')"
        )
        if not spinner_visible:
            break
        page.wait_for_timeout(1000)

    all_results: list[dict[str, Any]] = []
    for _ in range(max_pages):
        js = """
        () => {
            const items = [];
            const seenIds = new Set();
            // CommissionCrowd search results use .search-results .card (parent card, avoid .card-body duplication)
            const cards = document.querySelectorAll('.search-results .card');
            for (const card of cards) {
                const text = card.innerText.trim();
                // Heuristic: must contain commission symbol and a title-like line
                if (text.length > 30 && (text.includes('%') || text.includes('Commission'))) {
                    const link = card.querySelector('a[href*="/opportunities/"]');
                    const href = link ? link.href : '';
                    const m = href.match(/\\/opportunities\\/(\\d+)/);
                    const oppId = m ? m[1] : '';
                    if (oppId && seenIds.has(oppId)) continue;
                    if (oppId) seenIds.add(oppId);
                    // First meaningful line as title
                    const lines = text.split('\\n').filter(l => l.trim().length > 5);
                    const title = lines.length > 0 ? lines[0].trim() : '';
                    items.push({title, full_text: text, opp_id: oppId, href});
                }
            }
            return items;
        }
        """
        raw = page.evaluate(js)
        seen = set()
        for r in raw:
            title = r.get("title", "")[:200]
            if not title or title in seen:
                continue
            seen.add(title)
            opp_id = r.get("opp_id", "")
            all_results.append(
                {
                    "opportunity_id": opp_id,
                    "title": title,
                    "full_text": r.get("full_text", "")[:500],
                    "search_query": query,
                    "source_url": r.get("href", "")
                    or (f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else ""),
                    "route": "find_opportunities",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            )

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

    return all_results


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
        page.screenshot(path=str(REPORTS_DIR / "cca_dashboard_v6.png"), full_page=False)
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

        # Favourites
        inventory["favourites"] = _extract_favourites(page)
        print(f"Favourites: {len(inventory['favourites'])}")
        for f in inventory["favourites"][:5]:
            print(f"  -> {f.get('opportunity_id', '')}: {f['title'][:60]}")

        # Conversations
        inventory["conversations"] = _extract_conversations(page)
        conv = inventory["conversations"]
        print(f"Conversations badge_count: {conv.get('badge_count')}")
        print(f"Messages: {len(conv.get('messages', []))}")
        print(f"Invitations: {len(conv.get('invitations', []))}")
        print(f"Likely invitations: {len(conv.get('likely_invitations', []))}")
        for m in conv.get("messages", [])[:5]:
            print(f"  -> {m['sender'][:30]}: {m['subject'][:50]} [{m['classification']}]")

        # Find Opportunities — multiple searches (single navigation)
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
        for i, q in enumerate(search_queries):
            results = _extract_find_opportunities(page, query=q, max_pages=2, navigate=(i == 0))
            print(f"Find '{q}': {len(results)} results")
            all_find.extend(results)

        # Deduplicate
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

    # Save reports (atomic with backup)
    fav_path = REPORTS_DIR / "cca_favourite_opportunities_inventory.json"
    _atomic_write_json(
        fav_path,
        {"favourites": inventory["favourites"], "retrieved_at": inventory["retrieved_at"]},
    )
    print(f"\nSaved: {fav_path}")

    conv_path = REPORTS_DIR / "cca_conversations_inventory.json"
    _atomic_write_json(
        conv_path,
        inventory["conversations"],
    )
    print(f"Saved: {conv_path}")

    find_path = REPORTS_DIR / "cca_find_opportunities_search_log.json"
    _atomic_write_json(
        find_path,
        {
            "search_queries": search_queries,
            "results_count": len(deduped_find),
            "results": deduped_find,
            "retrieved_at": inventory["retrieved_at"],
        },
    )
    print(f"Saved: {find_path}")

    # Reconcile
    reconciliation = _reconcile_inventory(inventory)

    # Save state registry (atomic)
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
    _atomic_write_json(reg_path, registry)
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
    _atomic_write_json(summary_path, summary)
    print(f"Saved: {summary_path}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

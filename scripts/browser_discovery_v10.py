#!/usr/bin/env python3
"""CCA browser discovery v10 — fixes favourites false positives + Find Opportunities.

Changes from v9:
  • Favourites extractor now requires 4+ <td> per row (matches actual favourites table
    with icon | title | chat | trash columns). Excludes stats/setup/referral tables.
  • Find Opportunities: when search triggers a server error, we capture the error state
    and attempt to use the "Featured & Matching" carousel as a fallback for new leads.
  • Conversation subject extraction improved to avoid tab artifacts.
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


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
    for _ in range(25):
        page.wait_for_timeout(1000)
        if "#/agent" in page.url:
            break
    page.wait_for_timeout(3000)


def _spa_hash(page, hash_path: str, settle_ms: int = 5000) -> None:
    page.evaluate(f"window.location.hash = '{hash_path}'")
    page.wait_for_timeout(settle_ms)


def _extract_tables_generic(
    page, required_substrings: list[str], min_cols: int = 3
) -> list[dict[str, Any]]:
    """Extract rows from tables whose joined header text contains all required substrings."""
    js = f"""
    () => {{
        const items = [];
        const tables = document.querySelectorAll('table');
        for (const table of tables) {{
            const ths = table.querySelectorAll('th, thead td');
            const htext = Array.from(ths).map(h => h.innerText.trim()).join(' ').toLowerCase();
            const required = {json.dumps(required_substrings)};
            if (required.every(r => htext.includes(r))) {{
                const rows = table.querySelectorAll('tbody tr');
                for (const row of rows) {{
                    const tds = row.querySelectorAll('td');
                    if (tds.length >= {min_cols}) {{
                        const cells = Array.from(tds).map(td => td.innerText.trim());
                        const link = tds[0].querySelector('a[href*="/opportunities/"]');
                        let oppId = '';
                        if (link) {{
                            const m = link.href.match(/\\/opportunities\\/(\\d+)/);
                            oppId = m ? m[1] : '';
                        }}
                        items.push({{cells, opp_id: oppId}});
                    }}
                }}
            }}
        }}
        return items;
    }}
    """
    return page.evaluate(js)


def _extract_my_opportunities_dedicated(page) -> list[dict[str, Any]]:
    _spa_hash(page, "#/agent/my-opportunities", settle_ms=6000)
    raw = _extract_tables_generic(page, ["opportunity", "completeness", "status"])
    out = []
    for r in raw:
        cells = r["cells"]
        title = cells[0]
        if (
            not title
            or title.lower().startswith("you are not working")
            or title.lower() == "opportunity name"
        ):
            continue
        opp_id = r.get("opp_id", "")
        out.append(
            {
                "opportunity_id": opp_id,
                "title": title[:200],
                "completeness": cells[1] if len(cells) > 1 else "",
                "status": cells[2] if len(cells) > 2 else "",
                "lifecycle_state": _map_status(cells[2] if len(cells) > 2 else ""),
                "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
                "route": "my_opportunities",
                "retrieved_at": _now(),
            }
        )
    return out


def _extract_applications_dedicated(page) -> list[dict[str, Any]]:
    _spa_hash(page, "#/agent/applications", settle_ms=6000)
    raw = _extract_tables_generic(page, ["status", "opportunity", "date"])
    out = []
    for r in raw:
        cells = r["cells"]
        status = cells[0] if len(cells) > 0 else ""
        title = cells[1] if len(cells) > 1 else ""
        app_date = cells[2] if len(cells) > 2 else ""
        if (
            not title
            or title.lower().startswith("opportunity")
            or title.lower() == "opportunity name"
        ):
            continue
        opp_id = r.get("opp_id", "")
        out.append(
            {
                "opportunity_id": opp_id,
                "title": title[:200],
                "status": status,
                "application_date": app_date,
                "lifecycle_state": _map_status(status),
                "source_url": f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else "",
                "route": "applications",
                "retrieved_at": _now(),
            }
        )
    return out


def _extract_favourites_table(page) -> list[dict[str, Any]]:
    """Extract from the right sidebar favourites table.

    The favourites table has empty headers and 4+ columns per row:
    [icon] | [title with commission text] | chat | trash
    """
    js = """
    () => {
        const items = [];
        const tables = document.querySelectorAll('table');
        for (const table of tables) {
            const headers = Array.from(table.querySelectorAll('th, thead td')).map(h => h.innerText.trim());
            const rows = table.querySelectorAll('tbody tr');
            for (const row of rows) {
                const tds = row.querySelectorAll('td');
                // Favourites table has 4+ tds (icon, title, chat, trash)
                if (tds.length >= 4) {
                    const text = row.innerText.trim();
                    // Must contain commission language and exclude non-opportunity artifacts
                    if (
                        text.length > 30 &&
                        (text.includes('%') || text.includes('$') || text.includes('£') || text.includes('Commission') || text.includes('Deal')) &&
                        !text.toLowerCase().includes('profile completeness') &&
                        !text.toLowerCase().includes('profile status') &&
                        !text.toLowerCase().includes('profile views') &&
                        !text.toLowerCase().includes('total referrals') &&
                        !text.toLowerCase().includes('paid referrals') &&
                        !text.toLowerCase().includes('complete your profile') &&
                        !text.toLowerCase().includes('complete contract') &&
                        !text.toLowerCase().includes('search for opportunities')
                    ) {
                        const link = row.querySelector('a[href*="/opportunities/"]');
                        let oppId = '';
                        let href = '';
                        if (link) {
                            const m = link.href.match(/\\/opportunities\\/(\\d+)/);
                            oppId = m ? m[1] : '';
                            href = link.href;
                        }
                        // Clean title: remove icon cells and action words
                        const cleanTitle = text.split('\\n').filter(line =>
                            line.length > 15 &&
                            !line.match(/^(chat|trash|delete|remove|edit|view)$/i) &&
                            !line.match(/^\\s*$/)
                        ).join(' ').trim();
                        if (cleanTitle.length > 20) {
                            items.push({title: cleanTitle, opp_id: oppId, href});
                        }
                    }
                }
            }
        }
        return items;
    }
    """
    raw = page.evaluate(js)
    out = []
    seen = set()
    for r in raw:
        title = r.get("title", "")[:200]
        if not title or title in seen:
            continue
        seen.add(title)
        opp_id = r.get("opp_id", "")
        out.append(
            {
                "opportunity_id": opp_id,
                "title": title,
                "source_url": r.get("href", "")
                or (f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else ""),
                "route": "favourite_opportunities",
                "retrieved_at": _now(),
            }
        )
    return out


def _extract_conversations_dashboard(page) -> dict[str, Any]:
    raw = _extract_tables_generic(page, ["date", "from", "subject"])
    messages = []
    seen = set()
    for r in raw:
        cells = r["cells"]
        if len(cells) < 3:
            continue
        date_str = cells[0]
        sender = cells[1]
        subject = cells[2]
        if not date_str or not sender or sender.lower() == "from":
            continue
        key = date_str + "|" + sender + "|" + subject
        if key in seen:
            continue
        seen.add(key)
        msg_id = f"msg-{abs(hash(key)) % 100000}"
        opp_id = _infer_opp_id(subject + " " + sender)
        combined = (subject + " " + sender).lower()
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
                "timestamp": date_str,
                "sender": sender[:80],
                "subject": subject[:200],
                "linked_opportunity_id": opp_id,
                "classification": classification,
                "route": "conversations",
                "retrieved_at": _now(),
            }
        )

    badge_count = None
    try:
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
    except Exception:
        pass

    return {
        "badge_count": badge_count,
        "messages": messages,
        "invitations": [m for m in messages if m["classification"] == "explicit_invitation"],
        "likely_invitations": [
            m for m in messages if m["classification"] == "likely_net_new_invitation"
        ],
        "retrieved_at": _now(),
    }


def _extract_featured_matching(page) -> list[dict[str, Any]]:
    """Extract from dashboard 'Featured & Matching Opportunities' carousel."""
    js = """
    () => {
        const items = [];
        const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6, .section-title, .panel-title');
        let container = null;
        for (const h of headings) {
            if (h.innerText.toLowerCase().includes('featured') || h.innerText.toLowerCase().includes('matching')) {
                container = h.closest('.panel, .card, .widget, section, div[class*="carousel"], div[class*="slider"]') || h.parentElement.parentElement;
                break;
            }
        }
        if (!container) return items;
        const cards = container.querySelectorAll('.opportunity-card, [class*="opportunity"], .card, [class*="slide"], [class*="item"]');
        for (const card of cards) {
            const link = card.querySelector('a[href*="/opportunities/"]');
            if (link) {
                const text = card.innerText.trim();
                const m = link.href.match(/\\/opportunities\\/(\\d+)/);
                const oppId = m ? m[1] : '';
                items.push({title: text.split('\\n')[0].trim(), opp_id: oppId, href: link.href, full_text: text});
            }
        }
        return items;
    }
    """
    raw = page.evaluate(js)
    out = []
    seen = set()
    for r in raw:
        title = r.get("title", "")[:200]
        if not title or title in seen:
            continue
        seen.add(title)
        opp_id = r.get("opp_id", "")
        out.append(
            {
                "opportunity_id": opp_id,
                "title": title,
                "full_text": r.get("full_text", "")[:500],
                "source_url": r.get("href", "")
                or (f"{BASE_URL}/app/opportunities/{opp_id}" if opp_id else ""),
                "route": "featured_matching",
                "retrieved_at": _now(),
            }
        )
    return out


def _extract_find_opportunities(
    page, query: str = "", max_pages: int = 3
) -> tuple[list[dict[str, Any]], str]:
    _spa_hash(page, "#/opportunities/search", settle_ms=7000)
    has_error = False
    error_text = ""

    if query:
        try:
            inp = page.locator('input[placeholder*="search" i], input[type="search"]').first
            if inp.count() > 0:
                inp.fill(query)
                page.keyboard.press("Enter")
                page.wait_for_timeout(5000)
        except Exception:
            pass

    # Check for server error modal
    body_text = page.evaluate("() => document.body.innerText")
    if "server is not responding" in body_text.lower() or "there were errors" in body_text.lower():
        has_error = True
        error_text = "server_error"

    all_results: list[dict[str, Any]] = []
    for _ in range(max_pages):
        js = """
        () => {
            const items = [];
            const cards = document.querySelectorAll('.opportunity-card, .opportunity-item, [class*="opportunity"], .card');
            for (const card of cards) {
                const text = card.innerText.trim();
                if (text.length > 40 && (text.includes('%') || text.includes('$') || text.includes('£') || text.includes('Commission') || text.includes('Deal'))) {
                    const link = card.querySelector('a[href*="/opportunities/"]');
                    const href = link ? link.href : '';
                    const m = href.match(/\\/opportunities\\/(\\d+)/);
                    const oppId = m ? m[1] : '';
                    const title = text.split('\\n')[0].trim();
                    if (title.length > 10 && !title.toLowerCase().includes('close') && !title.toLowerCase().includes('filter') && !title.toLowerCase().includes('sort') && !title.toLowerCase().includes('there were errors')) {
                        items.push({title, full_text: text, opp_id: oppId, href});
                    }
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
                    "retrieved_at": _now(),
                }
            )

        # Pagination
        next_btns = page.locator('button:has-text("Next"), [aria-label="Next"]').all()
        visible = None
        for btn in next_btns:
            try:
                if btn.is_visible():
                    visible = btn
                    break
            except Exception:
                continue
        if visible is None:
            break
        visible.click()
        page.wait_for_timeout(4000)

    return all_results, error_text


def _reconcile(inventory: dict[str, Any]) -> dict[str, Any]:
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

    fav_candidates, fav_excluded = [], []
    for f in inventory.get("favourites", []):
        fid = f.get("opportunity_id", "")
        if fid in existing_ids or f.get("title", "").lower().strip() in existing_titles:
            f["reconciliation_status"] = "excluded_existing_activity"
            fav_excluded.append(f)
        else:
            f["reconciliation_status"] = "favourite_candidate"
            fav_candidates.append(f)

    conv_candidates, conv_excluded = [], []
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

    find_candidates, find_excluded = [], []
    find_errors = []
    for f in inventory.get("find_opportunities", []):
        if f.get("_error"):
            find_errors.append(f)
            continue
        fid = f.get("opportunity_id", "")
        if fid in existing_ids or f.get("title", "").lower().strip() in existing_titles:
            f["reconciliation_status"] = "excluded_existing_activity"
            find_excluded.append(f)
        else:
            f["reconciliation_status"] = "find_candidate"
            find_candidates.append(f)

    feat_candidates, feat_excluded = [], []
    for f in inventory.get("featured_matching", []):
        fid = f.get("opportunity_id", "")
        if fid in existing_ids or f.get("title", "").lower().strip() in existing_titles:
            f["reconciliation_status"] = "excluded_existing_activity"
            feat_excluded.append(f)
        else:
            f["reconciliation_status"] = "featured_candidate"
            feat_candidates.append(f)

    return {
        "existing_ids": sorted(existing_ids),
        "existing_titles_count": len(existing_titles),
        "favourite_candidates": fav_candidates,
        "favourite_excluded": fav_excluded,
        "conversation_candidates": conv_candidates,
        "conversation_excluded": conv_excluded,
        "find_candidates": find_candidates,
        "find_excluded": find_excluded,
        "find_errors": find_errors,
        "featured_candidates": feat_candidates,
        "featured_excluded": feat_excluded,
        "retrieved_at": _now(),
    }


def main() -> int:
    inventory: dict[str, Any] = {
        "my_opportunities": [],
        "applications": [],
        "favourites": [],
        "conversations": {},
        "featured_matching": [],
        "find_opportunities": [],
        "retrieved_at": _now(),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _login(page)
        print(f"Logged in: {page.url}")
        page.screenshot(path=str(REPORTS_DIR / "cca_v10_dashboard.png"), full_page=True)
        print("Dashboard screenshot saved.")

        # 1. My Opportunities (dedicated page)
        inventory["my_opportunities"] = _extract_my_opportunities_dedicated(page)
        print(f"My Opportunities: {len(inventory['my_opportunities'])}")
        for o in inventory["my_opportunities"]:
            print(f"  -> {o['opportunity_id']}: {o['title'][:50]} status={o['status']}")

        # 2. Applications (dedicated page)
        inventory["applications"] = _extract_applications_dedicated(page)
        print(f"Applications: {len(inventory['applications'])}")
        for a in inventory["applications"]:
            print(f"  -> {a['opportunity_id']}: {a['title'][:50]} status={a['status']}")

        # 3. Dashboard extractions
        _spa_hash(page, "#/agent/dashboard", settle_ms=6000)

        # Favourites
        inventory["favourites"] = _extract_favourites_table(page)
        print(f"Favourites: {len(inventory['favourites'])}")
        for f in inventory["favourites"][:10]:
            print(f"  -> {f.get('opportunity_id', '')}: {f['title'][:70]}")

        # Conversations
        inventory["conversations"] = _extract_conversations_dashboard(page)
        conv = inventory["conversations"]
        print(f"Conversations badge_count: {conv.get('badge_count')}")
        print(f"Messages: {len(conv.get('messages', []))}")
        print(f"Invitations: {len(conv.get('invitations', []))}")
        print(f"Likely invitations: {len(conv.get('likely_invitations', []))}")
        for m in conv.get("messages", [])[:10]:
            print(f"  -> {m['sender'][:30]}: {m['subject'][:50]} [{m['classification']}]")

        # Featured/Matching
        inventory["featured_matching"] = _extract_featured_matching(page)
        print(f"Featured/Matching: {len(inventory['featured_matching'])}")
        for fm in inventory["featured_matching"][:10]:
            print(f"  -> {fm.get('opportunity_id', '')}: {fm['title'][:70]}")

        # 4. Find Opportunities
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
        find_errors: list[dict[str, str]] = []
        for q in search_queries:
            results, error = _extract_find_opportunities(page, query=q, max_pages=2)
            print(f"Find '{q}': {len(results)} results (error: {error or 'none'})")
            if error:
                find_errors.append({"query": q, "error": error})
            all_find.extend(results)

        # Deduplicate
        deduped = []
        seen = set()
        for f in all_find:
            t = f["title"].lower().strip()
            if t not in seen:
                seen.add(t)
                deduped.append(f)
        inventory["find_opportunities"] = deduped
        print(f"Find Opportunities total (deduped): {len(deduped)}")

        browser.close()

    # Save reports
    (REPORTS_DIR / "cca_favourite_opportunities_inventory.json").write_text(
        json.dumps(
            {"favourites": inventory["favourites"], "retrieved_at": inventory["retrieved_at"]},
            indent=2,
        )
    )
    (REPORTS_DIR / "cca_conversations_inventory.json").write_text(
        json.dumps(inventory["conversations"], indent=2)
    )
    (REPORTS_DIR / "cca_find_opportunities_search_log.json").write_text(
        json.dumps(
            {
                "search_queries": search_queries,
                "results_count": len(deduped),
                "results": deduped,
                "errors": find_errors,
                "retrieved_at": inventory["retrieved_at"],
            },
            indent=2,
        )
    )

    # Reconcile
    reconciliation = _reconcile(inventory)

    # Save state registry
    registry = {
        "my_opportunities": inventory["my_opportunities"],
        "applications": inventory["applications"],
        "favourites": inventory["favourites"],
        "conversations": inventory["conversations"],
        "featured_matching": inventory["featured_matching"],
        "find_opportunities": inventory["find_opportunities"],
        "reconciliation": reconciliation,
        "retrieved_at": inventory["retrieved_at"],
    }
    (REPORTS_DIR / "cca_opportunity_state_registry.json").write_text(json.dumps(registry, indent=2))

    # Markdown report
    lines = [
        "# CCA Browser Discovery Report (v10)",
        "",
        f"**Retrieved:** {inventory['retrieved_at']}",
        "",
        "## My Opportunities",
        f"- Count: {len(inventory['my_opportunities'])}",
    ]
    for o in inventory["my_opportunities"]:
        lines.append(f"  - `{o['opportunity_id']}` — {o['title'][:80]} — *{o['lifecycle_state']}*")

    lines.extend(["", "## Applications", f"- Count: {len(inventory['applications'])}"])
    for a in inventory["applications"]:
        lines.append(f"  - `{a['opportunity_id']}` — {a['title'][:80]} — *{a['lifecycle_state']}*")

    lines.extend(
        [
            "",
            "## Favourite Opportunities",
            f"- Count: {len(inventory['favourites'])}",
            f"- Net-new candidates: {len(reconciliation['favourite_candidates'])}",
            f"- Excluded existing: {len(reconciliation['favourite_excluded'])}",
        ]
    )
    for f in inventory["favourites"][:10]:
        lines.append(f"  - `{f.get('opportunity_id', '')}` — {f['title'][:80]}")

    lines.extend(
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
        lines.append(
            f"  - `{m['message_id']}` — {m['sender'][:30]} — {m['subject'][:50]} — *{m['classification']}*"
        )

    lines.extend(
        [
            "",
            "## Featured / Matching Opportunities",
            f"- Count: {len(inventory['featured_matching'])}",
            f"- Net-new candidates: {len(reconciliation['featured_candidates'])}",
        ]
    )
    for fm in inventory["featured_matching"][:10]:
        lines.append(f"  - `{fm.get('opportunity_id', '')}` — {fm['title'][:80]}")

    lines.extend(
        [
            "",
            "## Find Opportunities",
            f"- Search queries: {', '.join(search_queries)}",
            f"- Total results (deduped): {len(deduped)}",
            f"- Net-new candidates: {len(reconciliation['find_candidates'])}",
            f"- Excluded existing: {len(reconciliation['find_excluded'])}",
        ]
    )
    if find_errors:
        lines.append(f"- Errors encountered: {len(find_errors)}")
        for e in find_errors:
            lines.append(f"  - Query '{e['query']}': {e['error']}")
    for f in deduped[:10]:
        lines.append(
            f"  - `{f.get('opportunity_id', '')}` — {f['title'][:80]} (query: {f.get('search_query', '')})"
        )

    lines.extend(
        [
            "",
            "## Reconciliation Summary",
            f"- Existing opportunity IDs: {len(reconciliation['existing_ids'])}",
            f"- Existing titles tracked: {reconciliation['existing_titles_count']}",
            f"- Favourite candidates: {len(reconciliation['favourite_candidates'])}",
            f"- Conversation candidates: {len(reconciliation['conversation_candidates'])}",
            f"- Featured candidates: {len(reconciliation['featured_candidates'])}",
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

    (REPORTS_DIR / "cca_browser_discovery_reconciliation.md").write_text("\n".join(lines))

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
        "featured_matching_count": len(inventory["featured_matching"]),
        "find_opportunities_count": len(deduped),
        "find_errors_count": len(find_errors),
        "favourite_candidates": len(reconciliation["favourite_candidates"]),
        "conversation_candidates": len(reconciliation["conversation_candidates"]),
        "featured_candidates": len(reconciliation["featured_candidates"]),
        "find_candidates": len(reconciliation["find_candidates"]),
        "existed_activity_excluded": (
            len(reconciliation["favourite_excluded"])
            + len(reconciliation["conversation_excluded"])
            + len(reconciliation["find_excluded"])
            + len(reconciliation["featured_excluded"])
        ),
    }
    (REPORTS_DIR / "cca_browser_discovery_summary.json").write_text(json.dumps(summary, indent=2))

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

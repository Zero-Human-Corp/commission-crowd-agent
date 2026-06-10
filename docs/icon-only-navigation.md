# Icon-Only Navigation

Version: MVP Browser Discovery v0.1.0 | Date: 2026-06-10

---

## Problem

The CommissionCrowd SPA uses icon-only navigation in several areas. Buttons, tabs, and menu items have no visible text labels — only SVG icons or FontAwesome classes. This makes automated discovery fragile because Playwright selectors that rely on `text=...` or `has-text` fail.

---

## Where Icons Appear

| UI Element | Icon / Visual Cue | Playwright Strategy |
|------------|-------------------|---------------------|
| **My Opportunities tab** | Briefcase icon (`fa-briefcase` or SVG) | `page.locator('a[href*="my-opportunities"], [data-testid="my-opp-tab"]')` |
| **Applications sub-tab** | Document icon | `page.locator('button:has-text("Applications"), [role="tab"]:nth-match(2)')` |
| **Favourites heart** | Heart icon (`fa-heart`) | `page.locator('a[href*="favourites"], .fa-heart').first` |
| **Messages envelope** | Envelope icon (`fa-envelope`) | `page.locator('a[href*="messages"], .fa-envelope').first` |
| **Find Opportunities search** | Magnifying glass | `page.locator('input[placeholder*="search" i], input[type="search"]')` |
| **Close modal** | `×` or `fa-times` | `page.locator('button:has-text("close" i), .modal-close, .fa-times').first` |
| **Pagination "Next"** | Chevron right | `page.locator('text=Next, button:has-text("Next"), [aria-label="Next"]').first` |

---

## Recommended Selector Hierarchy

When navigating icon-only elements, use this fallback order:

1. **Attribute selector** (`href`, `data-testid`, `aria-label`) — most stable
2. **CSS class** (`fa-*`, `.icon-*`) — stable unless site updates icon library
3. **nth-match / structural** (`nth-match(2)`, `first`, `last`) — brittle but usable
4. **Visual OCR** — last resort; use Playwright `screenshot` + external OCR only if all above fail

---

## Example: Selecting the Applications Tab

```python
# Strategy 1: href attribute
apps_tab = page.locator('a[href*="applications"], a[href*="my-opportunities"]').nth(1)

# Strategy 2: role + index
apps_tab = page.locator('[role="tab"]').nth(1)

# Strategy 3: icon class near text container
apps_tab = page.locator('.tab-item:has(.fa-file)')

# Click with retry
for attempt in range(3):
    try:
        apps_tab.click(timeout=5000)
        break
    except Exception:
        page.wait_for_timeout(500)
```

---

## Handling Missing Text in Tables

Some table cells contain only icons (e.g., status indicators). Extract text by:

1. Reading `title` or `aria-label` attributes on the icon element
2. Mapping icon class to meaning (e.g., `fa-check-circle` → `approved`)
3. Reading the parent row's `data-status` attribute if present

```python
cells = row.locator("td").all_inner_texts()
# If cell text is empty, try aria-label
status_icon = row.locator("td .status-icon")
status = status_icon.get_attribute("aria-label") or status_icon.get_attribute("title") or ""
```

---

## Known SPA Quirks

- **404 on direct URL load:** Navigating to `/app/#/agent/my-opportunities` sometimes returns a 404 shell. Fix: load the SPA root (`/app/`) first, then click the navigation icon.
- **Modal overlays:** Clicking a row may open a detail modal that blocks the table. Always close modals with the `×` / `.fa-times` button before reading the next page.
- **Infinite scroll vs pagination:** Find Opportunities uses pagination; Messages may use infinite scroll. Detect by checking for both `Next` button and scroll height changes.

---

## Maintenance Notes

If CommissionCrowd updates their UI:
1. Re-run the browser discovery script with `--debug-screenshots`.
2. Inspect failing selectors in the screenshot.
3. Update the locator strategy in `scripts/browser_discovery_v6.py` (or latest version).
4. Add a new entry to this doc if a previously unmapped icon appears.

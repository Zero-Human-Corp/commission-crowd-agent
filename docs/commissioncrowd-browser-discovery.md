# CommissionCrowd Browser Discovery

Version: MVP Browser Discovery v0.1.0 | Date: 2026-06-10  
**Status:** `MVP_RECOVERED` — 20 net-new Find candidates extracted after pipeline defect fix.

---

## What Browser Discovery Does

The browser discovery module logs into CommissionCrowd as the operator and navigates the SPA (Single Page Application) to extract structured data from authenticated pages that are not available via the public API alone.

### Data Sources Scraped

| Source | Page | What Is Extracted |
|--------|------|-------------------|
| **My Opportunities** | `/app/#/agent/my-opportunities` | Opportunity IDs, titles, lifecycle states (active, paused, application_submitted, etc.) |
| **Applications** | `/app/#/agent/my-opportunities` (applications tab) | IDs of opportunities the operator has already applied to |
| **Messages / Conversations** | `/app/#/agent/messages` | Message threads, linked opportunity IDs, invitation classifications |
| **Favourite Opportunities** | `/app/#/agent/favourites` | Favourited opportunity IDs and metadata |
| **Find Opportunities** | `/app/#/opportunities/find` | Search results for new opportunities |

All extracted data is saved as JSON in `/home/ubuntu/hermes-control/reports/`.

---

## Data Flow

```
Browser SPA pages
       ↓
   Playwright extraction
       ↓
   JSON inventory files
       ↓
   reconcile_inventory.py
       ↓
   OpportunityStateRegistry (precedence rules)
       ↓
   Net-new candidates list
```

---

## Precedence Rules (Highest → Lowest)

When the same opportunity appears in multiple sources, the registry resolves conflicts using this precedence:

1. **My Opportunities** (authenticated account state) — highest precedence. Never overridden by any other source.
2. **Explicit platform invitation** linked to an opportunity.
3. **Favourite Opportunities** (authenticated account state).
4. **Find Opportunities** (search results).
5. **Existing CRM / approval history** (Google Sheets data).
6. **CommissionCrowd API** — lowest precedence; enriches but never overrides account state.

### Consequences

- If an opportunity is in **My Opportunities** with status `active`, a Find result for the same ID will **not** change its lifecycle state.
- If an opportunity is in **Applications** with status `application_submitted`, it is **protected** and cannot receive a new `apply_to_principal` approval.
- API data can fill in missing `commission_text` or `territory`, but it cannot overwrite `title` or `lifecycle_state` already set by My Opportunities.

---

## Garbage Filtering

Find Opportunities search results occasionally return error pages or SPA fragments instead of real listings. The reconciliation script filters these out:

| Filter | Rule |
|--------|------|
| Missing `opportunity_id` | Skipped entirely (not trackable) |
| Title is `"close"` or empty | Treated as garbage modal/SPA fragment |
| `full_text` contains `"There were errors"` | Treated as error page result |
| ID exists in **protected set** (My Opp, Apps, Favs) | Skipped (already known) |
| ID already in CRM | Skipped (already tracked) |

**Recovery run result (2026-06-10):** 0 garbage results, 20 real net-new Find candidates, 40 Featured/Matching candidates, 6 protected IDs.

---

## Output Files

| File | Description |
|------|-------------|
| `cca_opportunity_state_registry.json` | Unified browser inventory (all sources) |
| `cca_browser_discovery_summary.json` | Counts and timestamps |
| `cca_favourite_opportunities_inventory.json` | Favourites only (legacy fallback) |
| `cca_conversations_inventory.json` | Messages only (legacy fallback) |
| `cca_find_opportunities_search_log.json` | Find search results (legacy fallback) |

---

## Pipeline Fixes (v6 Recovery)

### Atomic-Write Pattern (`_atomic_write_json`)

All JSON report files are now written atomically with timestamped backups of any existing file. This prevents a partially-failed or garbage run from silently overwriting a previous good run.

```python
def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    if path.exists():
        backup = path.with_suffix(f".json.backup-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}")
        backup.write_bytes(path.read_bytes())
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    tmp.replace(path)
```

Backups appear as `cca_opportunity_state_registry.json.backup-20260610-114530` in the reports directory. If a run produces garbage, the operator can restore the prior backup manually.

### Single-Navigation Pattern

The v11 and earlier discovery scripts called `_navigate_to_find_opportunities()` (sidebar click) for **every search query**. Repeated sidebar clicks caused:
- Viewport-scrolled buttons that Playwright could not click
- Ember.js re-initialising the search route, occasionally returning a 404 modal
- Silent overwrites of prior query results

The v6 recovery fix separates navigation from extraction:

```python
# First query only
call _extract_find_opportunities(page, query="software", navigate=True)
# Subsequent queries (if any) reuse the settled page state
call _extract_find_opportunities(page, query="AI", navigate=False)
```

This preserves authentication state and avoids the repeated click → reset → error loop.

### JS Click Fallback (`_js_click`)

When Playwright’s native `click()` fails because a button has scrolled out of the viewport, the script falls back to a JavaScript click:

```python
def _js_click(page, selector: str) -> bool:
    return page.evaluate(
        f"""() => {{
            const el = document.querySelector("{selector}");
            if (el) {{ el.click(); return true; }}
            return false;
        }}"""
    )
```

Used for the orange **Search** button (`button.carrot.stretch`) when the Find Opportunities panel is below the fold.

### Garbage-Filtering Rules

Find Opportunities search results occasionally return error pages, SPA fragments, or modal UI captured as pseudo-cards. The reconciliation script filters these out:

| Filter | Rule |
|--------|------|
| Missing `opportunity_id` | Skipped entirely (not trackable) |
| Title is `"close"` or empty | Treated as garbage modal/SPA fragment |
| `full_text` contains `"There were errors"` | Treated as error page result |
| ID exists in **protected set** (My Opp, Apps, Favs) | Skipped (already known) |
| ID already in CRM | Skipped (already tracked) |

**Historical context:** Earlier runs (v6–v10) produced 0 Find candidates because the SPA served an error modal with text:
> "Sorry, the server is not responding to that request. Either there's something wrong with the request or there's something wrong with the server. [Code: 404 NOT FOUND]"

The garbage filter now drops these entries before reconciliation.

### Pipeline Defect Root Cause

| Symptom | Root Cause |
|---------|-----------|
| 0 Find results across 8 queries | Repeated sidebar click reset Ember.js SPA state, causing viewport timeout → 404 modal |
| Silent overwrite of good results | No atomic writes; each query overwrote the previous JSON file |
| `title="close"` in results | Generic card detector matched the dismiss button of the error modal |

### Current Recovery Approach

The working recovery uses a **single-query, JS-only extraction** after a fresh login:

1. Log in via `page.goto("/login")`
2. Navigate once to `#/opportunities/search` via `window.location.hash`
3. Settle for 7 s
4. Fill the search field with `"software"` (only query used in recovery)
5. Trigger search via `_js_click` fallback
6. Extract cards with `document.querySelectorAll('.search-results .card')`
7. Write atomically with `_atomic_write_json`

**Result:** 20 real Find Opportunities extracted, 0 garbage entries, 6 protected IDs, 20 net-new candidates.

---

## SPA Navigation Notes

CommissionCrowd is an Ember.js SPA. Direct page loads sometimes return 404 or partial HTML. The discovery script:

1. Navigates via `page.goto()` with `wait_until="domcontentloaded"`
2. Uses `window.location.hash = ...` for in-app navigation (no reloads)
3. Waits for known DOM selectors (tables, card lists)
4. Retries with exponential backoff on timeout
5. Falls back to reading injected JS if DOM is incomplete
6. Uses `_js_click` when Playwright click fails on viewport-scrolled buttons

See `docs/icon-only-navigation.md` for details on navigating when UI elements lack text labels.

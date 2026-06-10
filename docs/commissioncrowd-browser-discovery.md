# CommissionCrowd Browser Discovery

Version: MVP Browser Discovery v0.1.0 | Date: 2026-06-10

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

**Current run result:** 1 garbage result found, 0 real net-new candidates after filtering.

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

## SPA Navigation Notes

CommissionCrowd is a React/Vue SPA. Direct page loads sometimes return 404 or partial HTML. The discovery script:

1. Navigates via `page.goto()` with `wait_until="domcontentloaded"`
2. Waits for known DOM selectors (tables, card lists)
3. Retries with exponential backoff on timeout
4. Falls back to reading `window.__INITIAL_STATE__` or injected JS if DOM is incomplete

See `docs/icon-only-navigation.md` for details on navigating when UI elements lack text labels.

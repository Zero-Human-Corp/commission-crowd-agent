# Opportunity Lifecycle

Version: MVP Browser Discovery v0.1.0 | Date: 2026-06-10

---

## Lifecycle States

| State | Meaning | Source of Truth |
|-------|---------|-----------------|
| `discovered` | Seen in Find Opportunities or API, no operator action yet | Find / API |
| `invited` | Platform sent (or received) an invitation linked to this opportunity | Messages |
| `favourited` | Operator clicked favourite, but has not applied | Favourites |
| `under_review` | Operator or system is evaluating fit | Pipeline scoring |
| `application_draft_pending` | Draft application created, awaiting operator review | Pipeline |
| `application_approved` | Operator approved the application-to-principal | Approvals tab |
| `application_submitted` | Application sent to the vendor/principal | Manual action (not automated) |
| `application_rejected` | Vendor declined the application | Vendor response |
| `principal_accepted` | Vendor accepted; onboarding begins | Vendor response |
| `active` | Operator is actively representing this principal | My Opportunities |
| `paused` | Relationship on hold | My Opportunities |
| `closed` | Relationship ended | My Opportunities |
| `withdrawn` | Operator withdrew application | My Opportunities |
| `expired` | Opportunity listing expired | Platform / API |
| `unknown` | No state information available | Default |

---

## Terminal States

Terminal states are **end-of-line** — no further pipeline action is permitted.

| Terminal State | Why It's Terminal |
|----------------|-------------------|
| `application_rejected` | Vendor said no; re-applying is not allowed without new context |
| `closed` | Relationship ended |
| `withdrawn` | Operator chose to exit |
| `expired` | Listing no longer exists |
| `active` | Already representing the vendor |
| `principal_accepted` | Vendor accepted; onboarding in progress |
| `application_submitted` | Application already sent; awaiting vendor response |
| `application_approved` | Operator approved but not yet submitted (still safe to submit) |

**Note:** `application_approved` is technically a pre-submission state, but it is classified as terminal for the *apply_to_principal* approval gate because the approval itself has already been granted — the only remaining step is manual submission.

---

## State Transitions (Allowed)

```
discovered
    ↓ (operator reviews + scores)
under_review
    ↓ (score passes threshold)
application_draft_pending
    ↓ (operator approves)
application_approved
    ↓ (MANUAL — operator submits on CommissionCrowd site)
application_submitted
    ↓ (vendor responds)
principal_accepted  →  active
    or
application_rejected / closed / withdrawn / expired
```

**No reverse transitions.** Once `application_submitted`, it cannot return to `application_draft_pending`. If the vendor rejects, the opportunity moves to `application_rejected` and stays there.

---

## Source Precedence

If multiple sources report different states for the same opportunity, the registry uses this precedence:

1. **My Opportunities** — always wins. If the platform says `active`, the opportunity is `active`.
2. **Applications** — if in My Opportunities applications list, state is `application_submitted`.
3. **Messages / Invitations** — if an invitation exists, minimum state is `invited`.
4. **Favourites** — if favourited and no higher-precedence source, state is `favourited`.
5. **Find / API** — only sets `discovered` if no other source has claimed the opportunity.

---

## Registry Conflicts

When reconciliation detects conflicting sources, it flags the record:

| Conflict Flag | Meaning |
|---------------|---------|
| `my_opportunities_vs_find_opportunities` | Same ID appears in My Opp and Find results (Find is stale / rediscovered) |
| `active_but_marked_eligible` | Data bug — active record somehow passed eligibility check |

Conflicts set `requires_operator_review = True`.

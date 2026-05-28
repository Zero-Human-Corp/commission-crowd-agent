# Website Copy Update Plan — Syntaxis Labs

**Status:** Draft — for operator review  
**Date:** 2026-05-29  
**Constraint:** Do not publish. Do not create live pages. This is a planning document only.

---

## 1. Guiding Principle

The public website (`sites/syntaxis-labs/`) should **stay simple and commercial**. Visitors are vendors evaluating a sales partner. Over-explaining the HoldCo structure adds cognitive load without conversion value.

**The rule:**
- **Homepage and primary pages** — present Syntaxis Labs as the brand.
- **Footer / legal micro-copy only** — mention the HoldCo structure.
- **No separate HoldCo landing page on the main nav.**

---

## 2. Proposed Copy Changes (Per Page)

### `index.html` — Homepage

**Current title:** `Syntaxis Labs — Independent B2B Commission-Only Sales Partner`

**Proposed change:** Keep title. Add one line to the hero subtitle or footer.

**Hero subtitle (keep current):**
> Commission-only. Global reach. SaaS, AI, automation, and business services.

**Footer addition (new — one line):**
> Syntaxis Labs is the operating name of a holding company. [Learn more]

The "[Learn more]" link may point to `#` (placeholder) or a not-yet-created hidden page. It is **not linked from the nav.**

### `commission-only-sales.html` — How It Works

**No changes needed.** This page explains the model. The model belongs to Syntaxis Commission Partners, which is the unit the customer (vendor) is contracting with. The vendor does not need to know the HoldCo name.

### `vendor-partnership.html` — For Vendors

**No changes needed.** Same reasoning as above.

### `opportunity-preferences.html` — Opportunities

**No changes needed.** This is operator-facing preference data.

### `commissioncrowd-profile.html` — CommissionCrowd Profile

**No changes needed.** This is platform-specific positioning.

### `contact.html` — Contact

**Proposed minor addition:**

**Current:**
> © 2026 Syntaxis Labs. Independent commission-only B2B sales partnership.

**Proposed:**
> © 2026 Syntaxis Labs. Part of Syntaxis Labs HoldCo. Independent commission-only B2B sales partnership.

This signals legitimacy without overcomplicating.

---

## 3. What NOT to Add

| Proposal | Rationale for Rejection |
|----------|------------------------|
| Separate "HoldCo" page in nav | Adds friction. Vendors want to know what you do for *them*, not your org chart. |
| Detailed org chart on public site | Exposes unnecessary internal structure. Not a conversion asset. |
| "Zero Human Corp" branding on public pages | Confuses the B2B sales message. Zero Human Corp is autonomous infrastructure — not a customer-facing sales brand. |
| "Human-in-the-Loop Ventures" branding on public pages | Too jargony. Sounds like a VC fund, not a sales partner. |
| Separate sub-brand websites for each unit | Not needed until a unit has its own go-to-market independent of Syntaxis Labs. |

---

## 4. Future-Proofing

When a business unit reaches sufficient scale to warrant its own brand website:

| Unit | Trigger for Separate Site | Suggested Domain Strategy |
|------|---------------------------|---------------------------|
| Syntaxis Commission Partners | Already served by `sites/syntaxis-labs/` | Keep as-is |
| Syntaxis Sales Desk | Spin out into separate agency offering | `sales.syntaxislabs.com` or `syntaxissales.com` |
| Syntaxis Digital Products | Launch first paid SaaS/micro-product | `products.syntaxislabs.com` |
| Global Oval Analytics | Already has own brand identity | `globaloval.com` (future independent domain) |
| ZHC Publishing | First public product launch | `publish.zerohumancorp.com` or `zerohuman.press` |

**Until these triggers are met, all units point to `syntaxis-labs.com` or their existing platform presence.**

---

## 5. Implementation Checklist (Post-Approval)

- [ ] Add footer micro-copy to `index.html`
- [ ] Add footer micro-copy to `contact.html`
- [ ] Create a hidden/not-linked `holdco.html` page (optional) with the full org chart for internal reference or due-diligence sharing
- [ ] Update `sites/syntaxis-labs/README.md` with this plan
- [ ] Do NOT create nav links to any HoldCo page
- [ ] Do NOT publish until operator explicitly approves a separate publish mission

---

## 6. Visual Treatment Recommendation

If a HoldCo micro-reference is added to the footer, keep it visually subordinate:

```css
.holdco-note {
  font-size: 0.75rem;
  color: var(--text-muted, #6b7280);
  margin-top: 0.5rem;
}
```

This is smaller than the copyright line and does not compete with primary CTAs.

---

*This plan is produced under the holdco-architecture mission. No website changes have been made. No pages published. Awaiting operator approval.*

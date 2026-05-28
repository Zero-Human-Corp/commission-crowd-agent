# Syntaxis Labs HoldCo Architecture

**Version:** 1.0  
**Status:** Draft — for operator review  
**Date:** 2026-05-29  
**Operator:** Gopolang Makokwe / Syntaxis Labs  

---

## 1. The Problem

Zero-Human-Corp (the GitHub organization) currently hosts two distinct kinds of projects:

- **Autonomous, zero-human businesses** (agent swarms, automated content pipelines, autonomous analytics) that run 24/7 with minimal operator intervention.
- **Human-operated ventures** (sales partnerships, digital products, consulting) that require active operator judgment, approval gates, and direct customer relationships.

These two classes have different governance models, risk profiles, and brand promises. Conflating them under a single org name creates ambiguity for vendors, partners, and operators.

**Syntaxis Labs** emerges as the **Holding Company** that makes this structure intentional and legible.

---

## 2. The Structure

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Syntaxis Labs                                 │
│                    (HoldCo — Holding Company)                        │
│                        Operator: Gopolang Makokwe                    │
└─────────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┴───────────────────┐
          │                                       │
    ┌──────────────┐                    ┌──────────────────────────┐
    │ Zero Human   │                    │ Human-in-the-Loop          │
    │ Corp         │                    │ Ventures                   │
    │ (Autonomous) │                    │ (Human Approved)           │
    └──────────────┘                    └──────────────────────────┘
          │                                       │
    ┌─────┴─────┬──────────┬────────────┐  ┌────┴────┬──────────┬──────────┬─────────────┐
    │ ZHC Search│ ZHC      │ ZHC        │  │ Syntaxis│ Syntaxis │ Syntaxis │ Global Oval │
    │           │ Ventures │ Publishing │  │ Commission│ Sales  │ Digital  │ Analytics   │
    │           │          │            │  │ Partners│ Desk     │ Products │             │
    │           │          │ ZHC Infra  │  │         │          │          │             │
    │           │          │            │  │         │          │          │             │
    └───────────┴──────────┴────────────┘  └─────────┴──────────┴──────────┴─────────────┘
```

---

## 3. Arms at a Glance

| Arm | Tagline | Governance Model | Approval Gating |
|-----|---------|----------------|----------------|
| **Zero Human Corp** | Autonomous, agentic systems that run without human intervention. | Policy-driven control plane; approval workflows encoded in code; cost guards; audit trail. | No human approval required for day-to-day operation. Strategic direction via Telegram. |
| **Human-in-the-Loop Ventures** | Human-operated partnerships and products where operator judgment is the core value. | Operator approval required for all external-facing actions: login, apply, submit, send, spend, approve_status_change. | Mandatory approval gates for every customer-facing action. |

---

## 4. Business Units — Zero Human Corp (Autonomous)

| Unit | Purpose | Current Repositories |
|------|---------|---------------------|
| **ZHC Search** | Autonomous research and data intelligence. AI-driven lead discovery, opportunity scoring, and market intel. | `zero-human-corp` (umbrella), shared research agents |
| **ZHC Ventures** | Autonomous project incubation and portfolio management. Spins up, monitors, and sunsets agent-run businesses. | `zero-human-corp` |
| **ZHC Publishing** | Autonomous content production pipelines — STEM books, technical documentation, blog series. | `applied-robotics-math` (parent), `applied-robotics-math-3d-transformations`, `applied-robotics-math-factory`, `applied-robotics-math-linear-algebra`, `applied-robotics-math-path-planning`, `applied-robotics-math-sensor-probability` |
| **ZHC Infrastructure** | Control plane, orchestration, shared tools, and platform engineering. The glue that makes the other units autonomous. | `zero-human-corp` (umbrella repo) |

---

## 5. Business Units — Human-in-the-Loop Ventures (Operator-Approved)

| Unit | Purpose | Current Repositories |
|------|---------|---------------------|
| **Syntaxis Commission Partners** | Commission-only sales representation for B2B vendors. Sources, qualifies, and introduces prospects. Revenue: commission on closed deals. | `commission-crowd-agent` |
| **Syntaxis Sales Desk** | Human-operated sales execution — appointment setting, demos, pipeline development, handoff. Revenue: performance fees / commission. | (operations within `commission-crowd-agent` presently; may split if/when scale demands) |
| **Syntaxis Digital Products** | Human-designed and -approved digital products, tools, and SaaS micro-products sold to end customers. | (future; may reuse ZHC Publishing outputs under HITL branding) |
| **Global Oval Analytics** | Autonomous +EV sports analytics platform with gated human oversight on capital-at-risk decisions. | `global-oval-analytics` |

**Rationale for renaming:**
- Global Oval Analytics retains its brand name because it operates as a standalone product/brand with its own market identity. It is classified under **Human-in-the-Loop Ventures** because picks and capital-at-risk decisions require operator approval (gated distribution through Whop + Discord).

---

## 6. Shared Services

These live under the HoldCo and serve both arms:

| Service | Function | Status |
|---------|----------|--------|
| **Hermes Control Plane** | Agent orchestration, Supervisor Relay, model routing, approval gates. | Active (`/home/ubuntu/hermes-control/`) |
| **Shared Tools** | Graphify, AgentOS, Code Review Graph — used across all business units. | Active (`/home/ubuntu/shared-tools/`) |
| **gstack** | AI engineering workflow toolkit — skills, benchmarks, browser automation, QA. | Active (`/home/ubuntu/gstack/`) |
| **Telegram Notifier** | Cross-unit alerting and operator notifications. | Active |
| **Google Sheets CRM** | Current data layer — commission pipeline, approvals, lead tracking. | Active |

**Shared services are NOT business units.** They are horizontal infrastructure provided by the HoldCo.

---

## 7. GitHub Repository Mapping

| Repository | GitHub Path | Business Unit | Arm | Rename Required? |
|------------|------------|---------------|-----|-----------------|
| `commission-crowd-agent` | `Zero-Human-Corp/commission-crowd-agent` | **Syntaxis Commission Partners** | Human-in-the-Loop | No — keep name to preserve history; add label/tag |
| `global-oval-analytics` | `Zero-Human-Corp/global-oval-analytics` | **Global Oval Analytics** | Human-in-the-Loop | No — brand identity is market-facing |
| `applied-robotics-math` | `Zero-Human-Corp/applied-robotics-math` | **ZHC Publishing** | Zero Human Corp | No — add label/tag |
| `applied-robotics-math-3d-transformations` | `Zero-Human-Corp/applied-robotics-math-3d-transformations` | **ZHC Publishing** | Zero Human Corp | No |
| `applied-robotics-math-factory` | `Zero-Human-Corp/applied-robotics-math-factory` | **ZHC Publishing** | Zero Human Corp | No |
| `applied-robotics-math-linear-algebra` | `Zero-Human-Corp/applied-robotics-math-linear-algebra` | **ZHC Publishing** | Zero Human Corp | No |
| `applied-robotics-math-path-planning` | `Zero-Human-Corp/applied-robotics-math-path-planning` | **ZHC Publishing** | Zero Human Corp | No |
| `applied-robotics-math-sensor-probability` | `Zero-Human-Corp/applied-robotics-math-sensor-probability` | **ZHC Publishing** | Zero Human Corp | No |
| `zero-human-corp` | `Zero-Human-Corp/zero-human-corp` | **ZHC Infrastructure / Umbrella** | Zero Human Corp | No — this IS the ZHC umbrella |
| **external: `agent-os`** | `buildermethods/agent-os` | **Shared Tool** | HoldCo (shared) | No — external dependency |
| **external: `graphify`** | `safishamsi/graphify` | **Shared Tool** | HoldCo (shared) | No — external dependency |
| **external: `code-review-graph`** | `tirth8205/code-review-graph` | **Shared Tool** | HoldCo (shared) | No — external dependency |
| **external: `hermes-workspace`** | `outsourc-e/hermes-workspace` | **Shared Tool** | HoldCo (shared) | No — external dependency |
| **external: `gstack`** | `garrytan/gstack` | **Shared Tool** | HoldCo (shared) | No — external dependency |
| **external: `hermes-agent`** | `NousResearch/hermes-agent` | **Shared Tool** | HoldCo (shared) | No — external dependency |

---

## 8. Naming Decision Log

| Decision | Rationale |
|----------|-----------|
| **Zero Human Corp → ZHC as brand prefix** | Keeps the established "Zero Human" identity but shortens it to a usable three-letter prefix (ZHC) for business unit names. |
| **ZHC Search** (new name) | Replaces ambiguous "Search" concept with a clear autonomous research/inelligence unit. |
| **ZHC Ventures** (new name) | Separates the incubator/venture function from the operational businesses. |
| **ZHC Publishing** (new name) | Gives the STEM book pipeline a clear unit name. Previously scattered under "Applied Robotics Math." |
| **ZHC Infrastructure** (new name) | Makes the platform/control-plane role explicit. |
| **Syntaxis Commission Partners** (new name) | Replaces "CommissionCrowd-specific" naming with a business-unit name that works across any platform. |
| **Syntaxis Sales Desk** (new name) | Separates the execution function (appointment setting, demos) from the partnership function. Today both live in `commission-crowd-agent`. |
| **Syntaxis Digital Products** (new name) | Reserve slot for future SaaS/micro-product offerings that are human-designed but may reuse ZHC Publishing outputs. |
| **Global Oval Analytics stays as-is** | Market-facing brand with existing positioning. Do not dilute. |

---

## 9. What This Means for the Existing Estate

### Files that reference old names — inventory

| File | Current Reference | Recommended Action |
|------|---------------------|--------------------|
| `docs/supervisor-overall-goal.md` | "Syntaxis Labs acts as an independent commission-only sales partner" | Keep — this remains accurate; add an explicit arm tag (HITL) |
| `sites/syntaxis-labs/index.html` | "Syntaxis Labs — Independent B2B Commission-Only Sales Partner" | Keep for now; add a "Part of Syntaxis Labs HoldCo" micro-copy in footer (see website plan) |
| `README.md` (commission-crowd-agent) | "Commission Crowd Agent" | Update to reference the business unit name in architecture section only |
| `sites/syntaxis-labs/commissioncrowd-profile.html` | CommissionCrowd-specific branding | Keep — this is the HITL Ventures go-to-market unit |
| GitHub org name `Zero-Human-Corp` | Org name itself | **No rename.** Renaming a GitHub org breaks all forks, stars, CI webhooks, and SSH remotes. Instead, add a public org profile README that clarifies: "Zero Human Corp is the autonomous arm of Syntaxis Labs HoldCo." |

### Repositories — action summary

- **No repos will be moved.** All repos stay in `Zero-Human-Corp`.
- **No repos will be renamed.** All names remain as-is.
- **No GitHub org rename.**
- **Action required:** Add GitHub topic tags to each repo indicating its business unit:
  - `zhc-publishing`
  - `syntaxis-commission-partners`
  - `syntaxis-hitl-venture`
  - `global-oval-analytics`
  - `zhc-infrastructure`
  - `shared-tool`

---

## 10. Governance by Arm

### Zero Human Corp Governance

1. **Mission-driven:** Each unit has a written mission with success metrics. The agent swarm self-directs within those bounds.
2. **Cost guards:** Monthly compute/data spend caps per unit. Breach triggers automatic suspension.
3. **Audit trail:** Every autonomous action is logged. Operator can replay any decision tree.
4. **Operator override:** Operator retains kill-switch and strategic direction via Telegram.
5. **Human-out-of-the-loop by design:** Day-to-day operation requires no approval gates.

### Human-in-the-Loop Ventures Governance

1. **Approval-gated:** Every external-facing action (login, apply, submit, send, spend, approve_status_change) requires explicit operator approval via Google Sheet CRM.
2. **Google Sheet is source of truth:** No action is taken unless the approval is visible and current in the Sheet.
3. **Supervisor Relay review:** All review-required JSON has a human-readable Markdown twin. Supervisor identifies stale approvals and blocks superseded gates.
4. **Dry-run by default:** All commands default to `--dry-run`. Explicit `--write` or `--notify` required for real execution.
5. **No credentials committed, no secrets printed.**

---

## 11. Next Steps (Pending Operator Approval)

| Step | Status | Actor |
|------|--------|-------|
| Operator reviews this document | Pending | **Operator** |
| Approve business unit names | Pending | **Operator** |
| Approve repository-to-unit mapping | Pending | **Operator** |
| Add GitHub topic tags to repos | Blocked pending approval | Agent (on approval) |
| Update `docs/supervisor-overall-goal.md` with arm tags | Blocked pending approval | Agent (on approval) |
| Update `README.md` with business-unit references | Blocked pending approval | Agent (on approval) |
| Draft public org profile README for `Zero-Human-Corp` | Blocked pending approval | Agent (on approval) |
| Create `sites/syntaxis-labs/holdco-claimer.html` (hidden page / not linked) | Blocked pending approval | Agent (on approval) |
| Update CommissionCrowd profile language to reflect HoldCo structure | Blocked pending approval | Agent (on approval) |

**Nothing moves until you approve this document.**

---

## 12. Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.1 | 2026-05-29 | Hermes / commission-crowd-agent | Operator-approved revision. Reclassified `Zero-Human-Workflows` as dormant/reserved — private, harmless, currently unused. Not an active business-unit dependency. |
| 1.0 | 2026-05-29 | Hermes / commission-crowd-agent | Initial draft. HoldCo structure, arms, business units, repo mapping, governance. |

---

*This document is part of the Syntaxis Labs commission-crowd-agent project. All changes are committed via Supervisor Relay for review. No repositories were moved, renamed, or deleted in the creation of this document.*

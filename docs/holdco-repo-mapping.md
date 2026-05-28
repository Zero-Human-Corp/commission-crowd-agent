# Internal Repository Mapping — Syntaxis Labs HoldCo

**Version:** 1.0  
**Status:** Draft — for operator review  
**Date:** 2026-05-29  
**Scope:** Maps every known GitHub repository to its business unit and arm. No repos moved. No repos renamed.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Active / existing |
| 🏗️ | In development / scaffolding |
| 📋 | Proposed / future |
| 🚫 | No action planned |

---

## Map by Business Unit

### Zero Human Corp — ZHC Search

| Repo | GitHub Path | Local Path | Status | Action |
|------|-------------|------------|--------|--------|
| `zero-human-corp` | `Zero-Human-Corp/zero-human-corp` | None | ✅ Active | Add topic tag `zhc-search` |

### Zero Human Corp — ZHC Ventures

| Repo | GitHub Path | Local Path | Status | Action |
|------|-------------|------------|--------|--------|
| `zero-human-corp` | `Zero-Human-Corp/zero-human-corp` | None | ✅ Active | Add topic tag `zhc-ventures` |

### Zero Human Corp — ZHC Publishing

| Repo | GitHub Path | Local Path | Status | Action |
|------|-------------|------------|--------|--------|
| `applied-robotics-math` | `Zero-Human-Corp/applied-robotics-math` | `/home/ubuntu/applied-robotics-math` | ✅ Active | Add topic tag `zhc-publishing` |
| `applied-robotics-math-3d-transformations` | `Zero-Human-Corp/applied-robotics-math-3d-transformations` | `/home/ubuntu/applied-robot-robotics-math/applied-robotics-math-3d-transformations` | ✅ Active | Keep name |
| `applied-robotics-math-factory` | `Zero-Human-Corp/applied-robotics-math-factory` | `/home/ubuntu/applied-robot-robotics-math/applied-robotics-math-factory` | ✅ Active | Keep name |
| `applied-robotics-math-linear-algebra` | `Zero-Human-Corp/applied-robotics-math-linear-algebra` | `/home/ubuntu/applied-robot-robotics-math/applied-robotics-math-linear-algebra` | ✅ Active | Keep name |
| `applied-robotics-math-path-planning` | `Zero-Human-Corp/applied-robotics-math-path-planning` | `/home/ubuntu/applied-robot-robotics-math/applied-robotics-math-path-planning` | ✅ Active | Keep name |
| `applied-robotics-math-sensor-probability` | `Zero-Human-Corp/applied-robotics-math-sensor-probability` | `/home/ubuntu/applied-robot-robotics-math/applied-robotics-math-sensor-probability` | ✅ Active | Keep name |

### Zero Human Corp — ZHC Infrastructure

| Repo | GitHub Path | Local Path | Status | Action |
|------|-------------|------------|--------|--------|
| `zero-human-corp` | `Zero-Human-Corp/zero-human-corp` | None | ✅ Active | Add topic tag `zhc-infrastructure` |

---

### Human-in-the-Loop Ventures — Syntaxis Commission Partners

| Repo | GitHub Path | Local Path | Status | Action |
|------|-------------|------------|--------|--------|
| `commission-crowd-agent` | `Zero-Human-Corp/commission-crowd-agent` | `/home/ubuntu/projects/commission-crowd-agent` | ✅ Active | Add topic tag `syntaxis-commission-partners` |

### Human-in-the-Loop Ventures — Syntaxis Sales Desk

| Repo | GitHub Path | Local Path | Status | Action |
|------|-------------|------------|--------|--------|
| `commission-crowd-agent` | `Zero-Human-Corp/commission-crowd-agent` | `/home/ubuntu/projects/commission-crowd-agent` | ✅ Active | Operations co-located with Commission Partners. Add topic tag `syntaxis-sales-desk`. Split when scale demands. |

### Human-in-the-Loop Ventures — Syntaxis Digital Products

| Repo | GitHub Path | Local Path | Status | Action |
|------|-------------|------------|--------|--------|
| *(none yet)* | — | — | 📋 Proposed | Future repo to be created when first product is scoped. |

### Human-in-the-Loop Ventures — Global Oval Analytics

| Repo | GitHub Path | Local Path | Status | Action |
|------|-------------|------------|--------|--------|
| `global-oval-analytics` | `Zero-Human-Corp/global-oval-analytics` | `/home/ubuntu/global-oval-analytics` | ✅ Active | Add topic tag `global-oval-analytics` |

---

### HoldCo Shared Services (Not Business Units)

| Repo | GitHub Path | Local Path | External? | Consumers |
|------|-------------|------------|-----------|-----------|
| `gstack` | `garrytan/gstack` | `/home/ubuntu/gstack` | ✅ Yes — fork/clone | All arms |
| `agent-os` | `buildermethods/agent-os` | `/home/ubuntu/shared-tools/agent-os` | ✅ Yes | All arms |
| `graphify` | `safishamsi/graphify` | `/home/ubuntu/shared-tools/graphify` | ✅ Yes | All arms |
| `code-review-graph` | `tirth8205/code-review-graph` | `/home/ubuntu/shared-tools/code-review-graph` | ✅ Yes | All arms |
| `hermes-workspace` | `outsourc-e/hermes-workspace` | `/home/ubuntu/shared-tools/hermes-workspace` | ✅ Yes | All arms |
| `hermes-agent` | `NousResearch/hermes-agent` | `/home/ubuntu/.hermes/hermes-agent` | ✅ Yes | All arms |

---

## GitHub Org Strategy

### Why `Zero-Human-Corp` stays unchanged

| Concern | Impact if renamed |
|---------|-------------------|
| SSH remotes | All local clones break. Every developer (operator + agents) must re-clone or update remotes. |
| CI/CD webhooks | All GitHub Actions, n8n triggers, and build pipelines break until reconfigured. |
| Forks and stars | Renamed orgs lose social proof. External forks stop working. |
| GitHub Pages | `Zero-Human-Corp.github.io/*` URLs change. Any shared links break. |
| API tokens | Existing tokens scoped to `Zero-Human-Corp` may need regeneration. |
| CommissionCrowd profile | Listed GitHub org link breaks. |

**Solution:** Keep `Zero-Human-Corp` as the GitHub org. Add a public org profile README that clarifies:

> **Zero Human Corp** is the autonomous arm of **Syntaxis Labs**, a holding company operated by Gopolang Makokwe. Zero Human Corp hosts autonomous, agentic AI systems that run with minimal human intervention. For human-operated sales partnerships and services, see **Syntaxis Labs** and **Human-in-the-Loop Ventures**.

This README is created in a special `.github/profile/README.md` on the org level (not in any repo). It requires no repo moves or renames.

---

## Action Matrix (Blocked — Pending Approval)

| Action | Actor | Effort | Risk | Status |
|--------|-------|--------|------|--------|
| Add GitHub topic tags to each mapped repo | Agent (via gh CLI) | Low (batch) | Very low | ⛔ Blocked |
| Draft `.github/profile/README.md` for Zero-Human-Corp org | Agent | Low | Low | ⛔ Blocked |
| Update `commission-crowd-agent/README.md` with business-unit references | Agent | Low | Very low | ⛔ Blocked |
| Update `docs/supervisor-overall-goal.md` with arm tags | Agent | Low | Very low | ⛔ Blocked |
| Create `sites/syntaxis-labs/holdco.html` (hidden page) | Agent | Low | Very low | ⛔ Blocked |
| Update site footer micro-copy (`index.html`, `contact.html`) | Agent | Low | Very low | ⛔ Blocked |
| Update CommissionCrowd profile language | Operator | Medium | Moderate | ⛔ Blocked |

---

## Verification

All paths in this document were verified on 2026-05-29:

- `commission-crowd-agent` → `git@github.com:Zero-Human-Corp/commission-crowd-agent.git`
- `global-oval-analytics` → `git@github.com:Zero-Human-Corp/global-oval-analytics.git`
- `applied-robotics-math` (parent) → `git@github.com:Zero-Human-Corp/applied-robotics-math.git`
- All 5 sub-repos → `git@github.com:Zero-Human-Corp/applied-robotics-math-*.git`
- `zero-human-corp` → `git@github.com:Zero-Human-Corp/zero-human-corp.git`

External repos verified via `gh repo list` and direct remote checks.

---

*This document is part of the Syntaxis Labs commission-crowd-agent project. No repositories were moved or renamed in its creation.*

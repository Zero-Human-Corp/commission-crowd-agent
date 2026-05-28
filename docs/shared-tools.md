# Shared Tools Documentation

This document describes the shared tools, libraries, and external resources used across the commission-crowd-agent project.

## Overview

The project uses several categories of shared resources:

1. **Agent Infrastructure** — Runtime and workspace tools
2. **Knowledge & Analysis** — Graph generation, code review
3. **Design & UI** — Website and landing page infrastructure
4. **External Platforms** — Third-party integrations

---

## Agent Infrastructure

### Agent OS
- **Path:** `.agent-os/`
- **Purpose:** Product mission, standards, repo structure conventions
- **Files:**
  - `product/mission.md` — Project mission statement
  - `product/supervisor_overall_goal.md` — Supervisor overall goal for commission-only agency
  - `standards/code-style.md` — Code style standards
  - `standards/repo-structure.md` — Repository structure conventions

### Hermes Workspace
- **Path:** `.hermes/`
- **Purpose:** Mission reports, audit logs, project documentation
- **Active files:** 18+ mission reports covering CRM cleanup, supervisor fixes, site scaffold, profile packs

### Obsidian Vault
- **Path:** `obsidian/`
- **Purpose:** Knowledge base for decisions, templates, profiles, vendors, ICPs, playbooks
- **Status:** Sparse — needs population (currently only `00-index.md`)

---

## Knowledge & Analysis

### Graphify
- **Path:** `.graphify/`
- **Purpose:** Knowledge graph generation for repo analysis
- **Status:** Sparse — `graph_index_summary_20260526_204500.md` and `repo_tree_fallback.txt`
- **Future:** Could migrate to `shared-tools/graphify/` if operator prefers centralized layout

### Code Review Graph
- **Path:** `.code-review-graph/`
- **Purpose:** Code review knowledge graph
- **Status:** Empty shell — verify if still needed or can be removed

---

## Design & UI

### Design OS
- **Path:** `shared-tools/design-os/`
- **Source:** https://github.com/buildermethods/design-os
- **Purpose:** Design planning and UI workflow infrastructure for Syntaxis Labs websites
- **Status:** Active — vendored with provenance documentation
- **Usage:**
  - Website design review and improvement
  - Landing page planning for ICP campaigns
  - Component library for visual consistency
- **Dependencies:** Not installed yet — pending operator approval

### Syntaxis Labs Website
- **Path:** `sites/syntaxis-labs/`
- **Purpose:** Portfolio website for Syntaxis Labs commission-only sales agency
- **Pages:** 6 HTML pages + CSS
- **Status:** Active — scaffold complete, not yet published
- **Publish target:** GitHub Pages (plan prepared)

---

## External Platform Integrations

### CommissionCrowd
- **Integration:** Lead ingestion, profile management, application submission
- **Path:** `src/commission_crowd_agent/lead_ingestion.py`, `directory_extractor.py`
- **Status:** Active — RiverForest RPO opportunity in pipeline

### Google Sheets (CRM)
- **Path:** `src/commission_crowd_agent/adapters.py` (GoogleSheetsAdapter)
- **Purpose:** Source-of-truth CRM for approvals, leads, and tracking
- **Status:** Active — CRM cleaned, canonical schema enforced

### Telegram
- **Path:** `src/commission_crowd_agent/telegram_notifier.py`
- **Purpose:** Operator notifications and updates
- **Status:** Active

---

## Tools Index (Centralized)

For the canonical shared tools index, see: `shared-tools/README.md`

---

## Adding New Tools

See: `shared-tools/README.md` → "Adding a New Shared Tool"

Quick checklist:
1. Create subdirectory under `shared-tools/`
2. Clone/copy tool files
3. Remove nested `.git` directories
4. Add provenance README
5. Update this document
6. Update `shared-tools/README.md`
7. Commit with explicit paths

---

## Governance

- **No secrets** in shared tool directories
- **No auto-install** of dependencies without operator approval
- **Document provenance** (source, license, version) for every tool
- **Prefer shallow clones** to minimize repo size
- **Remove nested `.git`** to avoid submodule conflicts

---

*Last updated: 2026-05-28*  
*Project: commission-crowd-agent*  
*Operator: Syntaxis Labs*

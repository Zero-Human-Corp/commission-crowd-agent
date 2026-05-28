# Design OS — Builder Methods

**Source:** https://github.com/buildermethods/design-os  
**License:** Check `LICENSE` file in this directory (MIT or similar, per upstream)  
**Cloned:** 2026-05-28 (shallow clone, `--depth 1`)  
**Purpose:** Design planning and UI workflow infrastructure for Syntaxis Labs websites and future landing pages  
**Project:** commission-crowd-agent  
**Operator:** Syntaxis Labs

---

## What Is Design OS?

Design OS is a design planning framework and UI component system created by Builder Methods. It provides:

- **Design section templates** for structuring web pages and landing pages
- **Component libraries** for consistent UI elements
- **Product planning workflows** for design-first development
- **Export utilities** for generating design artifacts
- **Getting started guides** for new projects

For Syntaxis Labs, Design OS will serve as the **design infrastructure layer** behind the portfolio website and future landing pages — ensuring consistent visual language, component reuse, and systematic page design.

---

## Usage for Syntaxis Labs

### Immediate Use
1. **Website design review** — Use Design OS templates to review and improve `sites/syntaxis-labs/` pages
2. **Component audit** — Map current site elements to Design OS components for consistency
3. **Landing page planning** — Use product planning templates for future campaign-specific landing pages

### Future Use
- **Campaign landing pages** — Build targeted landing pages for specific ICP campaigns using Design OS components
- **Design system evolution** — As Syntaxis Labs grows, maintain a single source of truth for UI patterns
- **Multi-site consistency** — Ensure all Syntaxis Labs properties share visual language

---

## Install Notes

**Do not run `npm install` or install dependencies without operator approval.**

The current vendored copy contains:
- Static design templates and documentation (safe, no build needed)
- React/Vue component source code (requires `npm install` to build)
- Configuration files for bundlers and linters

**If the operator approves building Design OS components:**
```bash
cd shared-tools/design-os
npm install  # Requires operator approval
npm run build  # Or equivalent command
```

For now, use the **documentation and templates** without building.

---

## File Structure

```
design-os/
├── docs/                    # Design OS documentation
│   ├── getting-started.md   # Setup guide
│   ├── design-section.md    # Design section templates
│   ├── product-planning.md  # Product planning workflows
│   ├── usage.md             # Usage instructions
│   ├── export.md            # Export utilities
│   ├── requirements.md      # Requirements framework
│   └── codebase-implementation.md  # Code integration
├── .claude/                 # Claude-specific commands and skills
├── components.json          # Component registry
├── index.html               # Design OS entry point
├── public/                  # Static assets
├── package.json             # Node dependencies (not installed yet)
├── eslint.config.js         # Linting config
└── LICENSE                  # Upstream license
```

---

## Provenance

| Field | Value |
|-------|-------|
| Repository | https://github.com/buildermethods/design-os |
| Clone command | `git clone --depth 1 https://github.com/buildermethods/design-os.git .` |
| Date cloned | 2026-05-28 |
| Nested `.git` removed | Yes |
| Nested `.github` removed | Yes |
| Dependencies installed | No — pending operator approval |
| License | See `LICENSE` file (upstream) |
| Modifications | None — vendored as-is |

---

## Governance

- **No secrets** in this directory
- **No auto-build** without operator approval
- **Document any modifications** in this README
- **Update provenance** if re-cloned or updated

---

*Added to commission-crowd-agent: 2026-05-28*  
*Path: `shared-tools/design-os/`*

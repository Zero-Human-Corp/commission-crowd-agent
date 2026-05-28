# Shared Tools — commission-crowd-agent

This directory contains external tools, libraries, and shared resources used across the commission-crowd-agent project. Each tool is vendored with provenance metadata so we can track origin, version, and usage.

---

## Tools Index

| Tool | Path | Source | Purpose | Status |
|------|------|--------|---------|--------|
| **design-os** | `shared-tools/design-os/` | https://github.com/buildermethods/design-os | Design planning and UI workflow infrastructure for Syntaxis Labs websites and future landing pages | Active |
| **gstack** | *(pending)* | Operator-provided | *(to be confirmed by operator)* | Pending |
| **graphify** | `.graphify/` (root) | Graphify CLI | Knowledge graph generation for repo analysis | Active |
| **code-review-graph** | `.code-review-graph/` (root) | Code review pipeline | *(empty shell — verify if still needed)* | Inactive? |

---

## Adding a New Shared Tool

1. Create a subdirectory under `shared-tools/<tool-name>/`
2. Clone or copy the tool files
3. Remove nested `.git` directories to avoid submodule conflicts
4. Add `README.md` with provenance (source URL, commit/date, purpose, install notes)
5. Update this index
6. Update `docs/shared-tools.md`
7. Commit with explicit paths

---

## Governance

- **Do not commit secrets** inside shared tools
- **Do not auto-install dependencies** without operator approval
- **Document provenance** for every tool (source, license, version)
- **Prefer shallow clones** (`--depth 1`) to minimize repo size
- **Remove `.git` directories** from vendored tools to avoid nested repo issues

---

*Index maintained by commission-crowd-agent project.*  
*Last updated: 2026-05-28*

# ADR-001: Replace n8n as the Primary Workflow Engine with Hermes Hooks

**Status**: Accepted  
**Date**: 2026-05-26  
**Decision Maker**: Syntaxis Labs / Hermes-OCI

---

## Context

The Commission Crowd Agent MVP was originally planned around n8n (self-hosted Docker) as the primary orchestration engine for:
- Research & draft generation workflows
- Approval & sending workflows
- Error handler sub-workflows
- Telegram command routing

n8n remains running on OCI (`:5678`) but has proven to require excessive babysitting, opaque JSON workflow exports, and hard-to-test node logic.

## Decision

We will **replace n8n as the primary workflow engine** with a **Git-controlled, testable Python workflow layer** driven by **Hermes hook scripts**.

| Aspect | Before (n8n) | After (Hermes Hooks + Python CLI)
|--------|-------------|-----------------------------------|
| Orchestration | n8n workflow JSONs | `src/commission_crowd_agent/workflows/*.py` |
| Trigger | n8n Schedule / Telegram nodes | Hermes hook scripts under `scripts/hooks/` |
| Configuration | n8n Credential Store | Pydantic Settings + `.env` |
| Testing | Manual n8n runs | pytest + dry-run flags |
| Version Control | Exported JSON blobs | Source code + tests |
| Observability | n8n execution log | Hermes reports + local `data/runs/` logs |
| Approval | Google Sheets checkbox | Hermes / Telegram approval adapter |

## Consequences

### Positive
1. **Testability**: Every workflow step is a Python function with unit tests.
2. **Determinism**: No hidden n8n node state — all logic is in Git.
3. **Hermes Integration**: Workflows can be triggered, supervised, and reported via Hermes natively.
4. **Local Development**: Run `cca run-research-cycle --dry-run` without Docker.

### Negative
1. **Migration Effort**: Existing n8n workflow knowledge must be captured as code.
2. **Self-Hosting Responsibility**: We own the cron/schedule mechanism (Hermes cron or system cron).
3. **n8n Sunsetting**: The `:5678` instance becomes read-only reference.

## Migration Path
1. **Phase 1**: Document the decision (this ADR), freeze n8n changes.
2. **Phase 2**: Build Hermes hook scripts (`scripts/hooks/`) that call Python CLI.
3. **Phase 3**: Implement workflow modules (`src/workflows/`) with stub-safe adapters.
4. **Phase 4**: Run dry tests via Hermes, then live tests with operator approval.
5. **Phase 5**: Deprecate n8n workflows (kept under `docs/legacy/n8n/` for reference).

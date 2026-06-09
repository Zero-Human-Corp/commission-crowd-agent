# CCA Phase 2 Architecture — Safety & Hardening Addendum

**Date:** 2026-06-09  
**Status:** VERIFIED — 430 tests pass  
**Applies to:** commission-crowd-agent ≥ ea7f7ae

## 1. Safety Layer (`cca_guardian.py`)

New runtime safety module providing five capabilities:

| Capability | Function | Purpose |
|-----------|----------|---------|
| **Bounded Retry** | `bounded_retry()` | Exponential-backoff decorator for network ops. Max 3 attempts, 1–8s backoff. Only retries `httpx.TimeoutException`, `httpx.ConnectError`. |
| **Payload Hashing** | `hash_payload()` | SHA-256 hex digest (16 chars) of canonical JSON. Enables deduplication of identical outreach / application payloads. |
| **Idempotency Store** | `IdempotencyStore` | Bounded in-memory store (10k entries, LRU eviction). Prevents duplicate CRM writes, duplicate approvals, duplicate calendar events. |
| **Campaign Context** | `CampaignContext` | Generates `run_id` + `correlation_id` per campaign to trace a request end-to-end across service boundaries. |
| **Approval Expiry** | `check_expiry()` | Validates approvals against a TTL (default 7 days). Rejects expired or stale approval tokens so an old approval cannot be accidentally re-approved weeks later. |

### Usage Patterns

**Retry on network adapter:**
```python
@bounded_retry(
    max_attempts=3,
    backoff_base=1.0,
    backoff_max=8.0,
    retryable_exceptions=(httpx.TimeoutException, httpx.ConnectError),
)
def _request(self, method: str, path: str) -> httpx.Response: ...
```

**Idempotency on CRM add_lead:**
```python
# Dry-run dedup via cache
# Live dedup via lead_id scan in existing Sheet rows
result = self.crm.add_lead(...)
if result.get("dedup"):
    logger.info("Duplicate lead_id suppressed: %s", lead_id)
```

**Approval double-approve protection:**
```python
# Guard: reject already-approved records
# Guard: reject already-rejected records
# Guard: reject expired records (>7 days)
```

## 2. Adapter Hardening

### CommissionCrowd API Adapter (`commissioncrowd_adapter.py`)
- **Retry-only on _request()** — public methods (`list_opportunities`, `list_agents`, `get_opportunity`) inherit retry via delegation.
- **SSL verify=False** retained but documented: CommissionCrowd certificate expired 2026-06-09. Remove once renewed.
- **Response shape normalised** — `items`, `next`, `count` fields always present (with `count` defaulting to `len(items)`).
- **Dry-run reads-only** — GET endpoints still require API key. No live POST/PUT endpoint for applications exists in the adapter.

### CRM Pipeline (`crm_pipeline.py`)
- **Deduplication guard** — `add_lead()` scans existing rows by `lead_id` before appending. Returns `dedup=True` silently if duplicate.
- **Bounded transition validation** — `advance_stage()` allows only valid `OpportunityStage` transitions per the pipeline state machine. Raises `ValueError` on illegal jumps.
- **Dry-run cache with canonical headers** — `_DRY_RUN_HEADER` ensures all dry-run records carry the same schema as live Sheet rows.

### Approval Gate (`approval_gate.py`)
- **Triple guard on approve()**:
  1. Re-approve blocked (status == "approved")
  2. Reject-after-rejection blocked (status == "rejected")
  3. Expiry guard (TTL = 168 hours)
- **Readback verification** — after writing an approval, row is read back from Sheets to confirm persistence before returning to caller.
- **Fail-closed on missing Sheets adapter** — raises `RuntimeError` rather than creating invisible local-only approvals.

## 3. Configuration Hardening

### Pydantic Settings (`CcaSettings` in `config.py`)
- **Readiness properties** — each subsystem (Ollama, Telegram, Google, SMTP, CommissionCrowd) exposes a boolean `*_ready` property based on whether required fields are populated.
- **No defaults for secrets** — all API keys/tokens default to "", never to sentinel values that could be mistaken for real credentials.
- **Shared.env integration** — `SHARED_KEY_MAP` maps canonical key names to shared.env keys. `load_settings()` reads shared.env and falls through to environment variables.

## 4. Dependency Vulnerability Disclosure

GitHub Dependabot reports **27 vulnerabilities** (18 high, 9 moderate) in transitive dependencies. These are **pre-existing** and **do not block current functionality**. Remediation path:
```bash
pip install --upgrade pip
pip install --upgrade -r requirements.txt
pip install --upgrade -r requirements-dev.txt
```
After upgrade, re-run `bash scripts/dev_check.sh` to confirm no regressions.

## 5. Phase 2 Checklist (completed)

| Item | Evidence |
|------|----------|
| Retry decorator with bounded backoff | `cca_guardian.py:bouned_retry` + tests |
| HTTP adapter retries on timeout/connect | `commissioncrowd_adapter.py` `@bounded_retry` |
| Payload hashing for dedup | `cca_guardian.py:hash_payload` + tests |
| Idempotency store | `cca_guardian.py:IdempotencyStore` + tests |
| Campaign correlation IDs | `cca_guardian.py:CampaignContext` + tests |
| Approval expiry guard | `approval_gate.py` + `check_expiry` + tests |
| Re-approve / re-reject guard | `approval_gate.py:approve()` inline guards |
| CRM dedup on add_lead | `crm_pipeline.py:add_lead()` lead_id scan |
| Safe stage transitions | `crm_pipeline.py:advance_stage()` validation |
| Dry-run cache canonical schema | `crm_pipeline.py:_DRY_RUN_HEADER` |
| Tests clean (no regressions) | 430 tests pass, ruff clean, mypy clean |
| Git commit | `ea7f7ae` on master, synced to GitHub |

## 6. Files Added / Modified in Phase 2

| File | Change |
|------|--------|
| `src/commission_crowd_agent/cca_guardian.py` | **NEW** — runtime safety utilities |
| `src/commission_crowd_agent/approval_gate.py` | **MODIFIED** — expiry, re-approve, re-reject guards |
| `src/commission_crowd_agent/commissioncrowd_adapter.py` | **MODIFIED** — retry decorator, count field, ssl note |
| `src/commission_crowd_agent/crm_pipeline.py` | **MODIFIED** — dedup, idempotency_store injection |
| `tests/test_cca_guardian.py` | **NEW** — 19 tests covering all safety utilities |
| `docs/architecture.md` | **MODIFIED** — this document updated |

## 7. Operator Action Required

**None.** All Phase 2 hardening is complete and committed. The agent is now safer to run in dry-run shadow campaigns without risk of duplicate state mutation.

To proceed to Phase 3 (quality gate re-run after full commit), run:
```bash
cd /home/ubuntu/projects/commission-crowd-agent
bash scripts/dev_check.sh
```

# Local Supervisor Model Routing

The Supervisor Relay routes supervisory decisions (code review, mission validation, reasoning fallback, draft review) through **local/Hermes-routed models** instead of the OpenAI API. This eliminates API-billing, preserves network-isolation, and respects human-only approval gates for every sensitive action.

## Model Map

| Role | Model | Task type | Default temperature |
|---|---|---|---|
| Primary supervisor | `glm-5.1` | General mission & report review | `0.2` |
| Code review | `qwen3-coder-next` | Code quality & security review | `0.2` |
| Reasoning fallback | `deepseek-v3.2` | Complex reasoning, risk analysis | `0.2` |
| Draft review | `kimi-k2-thinking` | Outreach text quality & tone | `0.2` |

## Configuration

Set the following environment variables (add to `.env` or your `.env.local`):

```bash
# Mode: local, openai, or dry-run
SUPERVISOR_MODE=local

# Hermes gateway base URL (must expose an OpenAI-compatible /v1/chat/completions)
SUPERVISOR_BASE_URL=http://localhost:8642
SUPERVISOR_TIMEOUT=120

# Override models (optional)
SUPERVISOR_PRIMARY_MODEL=glm-5.1
SUPERVISOR_CODE_REVIEW_MODEL=qwen3-coder-next
SUPERVISOR_REASONING_FALLBACK_MODEL=deepseek-v3.2
SUPERVISOR_DRAFT_REVIEW_MODEL=kimi-k2-thinking
```

### Pydantic Settings integration

The relay uses `commission_crowd_agent.config.Settings` and resolves to these `supervisor_relay` fields at runtime. No OpenAI API key is required in `local` mode.

## Architecture

```
CLI / workflow runner
        |
        v
+---------------------+
| SupervisorRelay     |
| - route(task, text)|
| - json_schema_check |
+---------------------+
        |
        v
+---------------------+
| BlockedActionChecker|
| - is_blocked()      |
| - HUMAN_ONLY_VERBS  |
+---------------------+
        |
        v
+---------------------+
| httpx.Client        |
| - POST /v1/chat/... |
| - Hermes gateway    |
+---------------------+
```

## API

### Import

```python
from commission_crowd_agent.supervisor_relay import SupervisorRelay
from commission_crowd_agent.config import Settings
```

### Basic usage

```python
settings = Settings()  # reads .env (SUPERVISOR_MODE=local)
relay = SupervisorRelay(settings=settings)

# Primary check on a mission report
resp = relay.primary_check("Review this mission report:\n...")
print(resp.approved, resp.recommended_action, resp.risk_level)

# Code review
resp = relay.code_review("def foo(): pass", system="Check for unsafe eval.")
print(resp.approved, resp.reason)
```

### Task-type based routing

```python
from commission_crowd_agent.supervisor_relay import SupervisorTaskType

resp = relay.route(
    task_type=SupervisorTaskType.CODE_REVIEW,
    text="Review this Python snippet...",
)
```

### Dry-run mode

```python
relay = SupervisorRelay(settings=settings, dry_run=True)
resp = relay.primary_check("Anything")
# Returns a canned approved response; no HTTP request is sent.
```

## Human-Only Approval Gates

The relay enforces **hard blocks** on any AI-recommended action that touches the outside world or involves spending:

| Action | Blocked? | Requires human? |
|---|---|---|
| `send_email` | ✅ yes | yes |
| `send_message` | ✅ yes | yes |
| `apply` | ✅ yes | yes |
| `login` | ✅ yes | yes |
| `call_api` | ✅ yes | yes |
| `spend_money` | ✅ yes | yes |
| `approve_status_change` | ✅ yes | yes |
| `deeper_research` | ❌ no | optional |
| `review` | ❌ no | optional |
| `revise` | ❌ no | optional |
| `ok` | ❌ no | optional |

When a blocked action is detected, `SupervisorBlockedActionError` is raised with the offending action name.

## JSON Schema Validation

Every supervisor response **must** be valid JSON containing these fields:

```json
{
  "approved": true,
  "reason": "Concise explanation",
  "recommended_action": "review | revise | deeper_research | ok",
  "risk_level": "low | medium | high",
  "notes": "Optional extra context"
}
```

Non-JSON, malformed JSON, or missing required keys triggers `SupervisorResponseValidationError` immediately.

## Testing

Run the supervisor test suites:

```bash
pytest tests/test_supervisor_relay.py tests/test_supervisor_smoke.py -v
```

- `test_supervisor_relay.py` — 50 unit tests covering routing, blocks, schema, dry-run.
- `test_supervisor_smoke.py` — 7 integration-style tests with sample mission reports.

## Security Checklist

- [ ] `SUPERVISOR_MODE=local` is set (no OpenAI key).
- [ ] `SUPERVISOR_BASE_URL` points to your Hermes gateway.
- [ ] No API keys in source code or `.env.example` comments.
- [ ] `BlockedActionChecker.is_blocked()` has not been weakened.
- [ ] `SupervisorBlockedActionError` is caught in production callers.
- [ ] Supervisor responses are validated with `SupervisorResponse.from_text()` before use.

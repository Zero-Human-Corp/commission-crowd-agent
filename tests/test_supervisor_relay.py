"""Tests for the Supervisor Relay — local model routing, schema validation,
and human-only action blocking.

All external inference is mocked. No real HTTP.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from commission_crowd_agent.config import CcaSettings
from commission_crowd_agent.supervisor_relay import (
    BLOCKED_ACTION_VERBS,
    SupervisorBlockedActionError,
    SupervisorRelay,
    SupervisorResponse,
    SupervisorResponseValidationError,
    SupervisorTaskType,
    _is_blocked_action,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_available(monkeypatch) -> None:
    """Patch _check_model_available so every model appears available."""
    monkeypatch.setattr(
        "commission_crowd_agent.supervisor_relay._check_model_available",
        lambda _base_url, _model_name, **_kwargs: True,
    )


def _make_settings(**overrides: Any) -> CcaSettings:
    """Build a CcaSettings with supervisor fields populated."""
    defaults: dict[str, Any] = {
        "supervisor_mode": "local",
        "supervisor_base_url": "http://localhost:9999/v1",
        "supervisor_api_key": "",
        "supervisor_primary_model": "glm-5.1",
        "supervisor_code_review_model": "qwen3-coder-next",
        "supervisor_reasoning_fallback_model": "deepseek-v3.2",
        "supervisor_draft_review_model": "gemma3:27b-cloud",
        "supervisor_long_context_model": "nemotron-3-super:cloud",
        "supervisor_emergency_fallback_model": "kimi-k2.6:cloud",
        "supervisor_allow_fallback": False,
        "supervisor_fallback_model": "",
        "supervisor_telegram_notify": True,
        "smtp_port": 587,
        "cca_daily_volume_limit": 50,
    }
    defaults.update(overrides)
    return CcaSettings(**defaults)


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------


def test_supervisor_defaults_from_config() -> None:
    settings = _make_settings()
    assert settings.supervisor_mode == "local"
    assert settings.supervisor_primary_model == "glm-5.1"
    assert settings.supervisor_code_review_model == "qwen3-coder-next"
    assert settings.supervisor_reasoning_fallback_model == "deepseek-v3.2"
    assert settings.supervisor_draft_review_model == "gemma3:27b-cloud"
    assert settings.supervisor_long_context_model == "nemotron-3-super:cloud"
    assert settings.supervisor_emergency_fallback_model == "kimi-k2.6:cloud"
    assert settings.supervisor_base_url == "http://localhost:9999/v1"


def test_supervisor_disabled_model_map_empty() -> None:
    settings = _make_settings(supervisor_mode="disabled")
    relay = SupervisorRelay(settings=settings, dry_run=True)
    assert not relay.enabled


# ---------------------------------------------------------------------------
# SupervisorResponse JSON schema
# ---------------------------------------------------------------------------


def test_supervisor_response_from_text_plain_json() -> None:
    text = '{"approved": true, "reason": "ok"}'
    resp = SupervisorResponse.from_text(text)
    assert resp.approved is True
    assert resp.reason == "ok"
    assert resp.risk_level == "unknown"


def test_supervisor_response_from_text_with_fences() -> None:
    text = '```json\n{"approved": false, "reason": "nope"}\n```'
    resp = SupervisorResponse.from_text(text)
    assert resp.approved is False
    assert resp.reason == "nope"


def test_supervisor_response_from_text_empty_raises() -> None:
    with pytest.raises(SupervisorResponseValidationError):
        SupervisorResponse.from_text("```json\n\n```")


def test_supervisor_response_invalid_type_raises() -> None:
    with pytest.raises(ValidationError):
        SupervisorResponse.from_text('{"approved": {"no": 1}, "reason": "not sure"}')


# ---------------------------------------------------------------------------
# Human-only gate — blocked actions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        "send",
        "Send",
        "SEND",
        "send_email",
        "apply_for_partner",
        "message_operator",
        "login_to_portal",
        "api_call",
        "api_call_external",
        "spend_credit",
        "approval_status_change",
        "approval_status_change_to_approved",
    ],
)
def test_is_blocked_action_true(action: str) -> None:
    assert _is_blocked_action(action) is True


@pytest.mark.parametrize("action", ["research", "score", "noop", "", "   "])
def test_is_blocked_action_false(action: str) -> None:
    assert _is_blocked_action(action) is False


def test_blocked_action_verbs_set_content() -> None:
    assert "send" in BLOCKED_ACTION_VERBS
    assert "apply" in BLOCKED_ACTION_VERBS
    assert "message" in BLOCKED_ACTION_VERBS
    assert "login" in BLOCKED_ACTION_VERBS
    assert "api_call" in BLOCKED_ACTION_VERBS
    assert "spend" in BLOCKED_ACTION_VERBS
    assert "approval_status_change" in BLOCKED_ACTION_VERBS


# ---------------------------------------------------------------------------
# SupervisorRelay routing (mocked)
# ---------------------------------------------------------------------------


def test_relay_enabled_when_local() -> None:
    settings = _make_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    assert relay.enabled


def test_relay_disabled_when_openai() -> None:
    settings = _make_settings(supervisor_mode="openai")
    relay = SupervisorRelay(settings=settings, dry_run=True)
    assert not relay.enabled


def test_relay_disabled_when_disabled() -> None:
    settings = _make_settings(supervisor_mode="disabled")
    relay = SupervisorRelay(settings=settings, dry_run=True)
    with pytest.raises(RuntimeError, match="not enabled"):
        relay.primary_check("hello")


def test_relay_model_map_populated() -> None:
    settings = _make_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    assert relay._model_map[SupervisorTaskType.PRIMARY_SUPERVISOR] == "glm-5.1"
    assert relay._model_map[SupervisorTaskType.CODE_REVIEW] == "qwen3-coder-next"
    assert relay._model_map[SupervisorTaskType.REASONING_FALLBACK] == "deepseek-v3.2"
    assert relay._model_map[SupervisorTaskType.DRAFT_REVIEW] == "gemma3:27b-cloud"


def test_relay_safe_repr_no_secrets() -> None:
    settings = _make_settings(supervisor_api_key="sk-secret12345")
    relay = SupervisorRelay(settings=settings, dry_run=True)
    text = relay.safe_repr()
    assert "glm-5.1" in text
    assert "qwen3-coder-next" in text
    assert "deepseek-v3.2" in text
    assert "gemma3:27b-cloud" in text
    assert "local" in text
    assert "Bearer" not in text
    assert "sk-secret" not in text


def test_primary_check_dry_run() -> None:
    settings = _make_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    resp = relay.primary_check("ping")
    assert resp.approved is False
    assert "Dry-run" in resp.reason


def test_code_review_dry_run() -> None:
    settings = _make_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    resp = relay.code_review("review this function")
    assert resp.approved is False


def test_reasoning_fallback_dry_run() -> None:
    settings = _make_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    resp = relay.reasoning_fallback("explain this")
    assert resp.approved is False


def test_draft_review_dry_run() -> None:
    settings = _make_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    resp = relay.draft_review("check draft")
    assert resp.approved is False


def test_route_no_model_mapped_raises() -> None:
    settings = _make_settings(
        supervisor_primary_model="",
    )
    relay = SupervisorRelay(settings=settings, dry_run=True)
    with pytest.raises(ValueError, match="No model configured"):
        relay.primary_check("hello")


# ---------------------------------------------------------------------------
# Live routing — mocked httpx
# ---------------------------------------------------------------------------


def _mock_response(content: str) -> httpx.Response:
    req = httpx.Request("POST", "http://localhost:9999/v1/chat/completions")
    return httpx.Response(
        200,
        request=req,
        json={
            "choices": [
                {
                    "message": {
                        "content": content,
                    }
                }
            ]
        },
    )


def test_primary_routes_to_glm51(monkeypatch) -> None:
    monkeypatch.setattr(
        "commission_crowd_agent.supervisor_relay._check_model_available",
        lambda _base_url, _model_name, **_kwargs: True,
    )
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response('{"approved": true, "reason": "looks good"}')
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.primary_check("Ping.")
    assert resp.approved is True
    assert resp.reason == "looks good"

    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "glm-5.1"


def test_code_review_routes_to_qwen3_coder_next(monkeypatch) -> None:
    monkeypatch.setattr(
        "commission_crowd_agent.supervisor_relay._check_model_available",
        lambda _base_url, _model_name, **_kwargs: True,
    )
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response('{"approved": true, "reason": "clean code"}')
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    relay.code_review("review this function")
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "qwen3-coder-next"


def test_reasoning_fallback_routes_to_deepseek_v32(monkeypatch) -> None:
    monkeypatch.setattr(
        "commission_crowd_agent.supervisor_relay._check_model_available",
        lambda _base_url, _model_name, **_kwargs: True,
    )
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response('{"approved": true, "reason": "solid logic"}')
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    relay.reasoning_fallback("is this sound?")
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "deepseek-v3.2"


def test_draft_review_routes_to_kimi_k2_thinking(monkeypatch) -> None:
    monkeypatch.setattr(
        "commission_crowd_agent.supervisor_relay._check_model_available",
        lambda _base_url, _model_name, **_kwargs: True,
    )
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response('{"approved": true, "reason": "well written"}')
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    relay.draft_review("evaluate outreach draft")
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "gemma3:27b-cloud"


# ---------------------------------------------------------------------------
# Blocked action enforcement — hard gate
# ---------------------------------------------------------------------------


def test_blocked_action_raises_on_send(monkeypatch) -> None:
    _patch_available(monkeypatch)
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "sure", "recommended_action": "send_email"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    with pytest.raises(SupervisorBlockedActionError, match="Blocked action"):
        relay.primary_check("Can I send this?")


def test_blocked_action_raises_on_apply(monkeypatch) -> None:
    _patch_available(monkeypatch)
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "sure", "recommended_action": "apply_for_partner"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    with pytest.raises(SupervisorBlockedActionError, match="apply"):
        relay.primary_check("Can I apply?")


def test_blocked_action_raises_on_login(monkeypatch) -> None:
    _patch_available(monkeypatch)
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "sure", "recommended_action": "login"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    with pytest.raises(SupervisorBlockedActionError, match="login"):
        relay.primary_check("Can I log in?")


def test_blocked_action_raises_on_api_call(monkeypatch) -> None:
    _patch_available(monkeypatch)
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "sure", "recommended_action": "api_call_external"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    with pytest.raises(SupervisorBlockedActionError, match="api_call"):
        relay.primary_check("Call the API.")


def test_blocked_action_raises_on_spend(monkeypatch) -> None:
    _patch_available(monkeypatch)
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "sure", "recommended_action": "spend_credit"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    with pytest.raises(SupervisorBlockedActionError, match="spend"):
        relay.primary_check("Spend credit.")


def test_blocked_action_raises_on_approval_status_change(monkeypatch) -> None:
    _patch_available(monkeypatch)
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "sure", "recommended_action": "approval_status_change"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    with pytest.raises(SupervisorBlockedActionError, match="approval_status_change"):
        relay.primary_check("Change status.")


def test_allowed_action_does_not_raise(monkeypatch) -> None:
    _patch_available(monkeypatch)
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "safe", "recommended_action": "research"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.primary_check("Research this company.")
    assert resp.approved is True
    assert resp.recommended_action == "research"


# ---------------------------------------------------------------------------
# Schema validation errors on bad JSON
# ---------------------------------------------------------------------------


def test_malformed_json_raises_validation_error(monkeypatch) -> None:
    _patch_available(monkeypatch)
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response("not json at all")
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    with pytest.raises(SupervisorResponseValidationError, match="valid JSON"):
        relay.primary_check("whatever")


def test_invalid_schema_raises_validation_error(monkeypatch) -> None:
    _patch_available(monkeypatch)
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response('{"approved": "maybe", "reason": "not sure"}')
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    with pytest.raises(SupervisorResponseValidationError, match="schema validation"):
        relay.primary_check("whatever")


# ---------------------------------------------------------------------------
# check_blocked convenience
# ---------------------------------------------------------------------------


def test_check_blocked_returns_expected_dict() -> None:
    settings = _make_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    result = relay.check_blocked("send_email")
    assert result["action"] == "send_email"
    assert result["blocked"] is True
    assert "Requires operator approval" in result["block_reason"]


def test_check_blocked_allowed() -> None:
    settings = _make_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    result = relay.check_blocked("research")
    assert result["blocked"] is False
    assert result["block_reason"] == ""


# ---------------------------------------------------------------------------
# JSON schema description completeness
# ---------------------------------------------------------------------------


def test_schema_description_has_required_fields() -> None:
    from commission_crowd_agent.supervisor_relay import SUPERVISOR_SCHEMA_DESCRIPTION

    assert SUPERVISOR_SCHEMA_DESCRIPTION["type"] == "object"
    assert "approved" in SUPERVISOR_SCHEMA_DESCRIPTION["properties"]
    assert "reason" in SUPERVISOR_SCHEMA_DESCRIPTION["properties"]
    assert "recommended_action" in SUPERVISOR_SCHEMA_DESCRIPTION["properties"]
    assert "risk_level" in SUPERVISOR_SCHEMA_DESCRIPTION["properties"]
    assert "notes" in SUPERVISOR_SCHEMA_DESCRIPTION["properties"]
    assert SUPERVISOR_SCHEMA_DESCRIPTION["required"] == ["approved", "reason"]


# ---------------------------------------------------------------------------
# Model independence — self-review guard
# ---------------------------------------------------------------------------


def test_self_review_guard_triggers_on_kimi(monkeypatch) -> None:
    """When the actual reviewer is from the same family as the Hermes worker,
    review_independence should be 'low' and human_approval_required True."""
    monkeypatch.setenv("HERMES_ACTIVE_MODEL", "kimi-k2.6:cloud")
    monkeypatch.setattr(
        "commission_crowd_agent.supervisor_relay._check_model_available",
        lambda _base_url, _model_name, **_kwargs: True,
    )
    settings = _make_settings(
        supervisor_draft_review_model="kimi-k2.6:cloud",
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "looks good", "recommended_action": "review"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.draft_review("Review this draft.")
    assert resp.review_independence == "low"
    assert resp.human_approval_required is True
    assert "SELF-REVIEW GUARD" in resp.notes


def test_self_review_guard_does_not_trigger_on_different_family(monkeypatch) -> None:
    """When reviewer is a different model family, independence stays high."""
    monkeypatch.setenv("HERMES_ACTIVE_MODEL", "kimi-k2.6:cloud")
    monkeypatch.setattr(
        "commission_crowd_agent.supervisor_relay._check_model_available",
        lambda _base_url, _model_name, **_kwargs: True,
    )
    settings = _make_settings(
        supervisor_draft_review_model="gemma3:27b-cloud",
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "looks good", "recommended_action": "review"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.draft_review("Review this draft.")
    assert resp.review_independence == "high"
    assert resp.human_approval_required is False
    assert "SELF-REVIEW GUARD" not in resp.notes


def test_long_context_route_uses_nemotron(monkeypatch) -> None:
    """LONG_CONTEXT_REVIEW should route to nemotron-3-super:cloud."""
    monkeypatch.setattr(
        "commission_crowd_agent.supervisor_relay._check_model_available",
        lambda _base_url, _model_name, **_kwargs: True,
    )
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "context ok", "recommended_action": "review"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.long_context_review("Long context prompt." * 100)
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "nemotron-3-super:cloud"
    assert resp.approved is True


def test_draft_review_routes_to_gemma(monkeypatch) -> None:
    """DRAFT_REVIEW should route to gemma3:27b-cloud."""
    monkeypatch.setattr(
        "commission_crowd_agent.supervisor_relay._check_model_available",
        lambda _base_url, _model_name, **_kwargs: True,
    )
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_response(
        '{"approved": true, "reason": "draft ok", "recommended_action": "review"}'
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.draft_review("Draft outreach text.")
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "gemma3:27b-cloud"
    assert resp.approved is True

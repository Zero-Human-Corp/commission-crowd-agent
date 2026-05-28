"""Dry-run smoke test for Supervisor Relay using sample Hermes mission report.

No real inference. Mocks all httpx responses.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from commission_crowd_agent.supervisor_relay import (
    SupervisorBlockedActionError,
    SupervisorRelay,
    SupervisorTaskType,
)


def _make_settings(**overrides: Any) -> Any:
    from commission_crowd_agent.config import CcaSettings

    defaults: dict[str, Any] = {
        "supervisor_mode": "local",
        "supervisor_base_url": "http://localhost:9999/v1",
        "supervisor_api_key": "",
        "supervisor_primary_model": "glm-5.1",
        "supervisor_code_review_model": "qwen3-coder-next",
        "supervisor_reasoning_fallback_model": "deepseek-v3.2",
        "supervisor_draft_review_model": "kimi-k2-thinking",
        "smtp_port": 587,
        "cca_daily_volume_limit": 50,
    }
    defaults.update(overrides)
    return CcaSettings(**defaults)


SAMPLE_MISSION_REPORT = """
**Mission: ingest-operator-sources**
- Status: completed
- Client: Syntaxis Labs
- Rows written: 5
- Leads discovered: 5
- Approvals created: 5
- Errors: 0
"""


def _mock_good_response(recommended_action: str = "review") -> httpx.Response:
    req = httpx.Request("POST", "http://localhost:9999/v1/chat/completions")
    raw_json = (
        f'{{"approved": true, "reason": "mission report looks clean", '
        f'"recommended_action": "{recommended_action}", "risk_level": "low", "notes": ""}}'
    )
    return httpx.Response(
        200,
        request=req,
        json={
            "choices": [
                {
                    "message": {
                        "content": raw_json,
                    }
                }
            ]
        },
    )


def test_smoke_primary_supervisor_on_mission_report() -> None:
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_good_response("review")
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.primary_check(
        f"Review this mission report:\n{SAMPLE_MISSION_REPORT}",
        system="You are a cautious supervisor. Respond strictly in JSON.",
    )
    assert resp.approved is True
    assert resp.risk_level == "low"
    assert resp.recommended_action == "review"
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "glm-5.1"
    messages = payload["messages"]
    assert messages[0]["role"] == "system"
    assert "cautious supervisor" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "mission report" in messages[1]["content"]


def test_smoke_code_review_on_mission_script() -> None:
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_good_response("review")
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.code_review(
        "Review this Python snippet:\ndef risk_score(): return 42",
        system="You review code quality.",
    )
    assert resp.approved is True
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "qwen3-coder-next"


def test_smoke_reasoning_fallback_on_risky_mission() -> None:
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_good_response("deeper_research")
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.reasoning_fallback(
        "Should we proceed with outreach to a company missing commission_signal?",
    )
    assert resp.approved is True
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "deepseek-v3.2"


def test_smoke_draft_review_on_outreach_text() -> None:
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _mock_good_response("revise")
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.draft_review(
        "Draft outreach email:\nHi there, we help with commission...",
    )
    assert resp.approved is True
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "kimi-k2-thinking"


def test_smoke_blocked_action_in_mission_report_review() -> None:
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "http://localhost:9999/v1/chat/completions"),
        json={
            "choices": [
                {
                    "message": {
                        "content": '{"approved": true, "reason": "send now", "recommended_action": "send_email"}',
                    }
                }
            ]
        },
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    with pytest.raises(SupervisorBlockedActionError, match="send_email"):
        relay.primary_check(
            f"The mission report looks good. Can we send outreach now?\n{SAMPLE_MISSION_REPORT}"
        )


def test_smoke_high_risk_detected_no_block() -> None:
    settings = _make_settings()
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "http://localhost:9999/v1/chat/completions"),
        json={
            "choices": [
                {
                    "message": {
                        "content": '{"approved": false, "reason": "missing commission_signal", "recommended_action": "deeper_research", "risk_level": "high"}',
                    }
                }
            ]
        },
    )
    relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
    resp = relay.primary_check("Should we approve this lead?")
    assert resp.approved is False
    assert resp.risk_level == "high"
    assert resp.recommended_action == "deeper_research"


def test_smoke_all_task_types_unique_models() -> None:
    settings = _make_settings()
    expected = {
        SupervisorTaskType.PRIMARY_SUPERVISOR: "glm-5.1",
        SupervisorTaskType.CODE_REVIEW: "qwen3-coder-next",
        SupervisorTaskType.REASONING_FALLBACK: "deepseek-v3.2",
        SupervisorTaskType.DRAFT_REVIEW: "kimi-k2-thinking",
    }
    for task_type, expected_model in expected.items():
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = _mock_good_response("ok")
        relay = SupervisorRelay(settings=settings, dry_run=False, client=mock_client)
        resp = relay.route(task_type, "test prompt")
        assert resp.approved is True
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["model"] == expected_model

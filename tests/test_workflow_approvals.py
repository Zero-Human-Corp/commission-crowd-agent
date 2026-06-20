"""Tests for the Telegram inline approval workflow.

Covers rich message construction, callback routing, lifecycle state migration,
registry persistence, and dry-run safety.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from commission_crowd_agent.canonical import CanonicalOpportunity
from commission_crowd_agent.state_registry import (
    LIFECYCLE_APPLICATION_APPROVED,
    LIFECYCLE_APPLICATION_DRAFT_PENDING,
    LIFECYCLE_APPLICATION_REJECTED,
    LIFECYCLE_DISCOVERED,
    OpportunityStateRecord,
    OpportunityStateRegistry,
)
from commission_crowd_agent.workflows.approvals import (
    ApprovalPack,
    _answer_callback_query,
    _extract_approval_id_from_message,
    build_approval_message,
    handle_callback_query,
    load_registry,
    migrate_lifecycle_state,
    parse_callback_data,
    save_registry,
    send_approval_request,
)

pytestmark = [pytest.mark.telegram, pytest.mark.approvals]


def test_build_approval_message_structure() -> None:
    pack = ApprovalPack(
        opportunity_id="OPP-123",
        title="Cybersecurity SaaS — North America",
        principal_name="SecureFlow Inc",
        commission_terms="20% recurring",
        target_size="$5k–$25k ACV",
        risk_level="medium",
        approval_id="A42",
    )
    msg = build_approval_message(pack)
    assert "Application Pack Awaiting Approval" in msg["text"]
    assert "Cybersecurity SaaS" in msg["text"]
    assert "20% recurring" in msg["text"]
    assert "A42" in msg["text"]
    assert "reply_markup" in msg
    keyboard = msg["reply_markup"]["inline_keyboard"][0]
    assert len(keyboard) == 2
    assert keyboard[0]["text"] == "🟢 Approve Pack"
    assert keyboard[0]["callback_data"] == "approve_OPP-123"
    assert keyboard[1]["text"] == "🔴 Reject Pack"
    assert keyboard[1]["callback_data"] == "reject_OPP-123"


def test_build_approval_message_escapes_markdown() -> None:
    pack = ApprovalPack(
        opportunity_id="OPP-124",
        title="AI *CRM* — [UK] (test)",
        commission_terms="25% on first-year",
        target_size="Not stated",
        approval_id="A43",
    )
    msg = build_approval_message(pack)
    # Asterisks and brackets should be escaped so Telegram Markdown is safe
    assert "AI \\*CRM\\*" in msg["text"]
    assert "\\[UK\\]" in msg["text"]
    assert "\\(test\\)" in msg["text"]


def test_approval_pack_from_canonical() -> None:
    opp = CanonicalOpportunity(
        source_opportunity_id="30130",
        title="Test Opportunity",
        company_name="Acme Corp",
        commission_text="15% on $10,000–$50,000",
        commission_percent=15.0,
        deal_value_usd=50000,
        territory="North America",
        data_quality_flags=["missing_contact_email"],
    )
    pack = ApprovalPack.from_canonical(opp, approval_id="A44")
    assert pack.opportunity_id == "30130"
    assert pack.title == "Test Opportunity"
    assert pack.principal_name == "Acme Corp"
    assert pack.commission_terms == "15% on $10,000–$50,000"
    assert "$50,000" in pack.target_size
    assert pack.risk_level == "medium"
    assert pack.approval_id == "A44"


@pytest.mark.asyncio
async def test_send_approval_request_dry_run() -> None:
    from commission_crowd_agent.adapters import NotifierAdapter

    notifier = NotifierAdapter(bot_token="", chat_id="", dry_run=False)
    pack = ApprovalPack(opportunity_id="OPP-1", title="T", approval_id="A1")
    result = await send_approval_request(pack, notifier, dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["sent"] is False
    assert "text" in result
    assert "reply_markup" in result


@pytest.mark.asyncio
async def test_send_approval_request_real_notifies() -> None:
    mock_notifier = MagicMock()
    mock_notifier.send_message.return_value = {"ok": True, "status": 200, "message_id": 7}
    pack = ApprovalPack(opportunity_id="OPP-2", title="T", approval_id="A2")
    result = await send_approval_request(pack, mock_notifier, dry_run=False)
    assert result == {"ok": True, "status": 200, "message_id": 7}
    call = mock_notifier.send_message.call_args
    assert call.kwargs["parse_mode"] == "Markdown"
    assert "reply_markup" in call.kwargs


def test_parse_callback_data_valid() -> None:
    assert parse_callback_data("approve_30130") == {
        "action": "approve",
        "opportunity_id": "30130",
    }
    assert parse_callback_data("reject_OPP-001") == {
        "action": "reject",
        "opportunity_id": "OPP-001",
    }


def test_parse_callback_data_invalid() -> None:
    assert parse_callback_data("garbage") is None
    assert parse_callback_data("approve_") is None
    assert parse_callback_data("unknown_123") is None


def test_migrate_lifecycle_state_success() -> None:
    registry = OpportunityStateRegistry()
    rec = OpportunityStateRecord(opportunity_id="OPP-5")
    rec.lifecycle_state = LIFECYCLE_APPLICATION_DRAFT_PENDING
    registry._records["OPP-5"] = rec

    result = migrate_lifecycle_state(
        registry,
        "OPP-5",
        LIFECYCLE_APPLICATION_APPROVED,
        from_states={LIFECYCLE_APPLICATION_DRAFT_PENDING},
    )
    assert result["ok"] is True
    assert result["previous_state"] == LIFECYCLE_APPLICATION_DRAFT_PENDING
    assert result["current_state"] == LIFECYCLE_APPLICATION_APPROVED
    updated = registry.get_by_id("OPP-5")
    assert updated is not None
    assert updated.lifecycle_state == LIFECYCLE_APPLICATION_APPROVED


def test_migrate_lifecycle_state_guard_blocks_wrong_from_state() -> None:
    registry = OpportunityStateRegistry()
    rec = OpportunityStateRecord(opportunity_id="OPP-6")
    rec.lifecycle_state = LIFECYCLE_DISCOVERED
    registry._records["OPP-6"] = rec

    result = migrate_lifecycle_state(
        registry,
        "OPP-6",
        LIFECYCLE_APPLICATION_APPROVED,
        from_states={LIFECYCLE_APPLICATION_DRAFT_PENDING},
    )
    assert result["ok"] is False
    assert "discovered" in result["error"]
    unchanged = registry.get_by_id("OPP-6")
    assert unchanged is not None
    assert unchanged.lifecycle_state == LIFECYCLE_DISCOVERED


def test_migrate_lifecycle_state_missing_opportunity() -> None:
    registry = OpportunityStateRegistry()
    result = migrate_lifecycle_state(registry, "MISSING", LIFECYCLE_APPLICATION_APPROVED)
    assert result["ok"] is False
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_handle_callback_query_approve_dry_run() -> None:
    from commission_crowd_agent.adapters import NotifierAdapter

    notifier = NotifierAdapter(bot_token="", chat_id="", dry_run=True)
    registry = OpportunityStateRegistry()
    rec = OpportunityStateRecord(opportunity_id="OPP-7")
    rec.lifecycle_state = LIFECYCLE_APPLICATION_DRAFT_PENDING
    registry._records["OPP-7"] = rec

    query = {
        "id": "cq-1",
        "data": "approve_OPP-7",
        "message": {"text": "Approval ID: `A7`"},
    }
    result = await handle_callback_query(
        query,
        notifier=notifier,
        registry=registry,
        dry_run=True,
    )
    assert result["ok"] is True
    assert result["action"] == "approve"
    assert result["ack"]["dry_run"] is True
    assert result["migration"]["current_state"] == LIFECYCLE_APPLICATION_APPROVED
    final = registry.get_by_id("OPP-7")
    assert final is not None
    assert final.lifecycle_state == LIFECYCLE_APPLICATION_APPROVED


@pytest.mark.asyncio
async def test_handle_callback_query_reject_dry_run() -> None:
    from commission_crowd_agent.adapters import NotifierAdapter

    notifier = NotifierAdapter(bot_token="", chat_id="", dry_run=True)
    registry = OpportunityStateRegistry()
    rec = OpportunityStateRecord(opportunity_id="OPP-8")
    rec.lifecycle_state = LIFECYCLE_APPLICATION_DRAFT_PENDING
    registry._records["OPP-8"] = rec

    query = {"id": "cq-2", "data": "reject_OPP-8"}
    result = await handle_callback_query(
        query,
        notifier=notifier,
        registry=registry,
        dry_run=True,
    )
    assert result["ok"] is True
    assert result["action"] == "reject"
    assert result["migration"]["current_state"] == LIFECYCLE_APPLICATION_REJECTED
    final = registry.get_by_id("OPP-8")
    assert final is not None
    assert final.lifecycle_state == LIFECYCLE_APPLICATION_REJECTED


@pytest.mark.asyncio
async def test_handle_callback_query_invalid_data() -> None:
    from commission_crowd_agent.adapters import NotifierAdapter

    notifier = NotifierAdapter(bot_token="", chat_id="", dry_run=True)
    registry = OpportunityStateRegistry()
    query = {"id": "cq-3", "data": "nonsense"}
    result = await handle_callback_query(
        query,
        notifier=notifier,
        registry=registry,
        dry_run=True,
    )
    assert result["ok"] is False
    assert "Unrecognised" in result["error"]


@pytest.mark.asyncio
async def test_handle_callback_query_calls_gate_approve() -> None:
    mock_gate = MagicMock()
    mock_gate.approve.return_value = {"ok": True, "status": "approved"}
    from commission_crowd_agent.adapters import NotifierAdapter

    notifier = NotifierAdapter(bot_token="token", chat_id="chat", dry_run=False)
    registry = OpportunityStateRegistry()
    rec = OpportunityStateRecord(opportunity_id="OPP-9")
    rec.lifecycle_state = LIFECYCLE_APPLICATION_DRAFT_PENDING
    registry._records["OPP-9"] = rec

    query = {
        "id": "cq-4",
        "data": "approve_OPP-9",
        "message": {"text": "Approval ID: `A9`"},
    }
    # Patch the network call inside _answer_callback_query so no real request is made.
    notifier._post_with_retry = MagicMock(return_value=MagicMock(  # type: ignore[method-assign]
        raise_for_status=MagicMock(),
        status_code=200,
        json=MagicMock(return_value={"ok": True}),
    ))

    result = await handle_callback_query(
        query,
        notifier=notifier,
        registry=registry,
        gate=mock_gate,
        dry_run=False,
    )
    assert result["ok"] is True
    mock_gate.approve.assert_called_once_with("A9")


def test_extract_approval_id_from_message() -> None:
    text = "Approval ID: `A123`\nChoose an action:"
    assert _extract_approval_id_from_message({"text": text}) == "A123"
    assert _extract_approval_id_from_message({"caption": text}) == "A123"
    assert _extract_approval_id_from_message({"text": "no id here"}) == ""


def test_answer_callback_query_dry_run() -> None:
    from commission_crowd_agent.adapters import NotifierAdapter

    notifier = NotifierAdapter(bot_token="", chat_id="", dry_run=True)
    result = _answer_callback_query(notifier, "cq-5", text="Done")
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["callback_query_id"] == "cq-5"


def test_registry_save_and_load_roundtrip(tmp_path: Path) -> None:
    registry = OpportunityStateRegistry()
    rec = OpportunityStateRecord(opportunity_id="OPP-R1")
    rec.title = "Roundtrip Opp"
    rec.lifecycle_state = LIFECYCLE_APPLICATION_DRAFT_PENDING
    rec.source_flags = {"in_find_opportunities"}
    registry._records["OPP-R1"] = rec

    path = tmp_path / "registry.json"
    save_registry(registry, path)
    loaded = load_registry(path)
    loaded_rec = loaded.get_by_id("OPP-R1")
    assert loaded_rec is not None
    assert loaded_rec.title == "Roundtrip Opp"
    assert loaded_rec.lifecycle_state == LIFECYCLE_APPLICATION_DRAFT_PENDING
    assert loaded_rec.source_flags == {"in_find_opportunities"}


def test_load_registry_missing_file_returns_empty() -> None:
    loaded = load_registry(Path("/nonexistent/path/registry.json"))
    assert loaded.to_dict_list() == []

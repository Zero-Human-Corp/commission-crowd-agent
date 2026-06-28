"""Telegram-driven inline approval workflow for application packs.

Replaces plain-text approval alerts with rich messages that include inline
action buttons. Operators tap "🟢 Approve Pack" or "🔴 Reject Pack" to:

1. Acknowledge the callback query (stops the loading spinner).
2. Update the corresponding ApprovalGate Sheet record.
3. Migrate the opportunity lifecycle state in the state registry.
4. Persist the updated registry to disk when a path is configured.

All outbound actions are gated by a ``dry_run`` parameter; the module never
sends real Telegram messages or mutates Sheets unless explicitly told to.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
from typing import Any

from ..adapters import NotifierAdapter
from ..approval_gate import ApprovalGate
from ..canonical import CanonicalOpportunity
from ..config import load_settings
from ..state_registry import (
    LIFECYCLE_APPLICATION_APPROVED,
    LIFECYCLE_APPLICATION_DRAFT_PENDING,
    LIFECYCLE_APPLICATION_REJECTED,
    OpportunityStateRecord,
    OpportunityStateRegistry,
)

DEFAULT_REGISTRY_PATH = Path("/home/ubuntu/hermes-control/runtime/cca_state_registry.json")
CALLBACK_DATA_PATTERN = re.compile(r"^(approve|reject)_(.+)$")


@dataclass
class ApprovalPack:
    """Compact, operator-safe metadata for an application pack."""

    opportunity_id: str
    title: str = ""
    commission_terms: str = ""
    target_size: str = ""
    principal_name: str = ""
    source_url: str = ""
    risk_level: str = "low"
    approval_id: str = ""

    @classmethod
    def from_canonical(
        cls,
        opp: CanonicalOpportunity,
        approval_id: str = "",
        target_size: str = "",
    ) -> ApprovalPack:
        return cls(
            opportunity_id=str(opp.source_opportunity_id),
            title=opp.title or opp.display_name,
            commission_terms=opp.commission_text or "Not stated",
            target_size=target_size or _infer_target_size(opp),
            principal_name=opp.company_name or "",
            source_url=opp.source_url,
            risk_level="low" if not opp.data_quality_flags else "medium",
            approval_id=approval_id,
        )


def _infer_target_size(opp: CanonicalOpportunity) -> str:
    """Best-effort target-size label from deal value / commission text."""
    if opp.deal_value_usd:
        return f"${opp.deal_value_usd:,}+ ACV"
    if opp.commission_text:
        m = re.search(r"\$[\d,]+(?:\s*[-–]\s*\$?[\d,]+)?", opp.commission_text)
        if m:
            return m.group(0)
    return "Not stated"


def escape_markdown(text: str) -> str:
    """Escape Telegram MarkdownV1 reserved characters."""
    if not text:
        return ""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", str(text))


def build_approval_message(pack: ApprovalPack) -> dict[str, Any]:
    """Return message text and inline keyboard for an approval pack.

    The keyboard encodes callback_data as ``approve_<opportunity_id>`` or
    ``reject_<opportunity_id>`` so the bot can route operator taps without
    needing to store per-message state.
    """
    text = (
        "⏳ *Application Pack Awaiting Approval*\n\n"
        f"*Target:* {escape_markdown(pack.title)}\n"
        f"*Principal:* {escape_markdown(pack.principal_name)}\n"
        f"*Commission:* {escape_markdown(pack.commission_terms)}\n"
        f"*Target Size:* {escape_markdown(pack.target_size)}\n"
        f"*Risk:* {pack.risk_level}\n"
        f"*Approval ID:* `{pack.approval_id}`\n\n"
        "Choose an action:"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "🟢 Approve Pack",
                    "callback_data": f"approve_{pack.opportunity_id}",
                },
                {
                    "text": "🔴 Reject Pack",
                    "callback_data": f"reject_{pack.opportunity_id}",
                },
            ]
        ]
    }
    return {"text": text, "reply_markup": reply_markup}


async def send_approval_request(
    pack: ApprovalPack,
    notifier: NotifierAdapter,
    *,
    chat_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Send the approval request via Telegram (or simulate in dry-run)."""
    message = build_approval_message(pack)
    if dry_run:
        return {
            "ok": True,
            "sent": False,
            "dry_run": True,
            "text": message["text"],
            "reply_markup": message["reply_markup"],
        }

    return notifier.send_message(
        chat_id=chat_id,
        text=message["text"],
        parse_mode="Markdown",
        reply_markup=message["reply_markup"],
    )


def parse_callback_data(data: str) -> dict[str, str] | None:
    """Parse Telegram callback_data into action and opportunity_id."""
    m = CALLBACK_DATA_PATTERN.match(data)
    if not m:
        return None
    return {"action": m.group(1), "opportunity_id": m.group(2)}


def _record_from_dict(data: dict[str, Any]) -> OpportunityStateRecord:
    """Hydrate an OpportunityStateRecord from a plain JSON dict."""
    rec = OpportunityStateRecord(opportunity_id=data["opportunity_id"])
    rec.title = data.get("title", "")
    rec.principal_name = data.get("principal_name", "")
    rec.lifecycle_state = data.get("lifecycle_state", "")
    rec.source_flags = set(data.get("source_flags", []))
    rec.commission_percent = data.get("commission_percent")
    rec.commission_text = data.get("commission_text", "")
    rec.residual_terms = data.get("residual_terms", False)
    rec.territory = data.get("territory", "")
    rec.category = data.get("category", "")
    rec.sales_motion = data.get("sales_motion", "")
    rec.source_url = data.get("source_url", "")
    rec.invitation_confidence = data.get("invitation_confidence", "")
    rec.invitation_message_id = data.get("invitation_message_id", "")
    rec.score = data.get("score", 0.0)
    rec.reasons = data.get("reasons", [])
    rec.data_quality_flags = data.get("data_quality_flags", [])
    rec.requires_operator_review = data.get("requires_operator_review", False)
    rec.conflicts = data.get("conflicts", [])
    rec.provenance = data.get("provenance", [])
    rec.search_queries = data.get("search_queries", [])
    rec.query_overlap_count = data.get("query_overlap_count", 1)
    rec.opportunity_id_missing = data.get("opportunity_id_missing", False)
    rec.created_at = data.get("created_at", datetime.now(UTC).isoformat())
    rec.updated_at = data.get("updated_at", datetime.now(UTC).isoformat())
    # Wave 3 Track A (H5): hydrate identity-gate fields so a reloaded record
    # preserves verification state. Without these, _record_from_dict relied on
    # dataclass defaults and a verified candidate read as "not verified" after
    # reload — evaluate_identity_gate would then block a legitimate write.
    rec.identity_verification_status = data.get("identity_verification_status", "")
    rec.identity_conflict_disposition = data.get("identity_conflict_disposition", "")
    rec.identity_verified_at = data.get("identity_verified_at", "")
    return rec


def load_registry(path: Path | str | None = None) -> OpportunityStateRegistry:
    """Load a persisted opportunity registry, or return an empty one."""
    target = Path(path) if path else DEFAULT_REGISTRY_PATH
    registry = OpportunityStateRegistry()
    if not target.exists():
        return registry
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        for item in raw:
            rec = _record_from_dict(item)
            registry._records[rec.opportunity_id] = rec
    except (json.JSONDecodeError, OSError, KeyError):
        # Fail open: return empty registry so the caller can decide to abort.
        pass
    return registry


def save_registry(
    registry: OpportunityStateRegistry,
    path: Path | str | None = None,
) -> Path:
    """Persist the registry to JSON and return the written path."""
    target = Path(path) if path else DEFAULT_REGISTRY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(registry.to_dict_list(), indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return target


def migrate_lifecycle_state(
    registry: OpportunityStateRegistry,
    opportunity_id: str,
    to_state: str,
    *,
    from_states: set[str] | None = None,
) -> dict[str, Any]:
    """Mutate an opportunity's lifecycle state in the registry.

    Args:
        registry: In-memory registry to mutate.
        opportunity_id: Target opportunity ID.
        to_state: Destination lifecycle state.
        from_states: Optional guard — only transition if current state is in this set.

    Returns:
        Structured dict with ok, previous_state, current_state.
    """
    record = registry.get_by_id(opportunity_id)
    if record is None:
        return {
            "ok": False,
            "error": f"Opportunity {opportunity_id} not found in registry",
            "previous_state": None,
            "current_state": None,
        }

    previous = record.lifecycle_state
    if from_states is not None and previous not in from_states:
        return {
            "ok": False,
            "error": (
                f"Opportunity {opportunity_id} is in state '{previous}', "
                f"not in allowed transition set {sorted(from_states)}"
            ),
            "previous_state": previous,
            "current_state": previous,
        }

    record.lifecycle_state = to_state
    record.updated_at = datetime.now(UTC).isoformat()
    return {
        "ok": True,
        "previous_state": previous,
        "current_state": to_state,
    }


def _answer_callback_query(
    notifier: NotifierAdapter,
    callback_query_id: str,
    text: str | None = None,
) -> dict[str, Any]:
    """Acknowledge a Telegram callback query to stop the spinner."""
    if notifier.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "callback_query_id": callback_query_id,
            "text": text,
        }

    if not notifier.bot_token:
        return {
            "ok": False,
            "error": "Missing bot_token",
            "callback_query_id": callback_query_id,
        }

    payload: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text is not None:
        payload["text"] = text

    try:
        response = notifier._post_with_retry("answerCallbackQuery", payload)
        response.raise_for_status()
        data = response.json()
        return {
            "ok": bool(data.get("ok")),
            "status": response.status_code,
            "callback_query_id": callback_query_id,
            "error": data.get("description") if not data.get("ok") else None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "callback_query_id": callback_query_id,
        }


async def handle_callback_query(
    query: dict[str, Any],
    *,
    notifier: NotifierAdapter,
    registry: OpportunityStateRegistry,
    gate: ApprovalGate | None = None,
    registry_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Route a Telegram callback_query to the appropriate lifecycle action.

    Args:
        query: Telegram callback_query object with at least ``id`` and ``data``.
        notifier: Wired NotifierAdapter used to answer the callback.
        registry: Opportunity registry whose state will be mutated.
        gate: Optional ApprovalGate for Sheet-side status updates.
        registry_path: Where to persist the mutated registry.
        dry_run: If True, no Telegram or Sheet mutation occurs.

    Returns:
        Structured result dict including action, opportunity_id, ack result,
        state migration result, and gate result.
    """
    callback_id = str(query.get("id", ""))
    raw_data = query.get("data", "")

    parsed = parse_callback_data(raw_data)
    if parsed is None:
        ack = _answer_callback_query(notifier, callback_id, text="Unrecognised action")
        return {
            "ok": False,
            "error": f"Unrecognised callback data: {raw_data!r}",
            "callback_query_id": callback_id,
            "ack": ack,
        }

    action = parsed["action"]
    opportunity_id = parsed["opportunity_id"]

    # Determine the approval_id if the message carries it. Telegram puts the
    # original message under query["message"]; we look for the approval ID in
    # the caption/text if it was included when the message was sent.
    approval_id = _extract_approval_id_from_message(query.get("message", {}))

    # Acknowledge immediately so the button spinner stops.
    ack_text = "✅ Approved" if action == "approve" else "❌ Rejected"
    ack = _answer_callback_query(notifier, callback_id, text=ack_text)

    # Migrate registry lifecycle state.
    if action == "approve":
        migration = migrate_lifecycle_state(
            registry,
            opportunity_id,
            LIFECYCLE_APPLICATION_APPROVED,
            from_states={LIFECYCLE_APPLICATION_DRAFT_PENDING, "application_draft_created"},
        )
    else:
        migration = migrate_lifecycle_state(
            registry,
            opportunity_id,
            LIFECYCLE_APPLICATION_REJECTED,
            from_states={LIFECYCLE_APPLICATION_DRAFT_PENDING, "application_draft_created"},
        )

    # Persist registry if a path is provided and migration succeeded.
    persisted: Path | None = None
    if migration["ok"] and registry_path is not None and not dry_run:
        persisted = save_registry(registry, registry_path)

    # Update the ApprovalGate Sheet record if we can map to an approval_id.
    gate_result: dict[str, Any] | None = None
    if gate is not None and approval_id and not dry_run:
        gate_result = (
            gate.approve(approval_id)
            if action == "approve"
            else gate.reject(approval_id)
        )

    return {
        "ok": migration["ok"],
        "action": action,
        "opportunity_id": opportunity_id,
        "approval_id": approval_id,
        "callback_query_id": callback_id,
        "ack": ack,
        "migration": migration,
        "registry_persisted": str(persisted) if persisted else None,
        "gate_result": gate_result,
    }


def _extract_approval_id_from_message(message: dict[str, Any]) -> str:
    """Try to read the approval_id back from the original message text/caption."""
    text = message.get("text", "") or message.get("caption", "")
    # Tolerate Markdown bold/italic wrapping between the label and the code block.
    m = re.search(r"Approval ID[^`]*`([A-Za-z0-9\-]+)`", text)
    return m.group(1) if m else ""


def main() -> int:
    """CLI entry point for dry-run demonstrations."""
    parser = argparse.ArgumentParser(description="Telegram inline approval workflow")
    parser.add_argument("--dry-run", action="store_true", help="Simulate all outbound actions")
    parser.add_argument("--opportunity-id", default="SAMPLE-1001")
    parser.add_argument("--approval-id", default="A001")
    parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--action", choices=["approve", "reject"], default="approve")
    args = parser.parse_args()

    settings = load_settings()
    notifier = NotifierAdapter(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        dry_run=args.dry_run,
    )

    pack = ApprovalPack(
        opportunity_id=args.opportunity_id,
        title="SAMPLE AI CRM — UK & Ireland",
        principal_name="Sample Principal Ltd",
        commission_terms="25% on first-year revenue",
        target_size="$5,000–$25,000 ACV",
        risk_level="low",
        approval_id=args.approval_id,
    )

    # Seed registry with the pack in application_draft_pending.
    registry = OpportunityStateRegistry()
    rec = OpportunityStateRecord(opportunity_id=args.opportunity_id)
    rec.title = pack.title
    rec.lifecycle_state = LIFECYCLE_APPLICATION_DRAFT_PENDING
    rec.commission_text = pack.commission_terms
    registry._records[args.opportunity_id] = rec

    # Simulate sending the inline-keyboard message.
    send_result = asyncio.run(
        send_approval_request(
            pack,
            notifier,
            chat_id=settings.telegram_chat_id,
            dry_run=args.dry_run,
        )
    )
    print("send_result:", json.dumps(send_result, indent=2, default=str))

    # Simulate operator tap.
    fake_query = {
        "id": "cq-sample-001",
        "data": f"{args.action}_{args.opportunity_id}",
        "message": {"text": send_result.get("text", ""), "message_id": 1},
    }
    handle_result = asyncio.run(
        handle_callback_query(
            fake_query,
            notifier=notifier,
            registry=registry,
            registry_path=args.registry_path if not args.dry_run else None,
            dry_run=args.dry_run,
        )
    )
    print("handle_result:", json.dumps(handle_result, indent=2, default=str))
    final_rec = registry.get_by_id(args.opportunity_id)
    print(
        "final_lifecycle_state:",
        final_rec.lifecycle_state if final_rec else "missing",
    )
    return 0 if handle_result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

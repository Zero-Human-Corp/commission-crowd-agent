#!/usr/bin/env python3
"""CCA Telegram Approval Daemon — persistent background worker.

Listens for inline-keyboard callback queries (approve_/reject_) from the
operator via Telegram Bot long-polling. For each callback:

1. Answers the callback query (stops the spinner).
2. Migrates the opportunity lifecycle state in the local registry.
3. Persists the updated registry to disk.
4. Updates the ApprovalGate Sheet record (if configured).

Environment:
- Expects standard CCA env (shared.env + .env) to be loadable.
- Requires TELEGRAM_BOT_TOKEN and optionally TELEGRAM_CHAT_ID.
- Uses the same state registry path as submit_application_packs.py.

Usage:
    python -m scripts.telegram_approval_daemon
    # Or via systemd: systemctl start cca-telegram-bot
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# fmt: off
from commission_crowd_agent.adapters import (  # type: ignore[import-untyped]
    GoogleSheetsAdapter,
    NotifierAdapter,
)
from commission_crowd_agent.approval_gate import ApprovalGate  # type: ignore[import-untyped]
from commission_crowd_agent.config import load_settings  # type: ignore[import-untyped]
from commission_crowd_agent.state_registry import OpportunityStateRegistry  # type: ignore[import-untyped]
from commission_crowd_agent.supervisor_relay import (  # type: ignore[import-untyped]
    SupervisorRelay,
    SupervisorTaskType,
)
from commission_crowd_agent.workflows.approvals import (  # type: ignore[import-untyped]
    handle_callback_query,
    load_registry,
)

# fmt: on

RUNTIME_DIR = Path("/home/ubuntu/hermes-control/runtime")
DEFAULT_REGISTRY_PATH = RUNTIME_DIR / "cca_state_registry.json"
LOG_PATH = Path(os.environ.get("LOG_PATH", RUNTIME_DIR / "cca_telegram_daemon.log"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("cca-telegram-daemon")

# Graceful shutdown bookkeeping
_shutdown_event = asyncio.Event()


def _supervisor_checkpoint(callback: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Option 2: explicit SupervisorRelay checkpoint before handling any callback.

    Routes the decision through the configured local primary-supervisor model
    (env-controlled; Workstream A expects ``glm-5.2:cloud``). The checkpoint
    validates that the callback is safe to process and is not trying to trigger
    a blocked action. Returns a dict so callers can log and skip safely.
    """
    data = callback.get("data", "")
    from_user = callback.get("from", {}).get("username", "unknown")
    prompt = (
        f"Telegram approval daemon received a callback.\n"
        f"Callback data: {data!r}\n"
        f"From user: {from_user}\n\n"
        f"Decide whether the daemon should process this callback. "
        f"Return JSON with approved (bool), reason (str), recommended_action (str), "
        f"risk_level (low|medium|high|unknown), and notes (str). "
        f"If the action is approve/reject for an opportunity, recommended_action must be "
        f"'approval_status_change' so the human-only gate can block it until operator "
        f"confirmation is verified."
    )
    system = (
        "You are the CCA primary supervisor. Review inbound Telegram callbacks. "
        "Be conservative. Any state-changing action should require explicit human approval. "
        "Respond only with the requested JSON."
    )
    # Option 2: supervisor inference is independent of daemon write dry-run.
    env_dry_run = os.environ.get("CCA_SUPERVISOR_INFERENCE_DRY_RUN", "").lower()
    relay_dry_run = env_dry_run in {"1", "true"}
    relay = SupervisorRelay(dry_run=relay_dry_run)
    try:
        resp = relay.route(SupervisorTaskType.PRIMARY_SUPERVISOR, prompt, system=system)
        return {
            "ok": resp.approved and not resp.human_approval_required,
            "approved": resp.approved,
            "human_approval_required": resp.human_approval_required,
            "risk_level": resp.risk_level,
            "reason": resp.reason,
            "recommended_action": resp.recommended_action,
            "requested_model": resp.requested_model,
            "actual_model": resp.actual_model,
            "fallback_reason": resp.fallback_reason,
        }
    except Exception as exc:
        logger.warning("SupervisorRelay checkpoint failed: %s", exc)
        return {
            "ok": False,
            "approved": False,
            "reason": f"Checkpoint error: {exc}",
            "recommended_action": "",
        }


def _signal_handler(signum: int, frame: Any) -> None:
    logger.info("Received signal %s, shutting down gracefully...", signum)
    _shutdown_event.set()


async def _process_updates(
    token: str,
    notifier: NotifierAdapter,
    registry: OpportunityStateRegistry,
    registry_path: Path,
    gate: ApprovalGate | None,
    sheets: GoogleSheetsAdapter | None,
    *,
    dry_run: bool = False,
) -> None:
    """Long-poll Telegram getUpdates and dispatch callback queries."""
    import httpx

    base = f"https://api.telegram.org/bot{token}"
    offset: int = 0
    consecutive_errors = 0
    max_backoff = 60

    async with httpx.AsyncClient(timeout=30.0) as client:
        while not _shutdown_event.is_set():
            try:
                resp = await client.get(
                    f"{base}/getUpdates",
                    params={"offset": offset, "limit": 10, "timeout": 30},
                )
                resp.raise_for_status()
                data = resp.json()
                consecutive_errors = 0

                if not data.get("ok"):
                    logger.warning("Telegram API returned ok=false: %s", data)
                    await asyncio.sleep(1)
                    continue

                updates = data.get("result", [])
                for update in updates:
                    offset = max(offset, update.get("update_id", 0) + 1)
                    callback = update.get("callback_query")
                    if callback is None:
                        continue

                    logger.info(
                        "Callback query id=%s data=%s from_user=%s",
                        callback.get("id"),
                        callback.get("data"),
                        callback.get("from", {}).get("username"),
                    )

                    # Option 2 SupervisorRelay checkpoint (Workstream A: glm-5.2:cloud)
                    checkpoint = _supervisor_checkpoint(callback, dry_run=dry_run)
                    logger.info(
                        "Supervisor checkpoint ok=%s approved=%s risk=%s action=%s model=%s",
                        checkpoint.get("ok"),
                        checkpoint.get("approved"),
                        checkpoint.get("risk_level"),
                        checkpoint.get("recommended_action"),
                        checkpoint.get("actual_model") or checkpoint.get("requested_model"),
                    )
                    if not checkpoint.get("ok"):
                        logger.warning(
                            "Skipping callback %s — supervisor did not approve: %s",
                            callback.get("id"),
                            checkpoint.get("reason"),
                        )
                        continue

                    result = await handle_callback_query(
                        callback,
                        notifier=notifier,
                        registry=registry,
                        gate=gate,
                        registry_path=registry_path,
                        dry_run=dry_run,
                    )

                    logger.info(
                        "Handled callback: action=%s opp=%s ok=%s migrated=%s persisted=%s",
                        result.get("action"),
                        result.get("opportunity_id"),
                        result.get("ok"),
                        result.get("migration", {}).get("current_state"),
                        result.get("registry_persisted"),
                    )

                    # Refresh gate if sheets writes happened
                    if sheets and not dry_run and gate:
                        with contextlib.suppress(Exception):
                            gate.sheets_adapter = sheets

                await asyncio.sleep(0.5)

            except httpx.HTTPStatusError as exc:
                consecutive_errors += 1
                backoff = min(2**consecutive_errors, max_backoff)
                logger.error(
                    "HTTPStatusError %s — backing off %ss",
                    exc.response.status_code,
                    backoff,
                )
                await asyncio.sleep(backoff)

            except httpx.RequestError as exc:
                consecutive_errors += 1
                backoff = min(2**consecutive_errors, max_backoff)
                logger.error("RequestError — backing off %ss: %s", backoff, exc)
                await asyncio.sleep(backoff)

            except Exception:
                consecutive_errors += 1
                backoff = min(2**consecutive_errors, max_backoff)
                logger.error(
                    "Unhandled exception — backing off %ss:\n%s",
                    backoff,
                    traceback.format_exc(),
                )
                await asyncio.sleep(backoff)


async def amain(*, dry_run: bool = False, registry_path: Path | None = None) -> None:
    settings = load_settings()
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id

    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not configured. Exiting.")
        sys.exit(1)

    notifier = NotifierAdapter(bot_token=token, chat_id=chat_id, dry_run=dry_run)
    registry = load_registry(registry_path)
    target_path = registry_path or DEFAULT_REGISTRY_PATH

    # Ensure runtime dir exists
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    sheets: GoogleSheetsAdapter | None = None
    gate: ApprovalGate | None = None
    if settings.google_ready and not dry_run:
        sheets = GoogleSheetsAdapter(
            spreadsheet_id=settings.google_sheets_spreadsheet_id,
            credentials_path=settings.google_application_credentials_path,
            service_account_json=settings.google_service_account_json,
            dry_run=False,
        )
        gate = ApprovalGate(sheets_adapter=sheets, notifier=notifier)

    logger.info(
        "CCA Telegram Daemon starting — dry_run=%s registry=%s token_present=%s",
        dry_run,
        target_path,
        bool(token),
    )

    await _process_updates(
        token=token,
        notifier=notifier,
        registry=registry,
        registry_path=target_path,
        gate=gate,
        sheets=sheets,
        dry_run=dry_run,
    )

    logger.info("CCA Telegram Daemon shut down cleanly.")


async def _run_demo_callback(
    *,
    opportunity_id: str,
    action: str,
    approval_id: str,
    dry_run: bool,
    registry_path: Path,
) -> int:
    """Simulate a single operator tap and exercise the supervisor checkpoint."""
    from commission_crowd_agent.workflows.approvals import (
        ApprovalPack,
        LIFECYCLE_APPLICATION_DRAFT_PENDING,
        OpportunityStateRecord,
        OpportunityStateRegistry,
        send_approval_request,
    )

    settings = load_settings()
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not configured. Exiting.")
        return 1

    notifier = NotifierAdapter(bot_token=token, chat_id=chat_id, dry_run=dry_run)
    registry = OpportunityStateRegistry()
    rec = OpportunityStateRecord(opportunity_id=opportunity_id)
    rec.title = f"Workstream A Demo Target {opportunity_id}"
    rec.lifecycle_state = LIFECYCLE_APPLICATION_DRAFT_PENDING
    rec.commission_text = "25% recurring commission"
    registry._records[opportunity_id] = rec

    pack = ApprovalPack(
        opportunity_id=opportunity_id,
        title=rec.title,
        principal_name="Demo Principal Ltd",
        commission_terms=rec.commission_text,
        target_size="$50,000+ ACV",
        risk_level="low",
        approval_id=approval_id,
    )
    send_result = await send_approval_request(pack, notifier, chat_id=chat_id, dry_run=dry_run)
    fake_query = {
        "id": "cq-ws-a-demo-001",
        "data": f"{action}_{opportunity_id}",
        "message": {"text": send_result.get("text", ""), "message_id": 1},
    }
    result = await handle_callback_query(
        fake_query,
        notifier=notifier,
        registry=registry,
        registry_path=registry_path if not dry_run else None,
        dry_run=dry_run,
    )
    logger.info("Demo callback result: %s", result)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="CCA Telegram Approval Daemon")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Process callbacks but do not mutate registry or Sheets",
    )
    parser.add_argument(
        "--registry-path",
        default=str(DEFAULT_REGISTRY_PATH),
        help="Path to opportunity state registry JSON",
    )
    parser.add_argument(
        "--demo-mode",
        action="store_true",
        help="Simulate a single callback and exit (for Option 2 workstream demos)",
    )
    parser.add_argument(
        "--opportunity-id",
        default="WS-A-1001",
        help="Opportunity ID for demo-mode callback",
    )
    parser.add_argument(
        "--approval-id",
        default="A001",
        help="Approval ID for demo-mode callback",
    )
    parser.add_argument(
        "--action",
        choices=["approve", "reject"],
        default="approve",
        help="Operator action for demo-mode callback",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        if args.demo_mode:
            return asyncio.run(
                _run_demo_callback(
                    opportunity_id=args.opportunity_id,
                    action=args.action,
                    approval_id=args.approval_id,
                    dry_run=args.dry_run,
                    registry_path=Path(args.registry_path),
                )
            )
        asyncio.run(amain(dry_run=args.dry_run, registry_path=Path(args.registry_path)))
    except KeyboardInterrupt:
        logger.info("Interrupted by operator.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

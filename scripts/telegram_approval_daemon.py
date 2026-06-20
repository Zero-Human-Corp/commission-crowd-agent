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
import logging
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
from commission_crowd_agent.state_registry import (
    OpportunityStateRegistry,  # type: ignore[import-untyped]
)
from commission_crowd_agent.workflows.approvals import (  # type: ignore[import-untyped]
    handle_callback_query,
    load_registry,
)

# fmt: on

RUNTIME_DIR = Path("/home/ubuntu/hermes-control/runtime")
DEFAULT_REGISTRY_PATH = RUNTIME_DIR / "cca_state_registry.json"
LOG_PATH = RUNTIME_DIR / "cca_telegram_daemon.log"

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
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        asyncio.run(amain(dry_run=args.dry_run, registry_path=Path(args.registry_path)))
    except KeyboardInterrupt:
        logger.info("Interrupted by operator.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

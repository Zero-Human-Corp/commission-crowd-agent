"""CCA Guardian — runtime safety utilities for Phase 2 hardening.

Provides:
- bounded_retry() decorator with exponential backoff
- hash_payload() for deterministic SHA-256 content hashes
- IdempotencyKey for deduplication across CRM, approvals, sends, calendar
- CampaignContext for run IDs and correlation
- check_expiry() for time-bound approval validation

No external network calls. No secrets logged.
"""

from __future__ import annotations

import hashlib
import json
import secrets as _secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


# ------------------------------------------------------------------
# Retry decorator
# ------------------------------------------------------------------


def bounded_retry(
    max_attempts: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 8.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    on_final_failure: Callable[[Exception], None] | None = None,
) -> Callable[[F], F]:
    """Decorator that retries a function on safe retryable failures.

    Does NOT retry on assertion failures or explicit ValueError.
    Designed for network / IO operations, not for logic errors.
    """

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        sleep_for = min(backoff_base * (2 ** (attempt - 1)), backoff_max)
                        time.sleep(sleep_for)
                    else:
                        break
            if last_exc is not None and on_final_failure is not None:
                on_final_failure(last_exc)
            raise last_exc or RuntimeError("bounded_retry exhausted all attempts")

        return wrapper  # type: ignore[return-value]

    return decorator


# ------------------------------------------------------------------
# Payload hashing
# ------------------------------------------------------------------


def hash_payload(*, action: str, opportunity_id: str, payload: dict[str, Any]) -> str:
    """Return a deterministic SHA-256 hex digest of the canonical payload.

    The hash is stable regardless of key ordering.
    Never includes secret values — caller must mask secrets before calling.
    """
    canonical = json.dumps(
        {"action": action, "opportunity_id": opportunity_id, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------
# Campaign context / correlation IDs
# ------------------------------------------------------------------


@dataclass
class CampaignContext:
    """Lightweight run context for tracing and idempotency."""

    run_id: str = field(default_factory=lambda: _secrets.token_urlsafe(8))
    correlation_id: str = field(default_factory=lambda: _secrets.token_urlsafe(8))
    started_at_utc: str = field(default_factory=lambda: _now_iso())
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "started_at_utc": self.started_at_utc,
            "dry_run": self.dry_run,
        }


def _now_iso() -> str:
    from datetime import datetime

    return datetime.utcnow().isoformat()


# ------------------------------------------------------------------
# Idempotency store (in-memory with bounded size)
# ------------------------------------------------------------------


class IdempotencyStore:
    """Tracks processed action keys to prevent duplicates.

    Keys are action-type + opportunity_id + payload_hash.
    Bounded to 10,000 entries; oldest are evicted on overflow.
    """

    _MAX_SIZE: int = 10_000

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}
        self._order: list[str] = []

    def _key(self, *, action: str, opportunity_id: str, payload_hash: str) -> str:
        return f"{action}:{opportunity_id}:{payload_hash}"

    def mark_processed(
        self,
        *,
        action: str,
        opportunity_id: str,
        payload_hash: str,
        timestamp: str = "",
    ) -> bool:
        """Mark an action as processed. Returns True if already processed."""
        key = self._key(action=action, opportunity_id=opportunity_id, payload_hash=payload_hash)
        if key in self._seen:
            return True
        self._seen[key] = timestamp or _now_iso()
        self._order.append(key)
        if len(self._order) > self._MAX_SIZE:
            oldest = self._order.pop(0)
            self._seen.pop(oldest, None)
        return False

    def is_processed(
        self,
        *,
        action: str,
        opportunity_id: str,
        payload_hash: str,
    ) -> bool:
        key = self._key(action=action, opportunity_id=opportunity_id, payload_hash=payload_hash)
        return key in self._seen

    def clear(self) -> None:
        self._seen.clear()
        self._order.clear()


# ------------------------------------------------------------------
# Approval expiry check
# ------------------------------------------------------------------


def check_expiry(
    created_at_utc: str,
    *,
    ttl_hours: float = 168.0,
) -> dict[str, Any]:
    """Check whether an approval has expired.

    Returns a structured result with ``expired`` bool and ``remaining_hours``.
    """
    from datetime import datetime

    try:
        created = datetime.fromisoformat(created_at_utc)
    except (ValueError, TypeError):
        return {"expired": True, "remaining_hours": 0.0, "error": "Invalid timestamp"}

    now = datetime.utcnow()
    elapsed_hours = (now - created).total_seconds() / 3600.0
    remaining = ttl_hours - elapsed_hours
    return {
        "expired": remaining <= 0,
        "remaining_hours": max(0.0, remaining),
        "error": None,
    }

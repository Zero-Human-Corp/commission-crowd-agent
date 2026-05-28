"""Supervisor Relay — routes AI supervision tasks to local/Hermes-routed models.

Never calls OpenAI API. All inference runs against the local Ollama-compatible
endpoint (or another local provider configured via ``SUPERVISOR_BASE_URL``).
Human-only gates are enforced programmatically regardless of model output.

Design goals:
- Model availability is explicit — no silent fallback.
- If the configured route model is unavailable and fallback is disabled,
  the relay returns a structured unavailable-model decision.
- If fallback is enabled (smoke-test mode), the audit trail includes
  requested_model, actual_model, fallback_reason.
- Telegram acknowledgements use the existing NotifierAdapter and config.
- Supervisor outbox directory is auto-created if missing.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import CcaSettings, load_settings

if TYPE_CHECKING:
    pass


class SupervisorTaskType(StrEnum):
    """Canonical task types that route to distinct local models."""

    PRIMARY_SUPERVISOR = "primary_supervisor"
    CODE_REVIEW = "code_review"
    REASONING_FALLBACK = "reasoning_fallback"
    DRAFT_REVIEW = "draft_review"
    LONG_CONTEXT_REVIEW = "long_context_review"


class SupervisorBlockedActionError(Exception):
    """Raised when the model output suggests a blocked action."""


class SupervisorResponseValidationError(Exception):
    """Raised when the model JSON does not match the expected schema."""


class SupervisorUnavailableModelError(Exception):
    """Raised when the configured route model is not available and fallback is disabled."""


class SupervisorResponse(BaseModel):
    """Strict JSON schema for every supervisor response.

    Fields:
        approved: bool — whether the supervisor approves proceeding.
        reason: str — human-readable rationale.
        recommended_action: str — downstream action (may trigger a block).
        risk_level: str — low | medium | high | unknown.
        notes: str — free-form additional context.
        requested_model: str | None — model that was configured for the route.
        actual_model: str | None — model actually used (may differ on fallback).
        fallback_reason: str | None — why fallback happened (if any).
        review_independence: str — high | medium | low.
        human_approval_required: bool — True if self-review guard triggered.
    """

    approved: bool = Field(default=False)
    reason: str = Field(default="", max_length=2000)
    recommended_action: str = Field(default="", max_length=500)
    risk_level: str = Field(default="unknown")
    notes: str = Field(default="", max_length=2000)
    requested_model: str | None = Field(default=None)
    actual_model: str | None = Field(default=None)
    fallback_reason: str | None = Field(default=None)
    review_independence: str = Field(default="high")
    human_approval_required: bool = Field(default=False)

    @classmethod
    def from_text(cls, text: str) -> SupervisorResponse:
        """Parse model output, stripping markdown fences if present."""
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        if not cleaned:
            raise SupervisorResponseValidationError("Empty supervisor response after cleaning.")
        return cls.model_validate_json(cleaned)


# Actions that ALWAYS require human approval.
BLOCKED_ACTION_VERBS: set[str] = {
    "send",
    "apply",
    "message",
    "login",
    "api_call",
    "spend",
    "approval_status_change",
}

SUPERVISOR_SCHEMA_DESCRIPTION: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "reason": {"type": "string"},
        "recommended_action": {"type": "string"},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high", "unknown"]},
        "notes": {"type": "string"},
    },
    "required": ["approved", "reason"],
}


def _is_blocked_action(action: str) -> bool:
    """Return True if *action* is a blocked verb or starts with one."""
    normalized = action.strip().lower().replace(" ", "_")
    if not normalized:
        return False
    if normalized in BLOCKED_ACTION_VERBS:
        return True
    return any(normalized.startswith(f"{verb}_") for verb in BLOCKED_ACTION_VERBS)


def _check_model_available(
    base_url: str,
    model_name: str,
    *,
    client: httpx.Client | None = None,
) -> bool:
    """Query Ollama /api/tags to see if a model name is available.

    ``base_url`` may end with ``/v1`` (OpenAI-compatible path) but the
    Ollama ``/api/tags`` endpoint lives at the root. We strip ``/v1``
    before appending ``/api/tags`` so availability checks work whether
    the configured base URL includes ``/v1`` or not.
    """
    _client = client or httpx.Client(timeout=10.0)
    try:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        resp = _client.get(f"{base}/api/tags")
        if resp.status_code != 200:
            return False
        data = resp.json()
        available = {m.get("name", "") for m in data.get("models", [])}
        return model_name in available
    except Exception:
        return False
    finally:
        if client is None:
            _client.close()


def _resolve_model(
    base_url: str,
    requested: str,
    fallback: str,
    allow_fallback: bool,
) -> tuple[str, str | None]:
    """Return the model to use plus an optional fallback_reason string.

    Resolution order:
    1. Exact match of requested model.
    2. Cloud-tagged equivalent ({requested}:cloud) if exact not available.
    3. Configured fallback model if allow_fallback=True.
    4. Cloud-tagged equivalent of fallback if exact fallback not available.
    If none resolve, raises SupervisorUnavailableModelError.
    """
    # 1. Exact match
    if _check_model_available(base_url, requested):
        return requested, None

    # 2. Cloud-tagged equivalent of primary
    cloud_variant = f"{requested}:cloud"
    if _check_model_available(base_url, cloud_variant):
        return cloud_variant, (
            f"Exact model '{requested}' unavailable. "
            f"Using cloud-tagged equivalent '{cloud_variant}'."
        )

    # 3. Configured fallback (only if explicitly enabled)
    if allow_fallback and fallback:
        if _check_model_available(base_url, fallback):
            return fallback, (
                f"Requested model '{requested}' unavailable. "
                f"Fallback to '{fallback}' enabled."
            )
        # 4. Cloud-tagged equivalent of fallback
        fallback_cloud = f"{fallback}:cloud"
        if _check_model_available(base_url, fallback_cloud):
            return fallback_cloud, (
                f"Requested model '{requested}' unavailable. "
                f"Fallback to '{fallback_cloud}' (cloud variant) enabled."
            )

    raise SupervisorUnavailableModelError(
        f"Model '{requested}' is not available. "
        f"Cloud variant '{cloud_variant}' not available. "
        f"Fallback is {'disabled' if not allow_fallback else 'enabled but model unavailable'}."
    )


def _apply_self_review_guard(resp: SupervisorResponse) -> SupervisorResponse:
    """Detect when the supervisor reviewer is the same model family as the active Hermes worker.

    If the actual_model contains the same family identifier as the Hermes active model
    (e.g. 'kimi'), mark review_independence as 'low' and require human approval.
    This prevents rubber-stamping by the same model family.
    """
    # Hermes active worker model (from env or default)
    hermes_model = __import__("os").environ.get("HERMES_ACTIVE_MODEL", "kimi-k2.6:cloud")
    hermes_family = hermes_model.split("-")[0].lower()

    actual_family = (resp.actual_model or "").split("-")[0].lower()

    if hermes_family and actual_family == hermes_family:
        resp.review_independence = "low"
        resp.human_approval_required = True
        resp.notes = (
            f"[SELF-REVIEW GUARD] Actual reviewer '{resp.actual_model}' shares model family "
            f"with Hermes worker '{hermes_model}'. Review independence degraded. "
            f"{resp.notes}"
        )

    return resp


class SupervisorRelay:
    """Local-only supervisor relay with task-type routing and hard action blocks."""

    def __init__(
        self,
        settings: CcaSettings | None = None,
        client: httpx.Client | None = None,
        dry_run: bool = False,
    ) -> None:
        self.settings = settings or load_settings()
        self.client = client or httpx.Client(timeout=60.0)
        self.dry_run = dry_run
        self._base_url = self.settings.supervisor_base_url.rstrip("/")
        self._api_key = self.settings.supervisor_api_key
        self._model_map: dict[SupervisorTaskType, str] = {
            SupervisorTaskType.PRIMARY_SUPERVISOR: (
                self.settings.supervisor_primary_model
            ),
            SupervisorTaskType.CODE_REVIEW: self.settings.supervisor_code_review_model,
            SupervisorTaskType.REASONING_FALLBACK: (
                self.settings.supervisor_reasoning_fallback_model
            ),
            SupervisorTaskType.DRAFT_REVIEW: self.settings.supervisor_draft_review_model,
            SupervisorTaskType.LONG_CONTEXT_REVIEW: (
                self.settings.supervisor_long_context_model
            ),
        }

    @property
    def enabled(self) -> bool:
        return self.settings.supervisor_mode == "local"

    def safe_repr(self) -> str:
        """Return a secret-free summary of relay configuration."""
        return (
            f"SupervisorRelay(mode={self.settings.supervisor_mode}, "
            f"enabled={self.enabled}, "
            f"primary={self.settings.supervisor_primary_model!r}, "
            f"code_review={self.settings.supervisor_code_review_model!r}, "
            f"reasoning={self.settings.supervisor_reasoning_fallback_model!r}, "
            f"draft={self.settings.supervisor_draft_review_model!r}, "
            f"long_context={self.settings.supervisor_long_context_model!r}, "
            f"emergency={self.settings.supervisor_emergency_fallback_model!r}, "
            f"allow_fallback={self.settings.supervisor_allow_fallback}, "
            f"fallback={self.settings.supervisor_fallback_model!r}, "
            f"dry_run={self.dry_run})"
        )

    def _url(self, path: str) -> str:
        base = self._base_url.rstrip("/")
        # Avoid double /v1 when base_url already includes it (e.g. Ollama default)
        if base.endswith("/v1") and path.startswith("/v1"):
            base = base[:-3]
        return f"{base}{path}"

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _ensure_outbox(self) -> Path:
        outbox = Path("/home/ubuntu/.hermes/supervisor_outbox")
        outbox.mkdir(parents=True, exist_ok=True)
        return outbox

    def _send_telegram_ack(
        self,
        text: str,
    ) -> dict[str, Any]:
        """Send a Telegram acknowledgement using the project notifier if configured."""
        if not self.settings.supervisor_telegram_notify:
            return {"ok": True, "sent": False, "reason": "supervisor_telegram_notify disabled"}
        try:
            from .adapters import NotifierAdapter

            notifier = NotifierAdapter(
                bot_token=self.settings.telegram_bot_token,
                chat_id=self.settings.telegram_chat_id,
            )
            return notifier.send_message(text=text)
        except Exception as exc:
            return {"ok": False, "sent": False, "error": str(exc)}

    def _write_outbox(
        self,
        filename: str,
        data: dict[str, Any],
    ) -> Path:
        outbox = self._ensure_outbox()
        path = outbox / filename
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        return path

    def route(
        self,
        task_type: SupervisorTaskType,
        prompt: str,
        system: str | None = None,
    ) -> SupervisorResponse:
        """Route a supervision prompt to the correct local model.

        Args:
            task_type: Which supervisor persona to invoke.
            prompt: The user prompt for the supervisor.
            system: Optional system message to prepend.

        Returns:
            A validated ``SupervisorResponse``.

        Raises:
            RuntimeError: If the relay is disabled.
            ValueError: If no model is mapped for the task type.
            SupervisorUnavailableModelError: If the model is unavailable and fallback disabled.
            SupervisorResponseValidationError: If the model output violates the schema.
            SupervisorBlockedActionError: If the model suggests a blocked action.
        """
        if not self.enabled:
            raise RuntimeError("Supervisor Relay is not enabled (SUPERVISOR_MODE != local)")

        requested_model = self._model_map.get(task_type)
        if not requested_model:
            raise ValueError(f"No model configured for task type {task_type.value}")

        if self.dry_run:
            return SupervisorResponse(
                approved=False,
                reason="Dry-run mode — no inference performed.",
                recommended_action="",
                risk_level="unknown",
                notes="",
                requested_model=requested_model,
                actual_model=requested_model,
                fallback_reason=None,
            )

        # Resolve model with strict fallback behavior
        actual_model, fallback_reason = _resolve_model(
            base_url=self._base_url,
            requested=requested_model,
            fallback=self.settings.supervisor_fallback_model,
            allow_fallback=self.settings.supervisor_allow_fallback,
        )

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": actual_model,
            "messages": messages,
            "temperature": 0.2,
        }

        response = self.client.post(
            self._url("/v1/chat/completions"),
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        # Strict JSON schema validation
        try:
            supervisor_resp = SupervisorResponse.from_text(content)
        except ValidationError as exc:
            raise SupervisorResponseValidationError(
                f"Supervisor response failed schema validation: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise SupervisorResponseValidationError(
                f"Supervisor response is not valid JSON: {exc}"
            ) from exc

        # Attach model routing audit fields
        supervisor_resp.requested_model = requested_model
        supervisor_resp.actual_model = actual_model
        supervisor_resp.fallback_reason = fallback_reason

        # Self-review guard: if the reviewer is the same model family as Hermes worker
        supervisor_resp = _apply_self_review_guard(supervisor_resp)

        # Human-only gate — hard block regardless of model output
        if _is_blocked_action(supervisor_resp.recommended_action):
            raise SupervisorBlockedActionError(
                f"Blocked action '{supervisor_resp.recommended_action}' detected. "
                "Human approval required."
            )

        return supervisor_resp

    def primary_check(self, prompt: str, system: str | None = None) -> SupervisorResponse:
        """Convenience wrapper for PRIMARY_SUPERVISOR."""
        return self.route(SupervisorTaskType.PRIMARY_SUPERVISOR, prompt, system=system)

    def code_review(self, prompt: str, system: str | None = None) -> SupervisorResponse:
        """Convenience wrapper for CODE_REVIEW."""
        return self.route(SupervisorTaskType.CODE_REVIEW, prompt, system=system)

    def reasoning_fallback(self, prompt: str, system: str | None = None) -> SupervisorResponse:
        """Convenience wrapper for REASONING_FALLBACK."""
        return self.route(SupervisorTaskType.REASONING_FALLBACK, prompt, system=system)

    def draft_review(self, prompt: str, system: str | None = None) -> SupervisorResponse:
        """Convenience wrapper for DRAFT_REVIEW."""
        return self.route(SupervisorTaskType.DRAFT_REVIEW, prompt, system=system)

    def long_context_review(self, prompt: str, system: str | None = None) -> SupervisorResponse:
        """Convenience wrapper for LONG_CONTEXT_REVIEW (Nemotron, etc.)."""
        return self.route(SupervisorTaskType.LONG_CONTEXT_REVIEW, prompt, system=system)

    def check_blocked(self, recommended_action: str) -> dict[str, Any]:
        """Explicitly test whether a recommended action would be blocked.

        Useful for CLI diagnostics and dry-run audits.
        """
        blocked = _is_blocked_action(recommended_action)
        return {
            "action": recommended_action,
            "blocked": blocked,
            "block_reason": (
                "Blocked by human-only gate. Requires operator approval." if blocked else ""
            ),
        }

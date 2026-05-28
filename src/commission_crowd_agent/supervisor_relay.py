"""Supervisor Relay — routes AI supervision tasks to local/Hermes-routed models.

Never calls OpenAI API. All inference runs against the local Ollama-compatible
endpoint (or another local provider configured via ``SUPERVISOR_BASE_URL``).
Human-only gates are enforced programmatically regardless of model output.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import CcaSettings, load_settings


class SupervisorTaskType(StrEnum):
    """Canonical task types that route to distinct local models."""

    PRIMARY_SUPERVISOR = "primary_supervisor"
    CODE_REVIEW = "code_review"
    REASONING_FALLBACK = "reasoning_fallback"
    DRAFT_REVIEW = "draft_review"


class SupervisorBlockedActionError(Exception):
    """Raised when the model output suggests a blocked action."""


class SupervisorResponseValidationError(Exception):
    """Raised when the model JSON does not match the expected schema."""


class SupervisorResponse(BaseModel):
    """Strict JSON schema for every supervisor response.

    Fields:
        approved: bool — whether the supervisor approves proceeding.
        reason: str — human-readable rationale.
        recommended_action: str — downstream action (may trigger a block).
        risk_level: str — low | medium | high | unknown.
        notes: str — free-form additional context.
    """

    approved: bool = Field(default=False)
    reason: str = Field(default="", max_length=2000)
    recommended_action: str = Field(default="", max_length=500)
    risk_level: str = Field(default="unknown")
    notes: str = Field(default="", max_length=2000)

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
    for verb in BLOCKED_ACTION_VERBS:
        if normalized.startswith(f"{verb}_"):
            return True
    return False


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
            SupervisorTaskType.PRIMARY_SUPERVISOR: self.settings.supervisor_primary_model,
            SupervisorTaskType.CODE_REVIEW: self.settings.supervisor_code_review_model,
            SupervisorTaskType.REASONING_FALLBACK: self.settings.supervisor_reasoning_fallback_model,
            SupervisorTaskType.DRAFT_REVIEW: self.settings.supervisor_draft_review_model,
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
            SupervisorResponseValidationError: If the model output violates the schema.
            SupervisorBlockedActionError: If the model suggests a blocked action.
        """
        if not self.enabled:
            raise RuntimeError("Supervisor Relay is not enabled (SUPERVISOR_MODE != local)")

        model = self._model_map.get(task_type)
        if not model:
            raise ValueError(f"No model configured for task type {task_type.value}")

        if self.dry_run:
            return SupervisorResponse(
                approved=False,
                reason="Dry-run mode — no inference performed.",
                recommended_action="",
                risk_level="unknown",
                notes="",
            )

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
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

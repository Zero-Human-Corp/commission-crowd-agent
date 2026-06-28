"""Browser automation facade — Playwright form submission and shadow validation.

This module re-exports the existing :class:`FormSubmissionEngine` and
:class:`FormShadowValidator` and provides ``asyncio`` wrappers so that the
Sprint 3 integration tests can use ``pytest.mark.asyncio`` without forcing a
rewrite of the battle-tested synchronous Playwright implementation.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .form_shadow_validator import (
    FormShadowValidator,
    OperatorInterventionRequired,
    ShadowValidationResult,
)
from .form_submission_engine import (
    FormSubmissionEngine,
    SubmissionEligibility,
    SubmissionResult,
)

__all__ = [
    "AsyncFormShadowValidator",
    "AsyncFormSubmissionEngine",
    "FormShadowValidator",
    "FormSubmissionEngine",
    "OperatorInterventionRequired",
    "ShadowValidationResult",
    "SubmissionEligibility",
    "SubmissionResult",
]


class AsyncFormShadowValidator:
    """Async wrapper around :class:`FormShadowValidator`.

    Runs the synchronous Playwright validator in a thread-pool executor so it
    can be awaited from ``pytest.mark.asyncio`` tests and async orchestrators.
    """

    def __init__(
        self,
        browser_adapter: Any,
        reports_dir: str = "/home/ubuntu/hermes-control/reports/form_validation_failures",
    ) -> None:
        self._validator = FormShadowValidator(
            browser_adapter=browser_adapter, reports_dir=reports_dir
        )

    async def validate(
        self,
        form_url: str,
        payload: dict[str, Any],
        payload_hash: str,
        field_mapping: dict[str, dict[str, str]],
        *,
        opportunity_id: str = "",
        principal_name: str = "",
        dom_fixture: str | None = None,
        dry_run: bool = False,
    ) -> ShadowValidationResult:
        """Run the shadow validator asynchronously.

        Mirrors :meth:`FormShadowValidator.validate` so async callers use the
        same keyword contract as the synchronous production path.
        """
        return await asyncio.to_thread(
            self._validator.validate,
            form_url,
            payload,
            payload_hash,
            field_mapping,
            opportunity_id=opportunity_id,
            principal_name=principal_name,
            dom_fixture=dom_fixture,
            dry_run=dry_run,
        )


class AsyncFormSubmissionEngine:
    """Async wrapper around :class:`FormSubmissionEngine`.

    Mirrors the public API of the synchronous engine and delegates each call to
    a thread-pool executor.  This keeps the production path synchronous and
    testable while letting async integration tests exercise the full guard
    chain (approval gate, supervisor checkpoint, shadow validator, audit).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._engine = FormSubmissionEngine(*args, **kwargs)

    def attach_registry(self, registry: Any) -> None:
        """Wire the opportunity state registry."""
        self._engine.attach_registry(registry)

    def can_submit(self, opportunity_id: str) -> SubmissionEligibility:
        """Return synchronous eligibility info (read-only)."""
        return self._engine.can_submit(opportunity_id)

    async def submit_application(
        self,
        opportunity_id: str,
        approval_id: str,
        *,
        dry_run: bool = True,
    ) -> SubmissionResult:
        """Submit (or simulate submitting) an approved application asynchronously."""
        return await asyncio.to_thread(
            self._engine.submit_application,
            opportunity_id,
            approval_id,
            dry_run=dry_run,
        )

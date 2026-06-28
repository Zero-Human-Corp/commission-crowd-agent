"""Form submission engine — gated application submission to CommissionCrowd.

The engine is the only component permitted to perform consequential form posts.
It verifies opportunity state, human approval, supervisor checkpoint, shadow
validation, idempotency, and daily volume limits before filling and optionally
submitting an approved application form.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .approval_gate import ApprovalGate
from .config import CcaSettings, load_settings
from .form_shadow_validator import (
    FormShadowValidator,
    OperatorInterventionRequired,
    ShadowValidationResult,
)
from .mvp_pipeline import generate_application_draft
from .state_registry import (
    LIFECYCLE_APPLICATION_APPROVED,
    LIFECYCLE_APPLICATION_SUBMITTED,
    OpportunityStateRegistry,
)
from .submission_audit import SubmissionAuditModule, SubmissionAuditRecord, hash_payload
from .supervisor_relay import (
    SupervisorBlockedActionError,
    SupervisorRelay,
    SupervisorResponse,
    SupervisorTaskType,
)
from .workflows.approvals import migrate_lifecycle_state

DEFAULT_ACTION = "apply_to_principal"


@dataclass
class SubmissionEligibility:
    """Eligibility result returned by ``can_submit``."""

    opportunity_id: str = ""
    eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    current_state: str = ""
    approval_approved: bool = False
    daily_count: int = 0
    daily_limit: int = 0
    idempotent_record_id: str | None = None


@dataclass
class SubmissionResult:
    """Result of a ``submit_application`` call."""

    ok: bool = False
    opportunity_id: str = ""
    approval_id: str = ""
    audit_id: str | None = None
    dry_run: bool = True
    state_migrated: bool = False
    supervisor_checkpoint: dict[str, Any] = field(default_factory=dict)
    shadow_validation: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    operator_notified: bool = False


class FormSubmissionEngine:
    """Gated form-submission engine for CommissionCrowd applications."""

    def __init__(
        self,
        browser: Any,
        gate: ApprovalGate,
        supervisor: SupervisorRelay,
        audit: SubmissionAuditModule,
        settings: CcaSettings | None = None,
    ) -> None:
        self.browser = browser
        self.gate = gate
        self.supervisor = supervisor
        self.audit = audit
        self.settings = settings or load_settings()
        self._state_registry: OpportunityStateRegistry | None = None
        self._shadow_validator = FormShadowValidator(browser_adapter=browser)

    def _get_registry(self) -> OpportunityStateRegistry:
        """Return the opportunity state registry attached to the engine.

        If none has been attached, an empty registry is returned. Callers
        should wire the registry before production use.
        """
        return self._state_registry or OpportunityStateRegistry()

    def attach_registry(self, registry: OpportunityStateRegistry) -> None:
        """Wire the opportunity state registry used for state checks/migration."""
        self._state_registry = registry

    def can_submit(self, opportunity_id: str) -> SubmissionEligibility:
        """Return eligibility info for the given opportunity.

        Checks:
          - opportunity exists in registry
          - lifecycle state is ``application_approved``
          - daily volume limit has not been reached
          - no recent successful/dry-run audit record implies idempotency concern
          - supervisor relay is enabled (the live checkpoint runs in submit_application)
        """
        reasons: list[str] = []
        registry = self._get_registry()
        record = registry.get_by_id(opportunity_id)
        if record is None:
            reasons.append("Opportunity not found in state registry")
            return SubmissionEligibility(
                opportunity_id=opportunity_id,
                eligible=False,
                reasons=reasons,
            )

        current_state = record.lifecycle_state
        if current_state != LIFECYCLE_APPLICATION_APPROVED:
            reasons.append(f"Lifecycle state is '{current_state}', expected 'application_approved'")

        if not self.supervisor.enabled:
            reasons.append("Supervisor relay is not enabled (SUPERVISOR_MODE != local)")

        daily_limit = self.settings.cca_daily_volume_limit
        daily_count = self.audit.count_today(DEFAULT_ACTION)
        if daily_count >= daily_limit:
            reasons.append(f"Daily volume limit reached ({daily_count}/{daily_limit})")

        # Build a representative payload hash for idempotency pre-check.
        payload, _draft = self._build_payload(record)
        payload_hash = hash_payload(payload)
        existing = self.audit.has_submission(opportunity_id, DEFAULT_ACTION, payload_hash)
        if existing is not None:
            reasons.append(f"Recent submission audit record exists: {existing.audit_id}")

        eligible = not reasons
        return SubmissionEligibility(
            opportunity_id=opportunity_id,
            eligible=eligible,
            reasons=reasons,
            current_state=current_state,
            approval_approved=False,  # checked separately per approval_id
            daily_count=daily_count,
            daily_limit=daily_limit,
            idempotent_record_id=existing.audit_id if existing else None,
        )

    def _build_payload(self, record: Any) -> tuple[dict[str, Any], dict[str, str]]:
        """Build the application payload and draft from a registry record.

        Uses :func:`mvp_pipeline.generate_application_draft` when the record can
        be converted to a :class:`CanonicalOpportunity`; otherwise falls back to
        a minimal identity-only payload.  Returns ``(payload, draft)`` so callers
        can audit the draft text alongside the hashed payload.
        """
        record_dict = record.to_dict() if hasattr(record, "to_dict") else dict(record)
        canonical = getattr(record, "to_canonical_opportunity", lambda: None)()

        draft: dict[str, str] = {}
        if canonical is not None:
            try:
                draft = generate_application_draft(canonical, self.settings)
            except Exception:  # noqa: BLE001 - draft generation must not crash the engine
                draft = {}

        if not draft:
            fallback_title = record_dict.get("title", "")
            draft = {
                "subject": (
                    f"Independent Sales Representative Application — {fallback_title}"
                ),
                "body": "",
            }

        # Payload is a flat map of form fields the engine intends to submit.
        # The draft text is included as ``subject``/``body`` so the shadow
        # validator can verify the rendered form accepts it; the draft dict is
        # also returned separately so it can be audited alongside the hash.
        payload: dict[str, Any] = {
            "opportunity_id": record_dict.get("opportunity_id", ""),
            "principal_name": record_dict.get("principal_name", ""),
            "title": record_dict.get("title", ""),
            "source_url": record_dict.get("source_url", ""),
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "action": DEFAULT_ACTION,
        }
        return payload, draft

    def _build_field_mapping(self, draft: dict[str, str]) -> dict[str, dict[str, str]]:
        """Return a best-effort form field mapping for the application draft."""
        return {
            "subject": {"selector": 'input[name="subject"]', "type": "text"},
            "body": {"selector": 'textarea[name="body"]', "type": "textarea"},
            "opportunity_id": {"selector": 'input[name="opportunity_id"]', "type": "text"},
            "principal_name": {"selector": 'input[name="principal_name"]', "type": "text"},
            "title": {"selector": 'input[name="title"]', "type": "text"},
            "source_url": {"selector": 'input[name="source_url"]', "type": "url"},
            "action": {"selector": 'input[name="action"]', "type": "hidden"},
        }

    def _compute_form_url(self, record: Any) -> str:
        """Resolve the application form URL for an opportunity."""
        record_dict = record.to_dict() if hasattr(record, "to_dict") else dict(record)
        source_url: str = str(record_dict.get("source_url", "") or "")
        opportunity_id: str = str(record_dict.get("opportunity_id", "") or "")
        if source_url and "commissioncrowd.com" in source_url:
            return source_url
        return f"https://www.commissioncrowd.com/opportunities/{opportunity_id}/apply"

    def _fill_form(self, payload: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
        """Fill form fields via the browser adapter without clicking submit.

        In dry-run mode the submit button is never clicked. In live mode the
        engine clicks only after all other guards pass.
        """
        page = getattr(self.browser, "_page", None)
        if page is None:
            raise RuntimeError("Browser page not available; call start() first.")

        filled: dict[str, Any] = {}
        for key, value in payload.items():
            if not value:
                continue
            # Heuristic selector: try input[name=key] and textarea[name=key]
            selectors = [
                f'input[name="{key}"]',
                f'textarea[name="{key}"]',
                f'[data-field="{key}"]',
            ]
            for selector in selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.fill(selector, str(value))
                        filled[key] = selector
                        break
                except Exception:
                    continue

        result: dict[str, Any] = {
            "filled_fields": filled,
            "submit_clicked": False,
            "dry_run": dry_run,
        }

        if not dry_run:
            # Locate a reasonable submit button and click it.
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                "button:has-text('Apply')",
                "button:has-text('Submit')",
                "[data-testid='submit-button']",
            ]
            for selector in submit_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.click(selector)
                        result["submit_clicked"] = True
                        result["submit_selector"] = selector
                        break
                except Exception:
                    continue
            if not result["submit_clicked"]:
                raise RuntimeError("Submit button not found on application form")

        return result

    def _checkpoint_to_dict(self, resp: SupervisorResponse | None) -> dict[str, Any]:
        """Convert a SupervisorResponse to an audit-friendly dict."""
        if resp is None:
            return {"ok": False, "error": "No supervisor response"}
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
            "review_independence": resp.review_independence,
        }

    def submit_application(
        self,
        opportunity_id: str,
        approval_id: str,
        *,
        dry_run: bool = True,
    ) -> SubmissionResult:
        """Submit (or simulate submitting) an approved application.

        Steps:
          1. Verify opportunity state is ``application_approved``.
          2. Check ``ApprovalGate.is_approved(approval_id)``.
          3. Run a SupervisorRelay checkpoint (CODE_REVIEW or DRAFT_REVIEW).
          4. Run ``FormShadowValidator.validate()``.
          5. Check idempotency and daily volume limit.
          6. Fill form via browser adapter.
          7. Click submit only when ``dry_run=False``.
          8. Write an audit record.
          9. Migrate state to ``application_submitted`` only on success and not dry_run.
        """
        result = SubmissionResult(
            opportunity_id=opportunity_id,
            approval_id=approval_id,
            dry_run=dry_run,
        )

        registry = self._get_registry()
        record = registry.get_by_id(opportunity_id)
        if record is None:
            result.error = "Opportunity not found in state registry"
            self._write_audit(result, status="aborted")
            return result

        # 1. State guard
        if record.lifecycle_state != LIFECYCLE_APPLICATION_APPROVED:
            result.error = (
                f"Opportunity state is '{record.lifecycle_state}', "
                f"expected '{LIFECYCLE_APPLICATION_APPROVED}'"
            )
            self._write_audit(result, status="aborted")
            return result

        # 2. Approval gate — fail closed before any page mutation.
        if not self.gate.is_approved(approval_id):
            result.error = f"Approval {approval_id} is not approved"
            self._write_audit(result, status="aborted")
            return result

        payload, draft = self._build_payload(record)
        payload_hash = hash_payload(payload)

        # 3. Supervisor checkpoint — submission plan review (DRAFT_REVIEW per spec §6.1).
        supervisor_checkpoint: SupervisorResponse | None = None
        try:
            prompt = self._supervisor_prompt(opportunity_id, payload)
            supervisor_checkpoint = self.supervisor.route(
                SupervisorTaskType.DRAFT_REVIEW, prompt
            )
            result.supervisor_checkpoint = self._checkpoint_to_dict(supervisor_checkpoint)
            if not result.supervisor_checkpoint.get("ok"):
                cp_reason = result.supervisor_checkpoint.get("reason", "")
                result.error = f"Supervisor checkpoint not ok: {cp_reason}"
                self._write_audit(result, status="aborted", payload_hash=payload_hash)
                return result
        except SupervisorBlockedActionError as exc:
            result.error = f"Supervisor blocked action: {exc}"
            result.supervisor_checkpoint = {"ok": False, "error": str(exc)}
            self._write_audit(result, status="aborted", payload_hash=payload_hash)
            return result
        except Exception as exc:
            result.error = f"Supervisor checkpoint failed: {exc}"
            result.supervisor_checkpoint = {"ok": False, "error": str(exc)}
            self._write_audit(result, status="aborted", payload_hash=payload_hash)
            return result

        # 4. Shadow validation against the live or structural form shadow.
        form_url = self._compute_form_url(record)
        field_mapping = self._build_field_mapping(draft)
        try:
            shadow_result: ShadowValidationResult = self._shadow_validator.validate(
                form_url,
                payload,
                payload_hash,
                field_mapping,
                opportunity_id=opportunity_id,
                principal_name=record.principal_name,
                dry_run=dry_run,
            )
            result.shadow_validation = shadow_result.to_dict()
            if not shadow_result.ok:
                result.error = (
                    "Shadow validation failed: "
                    + "; ".join(shadow_result.mismatches)
                )
                self._write_audit(result, status="aborted", payload_hash=payload_hash)
                return result
        except OperatorInterventionRequired as exc:
            result.error = f"Operator intervention required: {exc}"
            result.shadow_validation = {"ok": False, "error": str(exc)}
            self._write_audit(result, status="aborted", payload_hash=payload_hash)
            return result
        except Exception as exc:
            result.error = f"Shadow validation error: {exc}"
            result.shadow_validation = {"ok": False, "error": str(exc)}
            self._write_audit(result, status="aborted", payload_hash=payload_hash)
            return result

        # 5. Idempotency and daily volume limit
        existing = self.audit.has_submission(opportunity_id, DEFAULT_ACTION, payload_hash)
        if existing is not None:
            result.error = (
                f"Idempotency guard: recent submission exists ({existing.audit_id})"
            )
            result.audit_id = existing.audit_id
            self._write_audit(result, status="aborted", payload_hash=payload_hash)
            return result

        daily_count = self.audit.count_today(DEFAULT_ACTION)
        daily_limit = self.settings.cca_daily_volume_limit
        if daily_count >= daily_limit:
            result.error = f"Daily volume limit reached ({daily_count}/{daily_limit})"
            self._write_audit(result, status="aborted", payload_hash=payload_hash)
            return result

        # 6/7. Fill form and click submit only on a real (non-dry-run) run.
        fill_result: dict[str, Any] = {}
        if not dry_run:
            try:
                fill_result = self._fill_form(payload, dry_run=False)
            except Exception as exc:
                result.error = f"Form fill failed: {exc}"
                self._write_audit(result, status="failed", payload_hash=payload_hash)
                return result

        # 8. Always append an audit record.
        status = "dry_run" if dry_run else "success"
        audit_record = self._write_audit(
            result,
            status=status,
            payload_hash=payload_hash,
            extra={"fill_result": fill_result, "draft": draft} if not dry_run else {"draft": draft},
        )
        result.audit_id = audit_record.audit_id
        result.ok = True

        # 9. Migrate lifecycle state only on a real successful submission.
        if not dry_run:
            migration = migrate_lifecycle_state(
                registry,
                opportunity_id,
                LIFECYCLE_APPLICATION_SUBMITTED,
                from_states={LIFECYCLE_APPLICATION_APPROVED},
            )
            if not migration.get("ok"):
                # State guard refused the transition — surface but keep audit success.
                result.error = (
                    f"State migration failed: {migration.get('error', 'unknown')}"
                )
                result.state_migrated = False
            else:
                record.add_provenance(
                    source="form_submission_engine",
                    route="submit_application",
                )
                result.state_migrated = True

        return result

    def _supervisor_prompt(self, opportunity_id: str, payload: dict[str, Any]) -> str:
        """Build the supervisor prompt for the submission plan review."""
        return (
            "Review the following CommissionCrowd application submission plan. "
            "The action is 'apply_to_principal'. "
            "Confirm the payload is truthful, the target opportunity is known, "
            "and the recommended action is safe. "
            "Return a JSON object with approved (boolean), reason (string), "
            "risk_level (low|medium|high|unknown), and recommended_action (string).\n\n"
            f"Opportunity ID: {opportunity_id}\n"
            f"Payload: {json.dumps(payload, sort_keys=True, default=str)}"
        )

    def _write_audit(
        self,
        result: SubmissionResult,
        status: str,
        payload_hash: str = "",
        extra: dict[str, Any] | None = None,
    ) -> SubmissionAuditRecord:
        """Persist an audit record for the current submission step."""
        record = SubmissionAuditRecord(
            opportunity_id=result.opportunity_id,
            approval_id=result.approval_id,
            action=DEFAULT_ACTION,
            status=status,
            payload_hash=payload_hash,
            supervisor_checkpoint=result.supervisor_checkpoint,
            shadow_validation=result.shadow_validation,
            error=result.error,
            operator_notified=result.operator_notified,
            dry_run=result.dry_run,
        )
        if extra:
            record.supervisor_checkpoint = {
                **record.supervisor_checkpoint,
                "_engine_extra": extra,
            }
        self.audit.append(record)
        return record

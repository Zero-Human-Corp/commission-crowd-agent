"""Sprint 3 milestone tests — async integration suite.

Uses ``pytest.mark.asyncio`` to exercise the end-to-end report-fetching loop,
Google Sheets tracking, row-level deduplication, Pydantic schema validation,
and the shadow/form-submission engine guard chain.  All external systems are
replaced by injected fakes; no live browser, network, or supervisor inference
is performed.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from commission_crowd_agent.adapters import GoogleSheetsAdapter
from commission_crowd_agent.browser_automation import (
    AsyncFormShadowValidator,
    AsyncFormSubmissionEngine,
    FormShadowValidator,
    OperatorInterventionRequired,
)
from commission_crowd_agent.candidate_identity import IdentityVerificationResult
from commission_crowd_agent.config import CcaSettings
from commission_crowd_agent.models.report_schema import (
    CommissionReportSchema,
    ReportMetadataEngine,
    ReportProvenanceEntry,
)
from commission_crowd_agent.report_fetcher import CommissionReportFetcher
from commission_crowd_agent.report_registry import (
    CommissionReport,
    ReportRegistry,
)
from commission_crowd_agent.state_registry import (
    LIFECYCLE_APPLICATION_APPROVED,
    OpportunityStateRegistry,
)
from commission_crowd_agent.submission_audit import (
    SubmissionAuditModule,
    SubmissionAuditRecord,
    hash_payload,
)
from commission_crowd_agent.supervisor_relay import (
    SupervisorBlockedActionError,
    SupervisorResponse,
    SupervisorTaskType,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Settings / fakes
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> CcaSettings:
    defaults: dict[str, Any] = {
        "supervisor_mode": "local",
        "supervisor_base_url": "http://localhost:9999/v1",
        "supervisor_api_key": "",
        "supervisor_primary_model": "glm-5.1",
        "supervisor_code_review_model": "qwen3-coder-next",
        "supervisor_reasoning_fallback_model": "deepseek-v3.2",
        "supervisor_draft_review_model": "kimi-k2-thinking",
        "supervisor_long_context_model": "nemotron-3-super:cloud",
        "supervisor_emergency_fallback_model": "kimi-k2.6:cloud",
        "supervisor_allow_fallback": False,
        "supervisor_fallback_model": "",
        "supervisor_telegram_notify": False,
        "smtp_port": 587,
        "cca_daily_volume_limit": 50,
    }
    defaults.update(overrides)
    return CcaSettings(**defaults)


class FakeApiAdapter:
    """CommissionCrowd API double returning an empty opportunity list."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def token_present(self) -> bool:
        self.calls.append("token_present")
        return False

    def list_opportunities(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("list_opportunities")
        return {"ok": True, "data": {"items": []}}

    def get_opportunity(self, _opportunity_id: int) -> dict[str, Any]:
        return {"ok": False, "error": "no token"}


class FakeBrowserAdapter:
    """Browser adapter double exposing ``list_my_opportunities`` and ``_page``."""

    def __init__(self, opportunities: list[dict[str, Any]] | None = None) -> None:
        self.opportunities = opportunities or []
        self.calls: list[str] = []

    def list_my_opportunities(self) -> list[dict[str, Any]]:
        self.calls.append("list_my_opportunities")
        return self.opportunities

    @property
    def _page(self) -> None:
        return None


class RecordingSheetsAdapter(GoogleSheetsAdapter):
    """Google Sheets double that records every append without network."""

    def __init__(self) -> None:  # noqa: D107
        self.appended: list[tuple[str, list[str]]] = []

    def append_row(self, tab: str, values: list[str]) -> dict[str, Any]:
        self.appended.append((tab, values))
        return {"ok": True, "action": "append_row", "tab": tab, "rows_changed": 1}

    def health_check(self) -> dict[str, Any]:
        return {"ok": True}


# ---------------------------------------------------------------------------
# Fake Playwright page / locator
# ---------------------------------------------------------------------------


def _selector_to_field_name(selector: str) -> str | None:
    """Extract a field name from the simple selectors the validator uses."""
    for pattern in (
        r'(?:name|id|aria-label)=["\']([^"\']+)["\']',
        r'\[data-field=["\']([^"\']+)["\']\]',
        r'\[data-name=["\']([^"\']+)["\']\]',
    ):
        m = re.search(pattern, selector)
        if m:
            return m.group(1)
    return None


@dataclass
class FakeLocator:
    """Minimal Playwright locator double backed by a ``FakePage``."""

    selector: str
    page: FakePage

    def count(self) -> int:
        if self.page.fields_hidden:
            return 0
        # Field locators
        field_name = _selector_to_field_name(self.selector)
        if field_name and field_name in self.page.fields:
            return 1
        # Submit-button-like locators
        lower = self.selector.lower()
        html = self.page.content_html.lower()
        if 'type="submit"' in lower and ('<button' in html or '<input' in html):
            return 1
        if ":has-text('apply')" in lower and "apply" in html:
            return 1
        if ":has-text('submit')" in lower and "submit" in html:
            return 1
        if "data-testid='submit-button'" in lower:
            return 1
        return 0

    @property
    def first(self) -> FakeLocator:
        return self

    def fill(self, value: str) -> None:
        self.page.filled.append((self.selector, value))

    def click(self) -> None:
        self.page.clicked.append(self.selector)

    def get_attribute(self, name: str) -> str | None:
        field_name = _selector_to_field_name(self.selector)
        if field_name and field_name in self.page.fields:
            tag, itype = self.page.fields[field_name]
            if name == "type":
                return itype
            if name == "tag":
                return tag
        return None

    def evaluate(self, _script: str) -> str:
        field_name = _selector_to_field_name(self.selector)
        if field_name and field_name in self.page.fields:
            return self.page.fields[field_name][0]
        return ""


@dataclass
class FakePage:
    """Static HTML-backed Playwright page double."""

    content_html: str
    url_value: str = "https://www.commissioncrowd.com/opportunities/OPP-1/apply"
    fields: dict[str, tuple[str, str]] = field(default_factory=dict)
    fields_hidden: bool = False
    filled: list[tuple[str, str]] = field(default_factory=list)
    clicked: list[str] = field(default_factory=list)
    goto_calls: list[str] = field(default_factory=list)
    screenshot_paths: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return self.url_value

    def goto(self, url: str, **_kwargs: Any) -> None:
        self.goto_calls.append(url)
        self.url_value = url

    def wait_for_timeout(self, _ms: int) -> None:
        return

    def content(self) -> str:
        return self.content_html

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(selector=selector, page=self)

    def fill(self, selector: str, value: str) -> None:
        self.filled.append((selector, value))

    def click(self, selector: str) -> None:
        self.clicked.append(selector)

    def screenshot(self, *, path: str) -> None:
        self.screenshot_paths.append(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"PNG")


@dataclass
class FakeBrowser:
    """Browser adapter double exposing a ``_page`` attribute."""

    page: FakePage

    @property
    def _page(self) -> FakePage:
        return self.page


# ---------------------------------------------------------------------------
# Approval / supervisor fakes
# ---------------------------------------------------------------------------


class FakeApprovalGate:
    def __init__(self, approved_ids: set[str] | None = None) -> None:
        self._approved = approved_ids or set()

    def is_approved(self, approval_id: str) -> bool:
        return approval_id in self._approved


class FakeSupervisorRelay:
    def __init__(
        self,
        *,
        response: SupervisorResponse | None = None,
        raise_blocked: bool = False,
    ) -> None:
        self._response = response
        self._raise_blocked = raise_blocked
        self.route_calls: list[tuple[SupervisorTaskType, str]] = []

    @property
    def enabled(self) -> bool:
        return True

    def route(
        self,
        task_type: SupervisorTaskType,
        prompt: str,
        system: str | None = None,
    ) -> SupervisorResponse:
        self.route_calls.append((task_type, prompt))
        if self._raise_blocked:
            raise SupervisorBlockedActionError("blocked: apply")
        if self._response is not None:
            return self._response
        return SupervisorResponse(
            approved=True,
            reason="fake approve",
            recommended_action="proceed",
            risk_level="low",
            human_approval_required=False,
        )


def _approved_response() -> SupervisorResponse:
    return SupervisorResponse(
        approved=True,
        reason="fake approve",
        recommended_action="proceed",
        risk_level="low",
        human_approval_required=False,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _well_formed_payload() -> dict[str, Any]:
    return {
        "opportunity_id": "OPP-1",
        "principal_name": "SecureFlow Inc",
        "title": "Cybersecurity SaaS",
        "source_url": "",
        "action": "apply_to_principal",
        "submitted_at": "2026-06-28T12:00:00+00:00",
    }


def _well_formed_fields() -> dict[str, tuple[str, str]]:
    return {
        "opportunity_id": ("input", "text"),
        "principal_name": ("input", "text"),
        "title": ("input", "text"),
        "source_url": ("input", "text"),
        "action": ("input", "text"),
        "submitted_at": ("input", "text"),
    }


def _well_formed_field_mapping() -> dict[str, dict[str, str]]:
    """Field mapping matching :func:`_well_formed_fields` for the shadow validator."""
    return {
        name: {"selector": f'input[name="{name}"]', "type": "text"}
        for name in _well_formed_fields()
    }


def _well_formed_html() -> str:
    return (
        "<html><head><title>Apply to OPP-1</title></head><body>"
        "<form id='apply-form' data-opportunity-id='OPP-1'>"
        "<input name='opportunity_id' type='text' />"
        "<input name='principal_name' type='text' />"
        "<input name='title' type='text' />"
        "<input name='source_url' type='text' />"
        "<input name='action' type='text' />"
        "<input name='submitted_at' type='text' />"
        "<h2>SecureFlow Inc</h2>"
        "</form></body></html>"
    )


def _approved_registry() -> OpportunityStateRegistry:
    registry = OpportunityStateRegistry()
    record = registry._get_or_create("OPP-1")
    record.title = "Cybersecurity SaaS"
    record.principal_name = "SecureFlow Inc"
    record.lifecycle_state = LIFECYCLE_APPLICATION_APPROVED
    # Production writes require explicit IDENTITY_VERIFIED + RECONCILED.
    record.record_identity_verification(
        IdentityVerificationResult.VERIFIED,
        disposition="RECONCILED",
    )
    return registry


# ---------------------------------------------------------------------------
# Async tests: report-fetching loop (M1-M3)
# ---------------------------------------------------------------------------


async def test_fetch_reports_dry_run_is_shadow_and_writesis_free(tmp_path: Path) -> None:
    registry = ReportRegistry(path=tmp_path / "registry.json")
    fetcher = CommissionReportFetcher(
        browser=None,
        api_adapter=None,
        settings=_make_settings(),
        registry=registry,
    )
    result = await asyncio.to_thread(fetcher.fetch_account_reports, dry_run=True, limit=10)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["added"] == 0
    assert result["fetched"] == 10
    assert not (tmp_path / "registry.json").exists()


async def test_fetch_reports_live_ingests_and_tracks_in_sheets(tmp_path: Path) -> None:
    registry = ReportRegistry(path=tmp_path / "registry.json")
    sheets = RecordingSheetsAdapter()
    opportunities = [
        {
            "opportunity_id": "OPP-1",
            "title": "Cybersecurity SaaS",
            "principal_name": "SecureFlow Inc",
            "commission_summary": "20% recurring",
            "source_url": "https://www.commissioncrowd.com/opportunities/1",
            "status": "active",
        },
        {
            "opportunity_id": "OPP-1",  # duplicate item to exercise row-level dedup
            "title": "Cybersecurity SaaS",
            "principal_name": "SecureFlow Inc",
            "commission_summary": "20% recurring",
            "source_url": "https://www.commissioncrowd.com/opportunities/1",
            "status": "active",
        },
        {
            "opportunity_id": "OPP-2",
            "title": "Fintech API",
            "principal_name": "PayPipe Ltd",
            "commission_summary": "15% first year",
            "source_url": "https://www.commissioncrowd.com/opportunities/2",
            "status": "active",
        },
    ]
    fetcher = CommissionReportFetcher(
        browser=FakeBrowserAdapter(opportunities=opportunities),
        api_adapter=FakeApiAdapter(),
        settings=_make_settings(),
        registry=registry,
        sheets_adapter=sheets,
    )

    result = await asyncio.to_thread(
        fetcher.fetch_account_reports, dry_run=False, limit=10
    )

    assert result["ok"] is True
    assert result["dry_run"] is False
    assert result["fetched"] == 2  # duplicate removed
    assert result["added"] == 2
    assert len(registry.list_reports()) == 2

    # A tracking row was appended for the run.
    assert len(sheets.appended) == 1
    tab, row = sheets.appended[0]
    assert tab == "reports_tracking"
    assert row[1] == "fetch_account_reports"
    assert int(row[3]) == 2  # added count


async def test_fetch_reports_bound_exceeded_fails_closed(tmp_path: Path) -> None:
    registry = ReportRegistry(path=tmp_path / "registry.json")
    fetcher = CommissionReportFetcher(
        browser=FakeBrowserAdapter(opportunities=[{"opportunity_id": f"OPP-{i}"} for i in range(150)]),
        api_adapter=None,
        settings=_make_settings(),
        registry=registry,
    )

    result = await asyncio.to_thread(fetcher.fetch_account_reports, dry_run=False, limit=100)

    assert result["ok"] is False
    assert "exceeding" in result["error"].lower()
    assert result["added"] == 0


async def test_fetch_opportunity_report_dry_run_returns_shadow(tmp_path: Path) -> None:
    registry = ReportRegistry(path=tmp_path / "registry.json")
    fetcher = CommissionReportFetcher(
        browser=None,
        api_adapter=None,
        settings=_make_settings(),
        registry=registry,
    )
    result = await asyncio.to_thread(fetcher.fetch_opportunity_report, "OPP-1", dry_run=True)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["opportunity_id"] == "OPP-1"
    assert result["report_hash"]
    assert len(registry.list_reports()) == 0


# ---------------------------------------------------------------------------
# Async tests: Pydantic schemas and provenance (M2/M3)
# ---------------------------------------------------------------------------


async def test_report_schema_validates_and_computes_hash() -> None:
    schema = CommissionReportSchema(
        report_id="r-001",
        opportunity_id="OPP-1",
        principal_name="Principal A",
        report_type="earnings",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        currency="USD",
        gross_amount=1000.0,
        net_amount=950.0,
        status="confirmed",
        source_url="https://example.com/report/1",
        raw_fingerprint="fp-1",
    )
    assert schema.report_hash
    assert len(schema.report_hash) == 64

    engine_hash = ReportMetadataEngine.compute_report_hash(schema)
    assert engine_hash == schema.report_hash


async def test_report_provenance_entry_requires_utc() -> None:
    entry = ReportProvenanceEntry(
        source="browser", route="my_opportunities", retrieved_at=datetime(2026, 6, 28, 12, 0)
    )
    assert entry.retrieved_at.tzinfo is not None
    assert entry.retrieved_at.tzname() == "UTC"


async def test_dataclass_to_pydantic_round_trip_preserves_hash(tmp_path: Path) -> None:
    report = CommissionReport(
        report_id="r-001",
        opportunity_id="OPP-1",
        principal_name="Principal A",
        report_type="earnings",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        currency="USD",
        gross_amount=1000.0,
        net_amount=950.0,
        status="confirmed",
        source_url="https://example.com/report/1",
        raw_fingerprint="fp-1",
    )
    schema = report.to_pydantic()
    assert isinstance(schema, CommissionReportSchema)
    assert schema.report_hash == report.report_hash

    registry = ReportRegistry(path=tmp_path / "registry.json")
    registry.add_report_schema(schema, source="test", route="schema_bridge")
    assert len(registry.list_reports()) == 1
    assert registry.list_reports()[0].report_hash == report.report_hash


# ---------------------------------------------------------------------------
# Async tests: form shadow validator (M4)
# ---------------------------------------------------------------------------


async def test_async_shadow_validator_passes_well_formed_form(tmp_path: Path) -> None:
    page = FakePage(
        content_html=_well_formed_html(),
        url_value="https://www.commissioncrowd.com/opportunities/OPP-1/apply",
        fields=_well_formed_fields(),
    )
    validator = AsyncFormShadowValidator(browser_adapter=FakeBrowser(page=page))
    payload = _well_formed_payload()

    result = await validator.validate(
        "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
        payload,
        hash_payload(payload),
        _well_formed_field_mapping(),
        opportunity_id="OPP-1",
    )

    assert result.ok is True
    assert result.mismatches == []
    assert result.checks.get("page_reachable") is True
    assert result.checks.get("no_captcha_or_2fa") is True
    assert result.checks.get("required_fields_present") is True
    assert result.checks.get("field_type_compatible") is True
    assert result.checks.get("payload_hash_match") is True
    assert result.checks.get("opportunity_identity_verified") is True


async def test_async_shadow_validator_fails_missing_fields(tmp_path: Path) -> None:
    page = FakePage(
        content_html=_well_formed_html(),
        url_value="https://www.commissioncrowd.com/opportunities/OPP-1/apply",
        fields={k: v for k, v in _well_formed_fields().items() if k != "title"},
    )
    validator = AsyncFormShadowValidator(browser_adapter=FakeBrowser(page=page))
    payload = _well_formed_payload()

    result = await validator.validate(
        "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
        payload,
        hash_payload(payload),
        _well_formed_field_mapping(),
        opportunity_id="OPP-1",
    )

    assert result.ok is False
    assert result.checks.get("required_fields_present") is False
    assert any("title" in m for m in result.mismatches)
    assert result.screenshot_path or result.dom_snapshot_path


async def test_async_shadow_validator_aborts_on_captcha(tmp_path: Path) -> None:
    page = FakePage(
        content_html=(
            "<html><body><form>"
            "<p>Please complete the CAPTCHA to continue.</p>"
            "</form></body></html>"
        ),
        fields=_well_formed_fields(),
        fields_hidden=True,
    )
    validator = AsyncFormShadowValidator(browser_adapter=FakeBrowser(page=page))
    payload = _well_formed_payload()

    # A CAPTCHA/challenge page aborts hard with OperatorInterventionRequired so
    # the engine can route the opportunity into the operator-only flow.
    with pytest.raises(OperatorInterventionRequired, match="CAPTCHA"):
        await validator.validate(
            "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
            payload,
            hash_payload(payload),
            _well_formed_field_mapping(),
            opportunity_id="OPP-1",
        )


async def test_sync_validator_runs_under_thread(tmp_path: Path) -> None:
    """Smoke test that the sync validator can be called directly (not async)."""
    page = FakePage(
        content_html=_well_formed_html(),
        fields=_well_formed_fields(),
    )
    validator = FormShadowValidator(browser_adapter=FakeBrowser(page=page))
    payload = _well_formed_payload()

    result = validator.validate(
        "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
        payload,
        hash_payload(payload),
        _well_formed_field_mapping(),
        opportunity_id="OPP-1",
    )

    assert result.ok is True


# ---------------------------------------------------------------------------
# Async tests: form submission engine (M5-M7)
# ---------------------------------------------------------------------------


async def test_async_engine_dry_run_succeeds_and_writes_audit(tmp_path: Path) -> None:
    page = FakePage(content_html=_well_formed_html(), fields=_well_formed_fields())
    audit = SubmissionAuditModule(audit_path=tmp_path / "audit.jsonl")
    settings = _make_settings(cca_daily_volume_limit=50)
    engine = AsyncFormSubmissionEngine(
        browser=FakeBrowser(page=page),
        gate=FakeApprovalGate(approved_ids={"A42"}),
        supervisor=FakeSupervisorRelay(response=_approved_response()),
        audit=audit,
        settings=settings,
    )
    engine.attach_registry(_approved_registry())

    result = await engine.submit_application("OPP-1", "A42", dry_run=True)

    assert result.ok is True
    assert result.dry_run is True
    assert result.audit_id is not None
    assert result.error == ""
    records = audit._read_records()
    assert any(r.status == "dry_run" for r in records)
    assert not page.clicked
    assert not page.filled


async def test_async_engine_blocked_supervisor_aborts(tmp_path: Path) -> None:
    page = FakePage(content_html=_well_formed_html(), fields=_well_formed_fields())
    audit = SubmissionAuditModule(audit_path=tmp_path / "audit.jsonl")
    engine = AsyncFormSubmissionEngine(
        browser=FakeBrowser(page=page),
        gate=FakeApprovalGate(approved_ids={"A42"}),
        supervisor=FakeSupervisorRelay(raise_blocked=True),
        audit=audit,
        settings=_make_settings(),
    )
    engine.attach_registry(_approved_registry())

    result = await engine.submit_application("OPP-1", "A42", dry_run=True)

    assert result.ok is False
    assert "Supervisor blocked action" in result.error
    records = audit._read_records()
    assert any(r.status == "aborted" for r in records)


async def test_async_engine_unapproved_gate_fails_closed(tmp_path: Path) -> None:
    page = FakePage(content_html=_well_formed_html(), fields=_well_formed_fields())
    supervisor = FakeSupervisorRelay(response=_approved_response())
    audit = SubmissionAuditModule(audit_path=tmp_path / "audit.jsonl")
    engine = AsyncFormSubmissionEngine(
        browser=FakeBrowser(page=page),
        gate=FakeApprovalGate(approved_ids=set()),
        supervisor=supervisor,
        audit=audit,
        settings=_make_settings(),
    )
    engine.attach_registry(_approved_registry())

    result = await engine.submit_application("OPP-1", "A42", dry_run=True)

    assert result.ok is False
    assert "not approved" in result.error
    assert supervisor.route_calls == []
    records = audit._read_records()
    assert any(r.status == "aborted" for r in records)


async def test_async_engine_idempotency_skips_duplicate(tmp_path: Path) -> None:
    page = FakePage(content_html=_well_formed_html(), fields=_well_formed_fields())
    audit = SubmissionAuditModule(audit_path=tmp_path / "audit.jsonl")
    engine = AsyncFormSubmissionEngine(
        browser=FakeBrowser(page=page),
        gate=FakeApprovalGate(approved_ids={"A42"}),
        supervisor=FakeSupervisorRelay(response=_approved_response()),
        audit=audit,
        settings=_make_settings(),
    )
    engine.attach_registry(_approved_registry())
    # Freeze payload so the hash is deterministic across the seed and the call.
    fixed_payload = {
        "opportunity_id": "OPP-1",
        "principal_name": "SecureFlow Inc",
        "title": "Cybersecurity SaaS",
        "source_url": "",
        "subject": "Independent Sales Representative Application - Cybersecurity SaaS",
        "body": "",
        "action": "apply_to_principal",
    }
    fixed_draft: dict[str, str] = {"subject": fixed_payload["subject"], "body": ""}
    engine._engine._build_payload = lambda _record: (fixed_payload, fixed_draft)  # type: ignore[method-assign]

    seed = SubmissionAuditRecord(
        opportunity_id="OPP-1",
        approval_id="A42",
        action="apply_to_principal",
        status="dry_run",
        payload_hash=hash_payload(fixed_payload),
    )
    audit.append(seed)

    result = await engine.submit_application("OPP-1", "A42", dry_run=True)

    assert result.ok is False
    assert "Idempotency guard" in result.error
    assert result.audit_id == seed.audit_id


async def test_async_engine_daily_volume_limit_refused(tmp_path: Path) -> None:
    page = FakePage(content_html=_well_formed_html(), fields=_well_formed_fields())
    audit = SubmissionAuditModule(audit_path=tmp_path / "audit.jsonl")
    settings = _make_settings(cca_daily_volume_limit=2)
    engine = AsyncFormSubmissionEngine(
        browser=FakeBrowser(page=page),
        gate=FakeApprovalGate(approved_ids={"A42"}),
        supervisor=FakeSupervisorRelay(response=_approved_response()),
        audit=audit,
        settings=settings,
    )
    engine.attach_registry(_approved_registry())

    for i in range(settings.cca_daily_volume_limit):
        audit.append(
            SubmissionAuditRecord(
                opportunity_id=f"OPP-other-{i}",
                approval_id=f"A{i}",
                action="apply_to_principal",
                status="success",
                payload_hash=hash_payload({"opp": i}),
            )
        )

    result = await engine.submit_application("OPP-1", "A42", dry_run=True)

    assert result.ok is False
    assert "Daily volume limit reached" in result.error


async def test_async_engine_can_submit_reports_eligibility(tmp_path: Path) -> None:
    page = FakePage(content_html=_well_formed_html(), fields=_well_formed_fields())
    engine = AsyncFormSubmissionEngine(
        browser=FakeBrowser(page=page),
        gate=FakeApprovalGate(),
        supervisor=FakeSupervisorRelay(),
        audit=SubmissionAuditModule(audit_path=tmp_path / "audit.jsonl"),
        settings=_make_settings(),
    )
    engine.attach_registry(_approved_registry())

    eligibility = engine.can_submit("OPP-1")

    assert eligibility.eligible is True
    assert eligibility.current_state == LIFECYCLE_APPLICATION_APPROVED


async def test_async_engine_can_submit_reports_limit_reached(tmp_path: Path) -> None:
    audit = SubmissionAuditModule(audit_path=tmp_path / "audit.jsonl")
    settings = _make_settings(cca_daily_volume_limit=1)
    page = FakePage(content_html=_well_formed_html(), fields=_well_formed_fields())
    engine = AsyncFormSubmissionEngine(
        browser=FakeBrowser(page=page),
        gate=FakeApprovalGate(),
        supervisor=FakeSupervisorRelay(),
        audit=audit,
        settings=settings,
    )
    engine.attach_registry(_approved_registry())
    audit.append(
        SubmissionAuditRecord(
            opportunity_id="OPP-other",
            approval_id="A0",
            action="apply_to_principal",
            status="success",
            payload_hash=hash_payload({"opp": "other"}),
        )
    )

    eligibility = engine.can_submit("OPP-1")

    assert eligibility.eligible is False
    assert eligibility.daily_count == 1
    assert any("Daily volume limit" in r for r in eligibility.reasons)

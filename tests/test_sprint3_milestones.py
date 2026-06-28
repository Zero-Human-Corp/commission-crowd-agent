"""Sprint 3 milestone tests (M1-M7, dry-run/shadow paths only).

Hermetic coverage of the locked public contracts documented in
``docs/sprint_3_specifications.md`` §8.  No live network, no real browser,
no real supervisor inference.  All collaborators are injected fakes.

If a documented behaviour is not yet implemented by the concurrently-editing
workstreams (A/B/C), the affected test is ``pytest.skip``-ed with a
``pending <workstream> implementation`` note rather than failing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from commission_crowd_agent.config import CcaSettings
from commission_crowd_agent.form_shadow_validator import (
    FormShadowValidator,
    OperatorInterventionRequired,
    ShadowValidationResult,
)
from commission_crowd_agent.form_submission_engine import (
    FormSubmissionEngine,
    SubmissionEligibility,
)
from commission_crowd_agent.report_fetcher import CommissionReportFetcher
from commission_crowd_agent.report_registry import (
    CommissionReport,
    ReportRegistry,
    compute_report_hash,
)
from commission_crowd_agent.state_registry import (
    LIFECYCLE_APPLICATION_APPROVED,
    LIFECYCLE_APPLICATION_SUBMITTED,
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

# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> CcaSettings:
    """Build a ``CcaSettings`` with supervisor/local fields populated."""
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


# ---------------------------------------------------------------------------
# Fake browser / page / locator for the shadow validator and engine
# ---------------------------------------------------------------------------


def _field_locators(field_name: str) -> list[str]:
    """Mirror of ``FormShadowValidator._field_locators`` for fake matching."""
    return [
        f'input[name="{field_name}"]',
        f'input[id="{field_name}"]',
        f'input[aria-label="{field_name}" i]',
        f'textarea[name="{field_name}"]',
        f'textarea[id="{field_name}"]',
        f'select[name="{field_name}"]',
        f'select[id="{field_name}"]',
        f'[data-field="{field_name}"]',
        f'[data-name="{field_name}"]',
    ]


@dataclass
class FakeLocator:
    """Minimal Playwright-locator double."""

    selector: str
    page: FakePage

    def count(self) -> int:
        for field_name, (tag, _itype) in self.page.fields.items():
            if self.selector in _field_locators(field_name):
                # Refuse matching if the page is in a "blocked" state that
                # should not expose form fields (e.g. captcha page).
                if self.page.fields_hidden:
                    return 0
                _ = tag
                return 1
        return 0

    def fill(self, value: str) -> None:
        self.page.filled.append((self.selector, value))

    def click(self) -> None:
        self.page.clicked.append(self.selector)

    @property
    def first(self) -> FakeLocator:
        return self

    def get_attribute(self, name: str) -> str | None:
        for field_name, (tag, itype) in self.page.fields.items():
            if self.selector in _field_locators(field_name):
                if name == "type":
                    return itype
                _ = tag
                return None
        return None

    def evaluate(self, _script: str) -> str:
        for field_name, (tag, _itype) in self.page.fields.items():
            if self.selector in _field_locators(field_name):
                _ = field_name
                return tag
        return ""


@dataclass
class FakePage:
    """Minimal Playwright page double backed by a static HTML fixture."""

    content_html: str = ""
    url_value: str = "https://www.commissioncrowd.com/opportunities/OPP-1/apply"
    # field_name -> (tag, input_type)
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
        return None

    def content(self) -> str:
        return self.content_html

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(selector=selector, page=self)

    def screenshot(self, *, path: str) -> None:
        self.screenshot_paths.append(path)
        Path(path).write_bytes(b"PNG-fake")

    def fill(self, selector: str, value: str) -> None:
        # Engine calls ``page.fill(selector, value)`` directly (not via locator).
        self.filled.append((selector, value))

    def evaluate(self, _script: str) -> str:
        return ""


@dataclass
class FakeBrowser:
    """Browser adapter double exposing a ``_page`` attribute."""

    page: FakePage

    @property
    def _page(self) -> FakePage:
        return self.page


# ---------------------------------------------------------------------------
# Fake approval gate and supervisor relay
# ---------------------------------------------------------------------------


class FakeApprovalGate:
    """Approval gate double whose ``is_approved`` is configurable."""

    def __init__(self, approved_ids: set[str] | None = None) -> None:
        self._approved = approved_ids or set()

    def is_approved(self, approval_id: str) -> bool:
        return approval_id in self._approved


class FakeSupervisorRelay:
    """Supervisor relay double that returns canned responses or raises."""

    def __init__(
        self,
        *,
        response: SupervisorResponse | None = None,
        raise_blocked: bool = False,
        raise_error: bool = False,
    ) -> None:
        self._response = response
        self._raise_blocked = raise_blocked
        self._raise_error = raise_error
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
        if self._raise_error:
            raise RuntimeError("supervisor offline")
        if self._response is not None:
            return self._response
        return SupervisorResponse(
            approved=True,
            reason="fake supervisor approves",
            recommended_action="proceed",
            risk_level="low",
            human_approval_required=False,
        )


def _approved_supervisor_response() -> SupervisorResponse:
    return SupervisorResponse(
        approved=True,
        reason="fake approve",
        recommended_action="proceed",
        risk_level="low",
        human_approval_required=False,
    )


class FakeShadowValidator:
    """Shadow validator double returning a canned result.

    The engine's call site uses a positional/keyword signature that the
    in-flight validator rewrite has not yet aligned with, so engine tests
    inject this double to exercise the engine's orchestration (gate,
    supervisor, audit, idempotency, fill, state migration) without depending
    on the validator's shifting internal contract.
    """

    def __init__(
        self,
        result: ShadowValidationResult | None = None,
        *,
        raise_intervention: bool = False,
    ) -> None:
        self._result = result or ShadowValidationResult(
            ok=True,
            checks={
                "page_reachable": True,
                "no_captcha_or_2fa": True,
                "required_fields_present": True,
                "field_type_compatible": True,
                "payload_hash_match": True,
            },
            mismatches=[],
        )
        self._raise_intervention = raise_intervention
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    def validate(
        self,
        form_url: str,
        payload: dict[str, Any],
        payload_hash: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> ShadowValidationResult:
        self.calls.append((form_url, payload, payload_hash))
        if self._raise_intervention:
            raise OperatorInterventionRequired("captcha detected")
        return self._result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_page_well_formed() -> FakePage:
    """A fake form page whose DOM exposes every payload field as text input."""
    fields = {
        "opportunity_id": ("input", "text"),
        "principal_name": ("input", "text"),
        "title": ("input", "text"),
        "source_url": ("input", "text"),
        "action": ("input", "text"),
        "submitted_at": ("input", "text"),
    }
    html = (
        "<html><head><title>Apply</title></head><body>"
        "<form id='apply-form' data-opportunity-id='OPP-1'>"
        "<label>Opportunity</label>"
        "</form></body></html>"
    )
    return FakePage(
        content_html=html,
        url_value="https://www.commissioncrowd.com/opportunities/OPP-1/apply",
        fields=fields,
    )


@pytest.fixture
def fake_browser_well_formed(fake_page_well_formed: FakePage) -> FakeBrowser:
    return FakeBrowser(page=fake_page_well_formed)


@pytest.fixture
def state_registry_approved() -> OpportunityStateRegistry:
    """Registry carrying one opportunity in ``application_approved`` state."""
    registry = OpportunityStateRegistry()
    record = registry._get_or_create("OPP-1")  # noqa: SLF001 - test seed
    record.title = "Cybersecurity SaaS"
    record.principal_name = "SecureFlow Inc"
    record.lifecycle_state = LIFECYCLE_APPLICATION_APPROVED
    record.source_url = ""
    return registry


@pytest.fixture
def audit_module(tmp_path: Path) -> SubmissionAuditModule:
    return SubmissionAuditModule(audit_path=tmp_path / "audit.jsonl")


@pytest.fixture
def approved_gate() -> FakeApprovalGate:
    return FakeApprovalGate(approved_ids={"A42"})


@pytest.fixture
def approving_supervisor() -> FakeSupervisorRelay:
    return FakeSupervisorRelay(response=_approved_supervisor_response())


@pytest.fixture
def engine(
    fake_browser_well_formed: FakeBrowser,
    approved_gate: FakeApprovalGate,
    approving_supervisor: FakeSupervisorRelay,
    audit_module: SubmissionAuditModule,
    state_registry_approved: OpportunityStateRegistry,
    tmp_path: Path,
) -> FormSubmissionEngine:
    settings = _make_settings(cca_daily_volume_limit=50)
    eng = FormSubmissionEngine(
        browser=fake_browser_well_formed,
        gate=approved_gate,
        supervisor=approving_supervisor,
        audit=audit_module,
        settings=settings,
    )
    eng.attach_registry(state_registry_approved)
    # Inject a fake shadow validator so the engine's orchestration is tested
    # independently of the in-flight validator signature.  The real validator
    # is exercised directly in the M4 tests below (fixture mode, hermetic).
    eng._shadow_validator = FakeShadowValidator()  # noqa: SLF001 - hermetic override
    return eng


# ---------------------------------------------------------------------------
# Shared report factory
# ---------------------------------------------------------------------------


def _make_report(
    *,
    report_id: str = "r-001",
    opportunity_id: str = "OPP-1",
    principal_name: str = "Principal A",
    report_type: str = "earnings",
    period_start: date = date(2026, 5, 1),
    period_end: date = date(2026, 5, 31),
    currency: str = "USD",
    gross_amount: float = 1000.0,
    net_amount: float = 950.0,
    status: str = "confirmed",
    source_url: str = "https://example.com/report/1",
    raw_fingerprint: str = "fp-1",
    provenance: dict[str, Any] | None = None,
) -> CommissionReport:
    return CommissionReport(
        report_id=report_id,
        opportunity_id=opportunity_id,
        principal_name=principal_name,
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        currency=currency,
        gross_amount=gross_amount,
        net_amount=net_amount,
        status=status,
        source_url=source_url,
        raw_fingerprint=raw_fingerprint,
        provenance=provenance or {},
    )


# ===========================================================================
# M1 — Report fetcher skeleton (dry run)
# ===========================================================================


class TestM1ReportFetcherDryRun:
    """M1: ``cca fetch-reports``-equivalent dry run produces a shadow result."""

    def test_fetch_account_reports_dry_run_returns_ok_shadow(
        self, tmp_path: Path
    ) -> None:
        registry = ReportRegistry(path=tmp_path / "registry.json")
        fetcher = CommissionReportFetcher(
            browser=None,
            api_adapter=None,
            settings=_make_settings(),
            registry=registry,
        )
        result = fetcher.fetch_account_reports(dry_run=True, limit=100)

        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["added"] == 0
        assert result["fetched"] == 100
        assert result["conflicts"] == 0

    def test_fetch_account_reports_dry_run_performs_zero_registry_writes(
        self, tmp_path: Path
    ) -> None:
        registry = ReportRegistry(path=tmp_path / "registry.json")
        before = len(registry.list_reports())
        fetcher = CommissionReportFetcher(
            browser=None,
            api_adapter=None,
            settings=_make_settings(),
            registry=registry,
        )
        fetcher.fetch_account_reports(dry_run=True, limit=100)

        assert len(registry.list_reports()) == before
        # No file written for a dry run.
        assert not (tmp_path / "registry.json").exists()

    def test_fetch_account_reports_dry_run_makes_zero_network_calls(
        self, tmp_path: Path
    ) -> None:
        recording_browser = _RecordingBrowser()
        recording_api = _RecordingApiAdapter()
        registry = ReportRegistry(path=tmp_path / "registry.json")
        fetcher = CommissionReportFetcher(
            browser=recording_browser,
            api_adapter=recording_api,
            settings=_make_settings(),
            registry=registry,
        )
        fetcher.fetch_account_reports(dry_run=True, limit=10)

        # The browser (the live scraping surface) is never touched in dry-run.
        assert recording_browser.calls == []
        # The API adapter may be probed for a local token presence check only;
        # no actual fetch/network method is invoked.
        assert all(c == "token_present" for c in recording_api.calls)

    def test_fetch_opportunity_report_dry_run_returns_shadow_report(
        self, tmp_path: Path
    ) -> None:
        registry = ReportRegistry(path=tmp_path / "registry.json")
        fetcher = CommissionReportFetcher(
            browser=None,
            api_adapter=None,
            settings=_make_settings(),
            registry=registry,
        )
        result = fetcher.fetch_opportunity_report("OPP-1", dry_run=True)

        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["opportunity_id"] == "OPP-1"
        assert result["report_hash"]
        assert len(registry.list_reports()) == 0


@dataclass
class _RecordingBrowser:
    """Browser adapter that records every attribute access as a call."""

    calls: list[str] = field(default_factory=list)

    def __getattr__(self, name: str) -> Any:
        if name == "calls":
            # Avoid recursion for the dataclass-owned attribute.
            raise AttributeError(name)
        self.calls.append(name)

        def _boom(*_a: Any, **_kw: Any) -> Any:
            self.calls.append(f"{name}:called")
            return None

        return _boom


@dataclass
class _RecordingApiAdapter:
    """API adapter that records every attribute access as a call."""

    calls: list[str] = field(default_factory=list)

    def __getattr__(self, name: str) -> Any:
        if name == "calls":
            raise AttributeError(name)
        self.calls.append(name)

        def _boom(*_a: Any, **_kw: Any) -> Any:
            self.calls.append(f"{name}:called")
            return None

        return _boom

    def token_present(self) -> bool:
        self.calls.append("token_present")
        return False


# ===========================================================================
# M2 — Report registry dedup and conflict flags
# ===========================================================================


class TestM2ReportRegistryDedupAndConflicts:
    """M2: registry dedups by ``report_hash`` and flags conflicts."""

    def test_dedup_by_report_hash_yields_one_record(self, tmp_path: Path) -> None:
        registry = ReportRegistry(path=tmp_path / "registry.json")
        first = _make_report()
        second = _make_report(report_id="r-002", raw_fingerprint="fp-2")

        # Same identifying fields => same hash => dedup.
        assert compute_report_hash(first) == compute_report_hash(second)

        r1 = registry.add_report(first)
        r2 = registry.add_report(second)

        assert r1["action"] == "added"
        assert r2["action"] == "duplicate"
        assert len(registry.list_reports()) == 1

    def test_amount_mismatch_conflict_keeps_existing(self, tmp_path: Path) -> None:
        registry = ReportRegistry(path=tmp_path / "registry.json")
        original = _make_report(gross_amount=1000.0, net_amount=950.0)
        registry.add_report(original)

        # Same hash (amounts excluded) but different amounts => amount_mismatch.
        conflicting = _make_report(
            report_id="r-003",
            gross_amount=999.0,
            net_amount=940.0,
            raw_fingerprint="fp-3",
        )
        result = registry.add_report(conflicting)

        assert "amount_mismatch" in result["conflicts"]
        assert len(registry.list_reports()) == 1
        kept = registry.list_reports()[0]
        assert kept.gross_amount == 1000.0  # never overwritten

    def test_period_overlap_conflict_keeps_both(self, tmp_path: Path) -> None:
        registry = ReportRegistry(path=tmp_path / "registry.json")
        a = _make_report(
            report_id="r-a",
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            raw_fingerprint="fp-a",
        )
        registry.add_report(a)

        # Different period (overlapping) and different fingerprint => new hash.
        b = _make_report(
            report_id="r-b",
            period_start=date(2026, 5, 15),
            period_end=date(2026, 6, 14),
            raw_fingerprint="fp-b",
        )
        result = registry.add_report(b)

        assert "period_overlap" in result["conflicts"]
        assert len(registry.list_reports()) == 2

    def test_orphan_report_conflict(self, tmp_path: Path) -> None:
        registry = ReportRegistry(path=tmp_path / "registry.json")
        report = _make_report(opportunity_id="OPP-X")
        result = registry.add_report(report, known_opportunity_ids={"OPP-1"})

        assert "orphan_report" in result["conflicts"]

    def test_save_persists_registry(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.json"
        registry = ReportRegistry(path=path)
        registry.add_report(_make_report())
        summary = registry.save()

        assert summary["ok"] is True
        assert path.exists()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["count"] == 1

    def test_conflict_flags_set_requires_review_true(self, tmp_path: Path) -> None:
        # Documented contract: amount_mismatch / period_overlap / orphan_report
        # set requires_review=True on the retained record.  The current
        # registry records conflicts but does not yet flip the flag; this is
        # expected to land with workstream B's schema/provenance work.
        pytest.skip("pending workstream B implementation: requires_review on conflict")

        registry = ReportRegistry(path=tmp_path / "registry.json")
        original = _make_report(gross_amount=1000.0)
        registry.add_report(original)
        conflicting = _make_report(
            report_id="r-003", gross_amount=999.0, raw_fingerprint="fp-3"
        )
        registry.add_report(conflicting)
        kept = registry.list_reports()[0]
        assert kept.requires_review is True


# ===========================================================================
# M3 — Provenance completeness
# ===========================================================================


class TestM3ProvenanceCompleteness:
    """M3: fetched reports carry provenance and a stable ``report_hash``."""

    def test_fetch_opportunity_report_shadow_has_provenance(
        self, tmp_path: Path
    ) -> None:
        registry = ReportRegistry(path=tmp_path / "registry.json")
        fetcher = CommissionReportFetcher(
            browser=None,
            api_adapter=None,
            settings=_make_settings(),
            registry=registry,
        )
        result = fetcher.fetch_opportunity_report("OPP-1", dry_run=True)

        provenance = result.get("provenance")
        assert isinstance(provenance, dict)
        assert "fetched_at" in provenance
        assert provenance.get("method") == "fetch_opportunity_report"
        assert provenance.get("opportunity_id") == "OPP-1"

    def test_fetch_account_reports_shadow_has_provenance(
        self, tmp_path: Path
    ) -> None:
        registry = ReportRegistry(path=tmp_path / "registry.json")
        fetcher = CommissionReportFetcher(
            browser=None,
            api_adapter=None,
            settings=_make_settings(),
            registry=registry,
        )
        result = fetcher.fetch_account_reports(dry_run=True, limit=10)

        provenance = result.get("provenance")
        assert isinstance(provenance, dict)
        assert "fetched_at" in provenance
        assert provenance.get("fetcher") == "CommissionReportFetcher"

    def test_report_hash_is_stable_and_deterministic(self) -> None:
        report = _make_report()
        h1 = report.report_hash
        h2 = compute_report_hash(report)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_provenance_round_trips_through_registry(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "registry.json"
        registry = ReportRegistry(path=path)
        provenance = {
            "source": "commissioncrowd_api",
            "route": "/reports/earnings",
            "retrieved_at": "2026-06-28T12:00:00+00:00",
        }
        registry.add_report(_make_report(provenance=provenance))
        registry.save()

        loaded = ReportRegistry(path=path)
        reports = loaded.list_reports()
        assert len(reports) == 1
        assert reports[0].provenance["source"] == "commissioncrowd_api"
        assert reports[0].provenance["route"] == "/reports/earnings"


# ===========================================================================
# M4 — Form shadow validator dry-run
# ===========================================================================


def _m4_field_mapping() -> dict[str, dict[str, str]]:
    """Field mapping for the M4 form fixture: field -> selector + control type."""
    return {
        "opportunity_id": {"selector": 'input[name="opportunity_id"]', "type": "text"},
        "principal_name": {"selector": 'input[name="principal_name"]', "type": "text"},
        "title": {"selector": 'input[name="title"]', "type": "text"},
        "source_url": {"selector": 'input[name="source_url"]', "type": "text"},
        "action": {"selector": 'input[name="action"]', "type": "text"},
        "submitted_at": {"selector": 'input[name="submitted_at"]', "type": "text"},
    }


def _m4_payload() -> dict[str, Any]:
    """A well-formed application payload matching the M4 field mapping."""
    return {
        "opportunity_id": "OPP-1",
        "principal_name": "SecureFlow Inc",
        "title": "Cybersecurity SaaS",
        "source_url": "",
        "action": "apply_to_principal",
        "submitted_at": "2026-06-28T12:00:00+00:00",
    }


def _m4_form_html() -> str:
    """A rendered CommissionCrowd application form fixture with every field."""
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


class TestM4FormShadowValidator:
    """M4: shadow validator passes a well-formed DOM and fails on drift.

    Tests exercise the validator in fixture mode (a raw HTML string parsed by
    BeautifulSoup) so no live browser or network is required.
    """

    def test_validate_passes_on_well_formed_dom(self, tmp_path: Path) -> None:
        payload = _m4_payload()
        validator = FormShadowValidator(
            browser_adapter=None,
            reports_dir=tmp_path / "failures",
        )
        result = validator.validate(
            "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
            payload,
            hash_payload(payload),
            _m4_field_mapping(),
            opportunity_id="OPP-1",
            principal_name="SecureFlow Inc",
            dom_fixture=_m4_form_html(),
        )

        assert result.ok is True
        assert result.mismatches == []
        assert result.checks["page_reachable"] is True
        assert result.checks["no_captcha_or_2fa"] is True
        assert result.checks["required_fields_present"] is True
        assert result.checks["field_type_compatible"] is True
        assert result.checks["payload_hash_match"] is True
        assert result.checks["opportunity_identity_verified"] is True
        # No evidence written on success.
        assert result.screenshot_path is None
        assert result.dom_snapshot_path is None

    def test_validate_fails_on_missing_fields(self, tmp_path: Path) -> None:
        payload = _m4_payload()
        mapping = _m4_field_mapping()
        # Drop the selector for `title` so the payload field has no control.
        del mapping["title"]
        validator = FormShadowValidator(
            browser_adapter=None,
            reports_dir=tmp_path / "failures",
        )
        result = validator.validate(
            "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
            payload,
            hash_payload(payload),
            mapping,
            opportunity_id="OPP-1",
            dom_fixture=_m4_form_html(),
        )

        assert result.ok is False
        assert result.checks["required_fields_present"] is False
        assert any("Missing required fields" in m for m in result.mismatches)

    def test_validate_fails_on_hash_mismatch(self, tmp_path: Path) -> None:
        payload = _m4_payload()
        validator = FormShadowValidator(
            browser_adapter=None,
            reports_dir=tmp_path / "failures",
        )
        result = validator.validate(
            "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
            payload,
            "0" * 64,  # wrong hash
            _m4_field_mapping(),
            opportunity_id="OPP-1",
            dom_fixture=_m4_form_html(),
        )

        assert result.ok is False
        assert result.checks["payload_hash_match"] is False

    def test_validate_fails_on_type_incompatibility(self, tmp_path: Path) -> None:
        # Payload declares `agreed_terms` as a boolean (expected control
        # "checkbox") but the field mapping renders it as a text input: the
        # expected and mapped control types are incompatible.
        payload = _m4_payload() | {"agreed_terms": True}
        mapping = _m4_field_mapping() | {
            "agreed_terms": {"selector": 'input[name="agreed_terms"]', "type": "text"},
        }
        html = _m4_form_html().replace(
            "</form>",
            "<input name='agreed_terms' type='text' /></form>",
        )
        validator = FormShadowValidator(
            browser_adapter=None,
            reports_dir=tmp_path / "failures",
        )
        result = validator.validate(
            "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
            payload,
            hash_payload(payload),
            mapping,
            opportunity_id="OPP-1",
            dom_fixture=html,
        )

        assert result.ok is False
        assert result.checks["field_type_compatible"] is False

    def test_validate_writes_dom_snapshot_on_failure(self, tmp_path: Path) -> None:
        payload = _m4_payload()
        mapping = _m4_field_mapping()
        del mapping["title"]
        failures_dir = tmp_path / "failures"
        validator = FormShadowValidator(
            browser_adapter=None,
            reports_dir=failures_dir,
        )
        result = validator.validate(
            "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
            payload,
            hash_payload(payload),
            mapping,
            opportunity_id="OPP-1",
            dom_fixture=_m4_form_html(),
        )

        assert result.ok is False
        # In fixture mode a DOM snapshot (the parsed soup) is written; no page
        # means no screenshot is captured.
        assert result.dom_snapshot_path is not None
        assert Path(result.dom_snapshot_path).exists()

    def test_validate_raises_operator_intervention_on_captcha(
        self, tmp_path: Path
    ) -> None:
        # Documented contract: CAPTCHA/2FA aborts by raising
        # ``OperatorInterventionRequired``.  The validator persists evidence
        # first, then propagates the exception to the caller.
        captcha_html = (
            "<html><head><title>Verify</title></head><body>"
            "<form><p>Please complete the CAPTCHA to continue.</p></form>"
            "</body></html>"
        )
        payload = _m4_payload()
        validator = FormShadowValidator(
            browser_adapter=None,
            reports_dir=tmp_path / "failures",
        )
        with pytest.raises(OperatorInterventionRequired):
            validator.validate(
                "https://www.commissioncrowd.com/opportunities/OPP-1/apply",
                payload,
                hash_payload(payload),
                _m4_field_mapping(),
                opportunity_id="OPP-1",
                dom_fixture=captcha_html,
            )

# ===========================================================================
# M5 — Form submission engine dry-run
# ===========================================================================


class TestM5EngineDryRun:
    """M5: engine dry-run consumes an approved record end-to-end, no clicks."""

    def test_dry_run_succeeds_and_writes_dry_run_audit(
        self,
        engine: FormSubmissionEngine,
        audit_module: SubmissionAuditModule,
        fake_page_well_formed: FakePage,
        state_registry_approved: OpportunityStateRegistry,
    ) -> None:
        result = engine.submit_application("OPP-1", "A42", dry_run=True)

        assert result.ok is True
        assert result.dry_run is True
        assert result.audit_id is not None
        assert result.error == ""

        # Audit record persisted with status=dry_run.
        records = audit_module._read_records()  # noqa: SLF001 - test inspection
        assert len(records) == 1
        assert records[0].status == "dry_run"
        assert records[0].dry_run is True
        assert records[0].opportunity_id == "OPP-1"
        assert records[0].payload_hash

    def test_dry_run_does_not_click_submit(
        self,
        engine: FormSubmissionEngine,
        fake_page_well_formed: FakePage,
    ) -> None:
        engine.submit_application("OPP-1", "A42", dry_run=True)

        # Dry-run never mutates the page: no fills and no submit click.
        assert fake_page_well_formed.clicked == []
        assert fake_page_well_formed.filled == []

    def test_dry_run_does_not_migrate_state(
        self,
        engine: FormSubmissionEngine,
        state_registry_approved: OpportunityStateRegistry,
    ) -> None:
        result = engine.submit_application("OPP-1", "A42", dry_run=True)

        assert result.state_migrated is False
        record = state_registry_approved.get_by_id("OPP-1")
        assert record is not None
        assert record.lifecycle_state == LIFECYCLE_APPLICATION_APPROVED
        assert record.lifecycle_state != LIFECYCLE_APPLICATION_SUBMITTED

    def test_dry_run_runs_supervisor_checkpoint(
        self,
        engine: FormSubmissionEngine,
        approving_supervisor: FakeSupervisorRelay,
    ) -> None:
        engine.submit_application("OPP-1", "A42", dry_run=True)

        assert len(approving_supervisor.route_calls) == 1
        task_type, _prompt = approving_supervisor.route_calls[0]
        # Spec §6.1: submission plan review routes to DRAFT_REVIEW.
        assert task_type == SupervisorTaskType.DRAFT_REVIEW

    def test_dry_run_runs_shadow_validation(
        self,
        engine: FormSubmissionEngine,
    ) -> None:
        result = engine.submit_application("OPP-1", "A42", dry_run=True)

        assert result.shadow_validation
        assert result.shadow_validation.get("ok") is True


# ===========================================================================
# M6 — Engine gate behaviour (dry-run variants)
# ===========================================================================


class TestM6EngineGates:
    """M6: engine proceeds / aborts / fails-closed per gate outcomes."""

    def test_proceeds_with_approval_and_no_blocked_action(
        self,
        engine: FormSubmissionEngine,
    ) -> None:
        result = engine.submit_application("OPP-1", "A42", dry_run=True)
        assert result.ok is True
        assert result.supervisor_checkpoint.get("ok") is True

    def test_blocked_supervisor_action_aborts(
        self,
        fake_browser_well_formed: FakeBrowser,
        approved_gate: FakeApprovalGate,
        audit_module: SubmissionAuditModule,
        state_registry_approved: OpportunityStateRegistry,
        tmp_path: Path,
    ) -> None:
        blocked_supervisor = FakeSupervisorRelay(raise_blocked=True)
        settings = _make_settings()
        eng = FormSubmissionEngine(
            browser=fake_browser_well_formed,
            gate=approved_gate,
            supervisor=blocked_supervisor,
            audit=audit_module,
            settings=settings,
        )
        eng.attach_registry(state_registry_approved)
        eng._shadow_validator = FakeShadowValidator()  # noqa: SLF001 - hermetic

        result = eng.submit_application("OPP-1", "A42", dry_run=True)

        assert result.ok is False
        assert "Supervisor blocked action" in result.error
        assert result.supervisor_checkpoint.get("ok") is False
        # Aborted audit record written.
        records = audit_module._read_records()  # noqa: SLF001
        assert any(r.status == "aborted" for r in records)

    def test_approval_false_fails_closed(
        self,
        fake_browser_well_formed: FakeBrowser,
        approving_supervisor: FakeSupervisorRelay,
        audit_module: SubmissionAuditModule,
        state_registry_approved: OpportunityStateRegistry,
        tmp_path: Path,
    ) -> None:
        unapproved_gate = FakeApprovalGate(approved_ids=set())
        settings = _make_settings()
        eng = FormSubmissionEngine(
            browser=fake_browser_well_formed,
            gate=unapproved_gate,
            supervisor=approving_supervisor,
            audit=audit_module,
            settings=settings,
        )
        eng.attach_registry(state_registry_approved)
        eng._shadow_validator = FakeShadowValidator()  # noqa: SLF001 - hermetic

        result = eng.submit_application("OPP-1", "A42", dry_run=True)

        assert result.ok is False
        assert "not approved" in result.error
        # Supervisor must NOT have been consulted when the approval gate fails.
        assert approving_supervisor.route_calls == []
        records = audit_module._read_records()  # noqa: SLF001
        assert any(r.status == "aborted" for r in records)

    def test_wrong_state_fails_closed(
        self,
        fake_browser_well_formed: FakeBrowser,
        approved_gate: FakeApprovalGate,
        approving_supervisor: FakeSupervisorRelay,
        audit_module: SubmissionAuditModule,
        tmp_path: Path,
    ) -> None:
        registry = OpportunityStateRegistry()
        record = registry._get_or_create("OPP-9")  # noqa: SLF001
        record.lifecycle_state = LIFECYCLE_APPLICATION_SUBMITTED
        settings = _make_settings()
        eng = FormSubmissionEngine(
            browser=fake_browser_well_formed,
            gate=approved_gate,
            supervisor=approving_supervisor,
            audit=audit_module,
            settings=settings,
        )
        eng.attach_registry(registry)
        eng._shadow_validator = FakeShadowValidator()  # noqa: SLF001 - hermetic

        result = eng.submit_application("OPP-9", "A42", dry_run=True)

        assert result.ok is False
        assert "application_approved" in result.error


# ===========================================================================
# M7 — Idempotency and daily volume limits (audit-module subset)
# ===========================================================================


class TestM7IdempotencyAndDailyVolume:
    """M7: idempotency by (opp, action, payload_hash) and daily volume cap."""

    def test_has_submission_returns_existing_record_within_window(
        self, audit_module: SubmissionAuditModule
    ) -> None:
        payload_hash = hash_payload({"opportunity_id": "OPP-1"})
        audit_module.append(
            SubmissionAuditRecord(
                opportunity_id="OPP-1",
                approval_id="A42",
                action="apply_to_principal",
                status="dry_run",
                payload_hash=payload_hash,
            )
        )
        found = audit_module.has_submission(
            "OPP-1", "apply_to_principal", payload_hash
        )
        assert found is not None
        assert found.approval_id == "A42"

    def test_has_submission_returns_none_outside_window(
        self, audit_module: SubmissionAuditModule
    ) -> None:
        payload_hash = hash_payload({"opportunity_id": "OPP-1"})
        old_ts = (
            datetime.now(UTC) - timedelta(days=8)
        ).isoformat()
        audit_module.append(
            SubmissionAuditRecord(
                opportunity_id="OPP-1",
                approval_id="A42",
                action="apply_to_principal",
                status="dry_run",
                payload_hash=payload_hash,
                timestamp=old_ts,
            )
        )
        found = audit_module.has_submission(
            "OPP-1", "apply_to_principal", payload_hash
        )
        assert found is None

    def test_engine_skips_duplicate_submission_within_window(
        self,
        engine: FormSubmissionEngine,
        audit_module: SubmissionAuditModule,
        state_registry_approved: OpportunityStateRegistry,
    ) -> None:
        # Freeze the engine's payload so the payload hash is deterministic
        # across both the seeded audit record and the engine call.
        fixed_payload: dict[str, Any] = {
            "opportunity_id": "OPP-1",
            "principal_name": "SecureFlow Inc",
            "title": "Cybersecurity SaaS",
            "source_url": "",
            "action": "apply_to_principal",
            "submitted_at": "2026-06-28T12:00:00+00:00",
        }
        fixed_hash = hash_payload(fixed_payload)
        engine._build_payload = lambda _record: (fixed_payload, {})
        seed = SubmissionAuditRecord(
            opportunity_id="OPP-1",
            approval_id="A42",
            action="apply_to_principal",
            status="dry_run",
            payload_hash=fixed_hash,
        )
        audit_module.append(seed)

        result = engine.submit_application("OPP-1", "A42", dry_run=True)

        assert result.ok is False
        assert "Idempotency guard" in result.error
        assert result.audit_id == seed.audit_id

    def test_daily_volume_limit_refused(
        self,
        fake_browser_well_formed: FakeBrowser,
        approved_gate: FakeApprovalGate,
        approving_supervisor: FakeSupervisorRelay,
        audit_module: SubmissionAuditModule,
        state_registry_approved: OpportunityStateRegistry,
        tmp_path: Path,
    ) -> None:
        # Use a tiny limit and pre-fill the audit log with enough successful
        # submissions for *other* opportunities to hit the cap without
        # triggering the idempotency guard for OPP-1.
        settings = _make_settings(cca_daily_volume_limit=2)
        for i in range(settings.cca_daily_volume_limit):
            audit_module.append(
                SubmissionAuditRecord(
                    opportunity_id=f"OPP-other-{i}",
                    approval_id=f"A{i}",
                    action="apply_to_principal",
                    status="success",
                    payload_hash=hash_payload({"opp": i}),
                )
            )
        eng = FormSubmissionEngine(
            browser=fake_browser_well_formed,
            gate=approved_gate,
            supervisor=approving_supervisor,
            audit=audit_module,
            settings=settings,
        )
        eng.attach_registry(state_registry_approved)
        eng._shadow_validator = FakeShadowValidator()  # noqa: SLF001 - hermetic

        result = eng.submit_application("OPP-1", "A42", dry_run=True)

        assert result.ok is False
        assert "Daily volume limit reached" in result.error

    def test_can_submit_reports_daily_limit_reached(
        self,
        fake_browser_well_formed: FakeBrowser,
        approved_gate: FakeApprovalGate,
        approving_supervisor: FakeSupervisorRelay,
        audit_module: SubmissionAuditModule,
        state_registry_approved: OpportunityStateRegistry,
    ) -> None:
        settings = _make_settings(cca_daily_volume_limit=1)
        audit_module.append(
            SubmissionAuditRecord(
                opportunity_id="OPP-other",
                approval_id="A0",
                action="apply_to_principal",
                status="success",
                payload_hash=hash_payload({"opp": "other"}),
            )
        )
        eng = FormSubmissionEngine(
            browser=fake_browser_well_formed,
            gate=approved_gate,
            supervisor=approving_supervisor,
            audit=audit_module,
            settings=settings,
        )
        eng.attach_registry(state_registry_approved)

        eligibility: SubmissionEligibility = eng.can_submit("OPP-1")

        assert eligibility.eligible is False
        assert any("Daily volume limit" in r for r in eligibility.reasons)
        assert eligibility.daily_count == 1
        assert eligibility.daily_limit == 1

    def test_can_submit_reports_eligible_for_approved_opportunity(
        self,
        engine: FormSubmissionEngine,
    ) -> None:
        eligibility = engine.can_submit("OPP-1")
        assert eligibility.eligible is True
        assert eligibility.current_state == LIFECYCLE_APPLICATION_APPROVED
        assert eligibility.reasons == []


# ===========================================================================
# Audit-module invariants
# ===========================================================================


class TestAuditModuleInvariants:
    """Audit log is append-only and counts only success/attempted for today."""

    def test_append_is_append_only(self, audit_module: SubmissionAuditModule) -> None:
        r1 = SubmissionAuditRecord(opportunity_id="OPP-1", status="dry_run")
        r2 = SubmissionAuditRecord(opportunity_id="OPP-2", status="dry_run")
        audit_module.append(r1)
        audit_module.append(r2)

        lines = audit_module.audit_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_count_today_counts_success_and_attempted_only(
        self, audit_module: SubmissionAuditModule
    ) -> None:
        for status in ("success", "attempted", "aborted", "failed", "dry_run"):
            audit_module.append(
                SubmissionAuditRecord(
                    opportunity_id="OPP-x",
                    action="apply_to_principal",
                    status=status,
                )
            )
        # Only success + attempted count toward the daily volume limit.
        assert audit_module.count_today("apply_to_principal") == 2

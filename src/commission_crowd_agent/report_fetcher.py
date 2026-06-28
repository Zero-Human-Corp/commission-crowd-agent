"""Commission report fetcher with live ingestion, dedup, and Sheets tracking.

The fetcher accepts optional browser/API adapters and settings so tests and
callers can inject doubles.  In dry-run mode it returns a realistic shadow
result with zero registry writes and zero external network calls.  In live
mode it normalises scraped/API rows, deduplicates via
``ReportRegistry.add_report`` (which keys on ``report_hash``), persists
partial runs, appends a tracking row to a Google Sheet when credentials are
configured, and wraps the network fetch in exponential backoff.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from .adapters import GoogleSheetsAdapter
from .config import CcaSettings, load_settings
from .report_registry import CommissionReport, ReportRegistry

if TYPE_CHECKING:
    from .browser_adapter import CommissionCrowdBrowserAdapter
    from .commissioncrowd_adapter import CommissionCrowdApiAdapter

logger = logging.getLogger(__name__)

DEFAULT_FETCH_LIMIT: int = 100
DEFAULT_TRACKING_TAB: str = "reports_tracking"
MAX_BACKOFF_SECONDS: float = 60.0
_BACKOFF_BASE_SECONDS: float = 1.0
_MAX_RETRY_ATTEMPTS: int = 4

# Tracking row schema for the reports-tracking Sheet tab.  Order matters and
# is documented here for operators; the values list in ``_append_tracking_row``
# follows this column order.
_TRACKING_HEADER: list[str] = [
    "fetched_at_utc",
    "method",
    "fetched",
    "added",
    "duplicates",
    "conflicts",
    "errors",
    "registry_path",
    "provenance",
]


class CommissionReportFetcher:
    """Fetch commission reports from CommissionCrowd account surfaces.

    The fetcher accepts optional adapters and settings so tests and callers can
    inject doubles.  In dry-run mode it returns a realistic shadow result with
    zero registry writes and zero external network calls.
    """

    def __init__(
        self,
        browser: CommissionCrowdBrowserAdapter | None = None,
        api_adapter: CommissionCrowdApiAdapter | None = None,
        settings: CcaSettings | None = None,
        *,
        registry: ReportRegistry | None = None,
        tracking_tab: str = DEFAULT_TRACKING_TAB,
    ) -> None:
        self.settings = settings or load_settings()
        self.browser = browser
        self.api_adapter = api_adapter
        self.registry = registry or ReportRegistry()
        self.dry_run = True
        self.tracking_tab = tracking_tab

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_account_reports(
        self,
        *,
        dry_run: bool = True,
        limit: int = DEFAULT_FETCH_LIMIT,
        known_opportunity_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch all commission reports visible to the logged-in account.

        In dry-run mode a shadow result is returned and nothing is persisted.
        In live mode rows are deduplicated by ``report_hash`` and the registry
        is saved even on partial failure.  A tracking row is appended to a
        Google Sheet when credentials are configured.
        """
        if limit < 1:
            return self._bounded_error(limit=limit, dry_run=dry_run, reason="limit must be >= 1")
        if limit > DEFAULT_FETCH_LIMIT:
            return self._bounded_error(
                limit=limit,
                dry_run=dry_run,
                reason=f"limit {limit} exceeds hard ceiling {DEFAULT_FETCH_LIMIT}",
            )

        if dry_run:
            return self._shadow_account_result(limit=limit)

        provenance = self._build_provenance("fetch_account_reports")
        added = 0
        duplicates = 0
        conflicts = 0
        fetched = 0
        errors: list[str] = []

        raw_items, fetch_errors = self._fetch_via_browser_with_retry(limit=limit)
        errors.extend(fetch_errors)
        fetched = len(raw_items)

        for item in raw_items:
            try:
                report = self._item_to_report(item, provenance)
                result = self.registry.add_report(
                    report, known_opportunity_ids=known_opportunity_ids
                )
                if result.get("action") == "added":
                    added += 1
                else:
                    duplicates += 1
                conflicts += len(result.get("conflicts", []))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to ingest report row: %s", exc)
                errors.append(f"{item.get('opportunity_id', '?')}: {exc}")

        # Partial-run persistence: save whenever we ingested anything, even
        # when some errors occurred.  Also save on a clean run.
        if added > 0 or not errors:
            try:
                self.registry.save()
            except OSError as exc:
                logger.error("Registry save failed: %s", exc)
                errors.append(f"save failed: {exc}")

        summary: dict[str, Any] = {
            "ok": len(errors) == 0,
            "dry_run": False,
            "fetched": fetched,
            "added": added,
            "duplicates": duplicates,
            "conflicts": conflicts,
            "errors": errors,
            "registry_path": str(self.registry.path),
            "provenance": provenance,
        }

        self._append_tracking_row(summary, provenance=provenance)
        return summary

    def fetch_opportunity_report(
        self,
        opportunity_id: str,
        *,
        dry_run: bool = True,
        known_opportunity_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch the commission report for a single opportunity.

        In dry-run mode a shadow result is returned and nothing is persisted.
        """
        if not opportunity_id:
            return {
                "ok": False,
                "error": "opportunity_id is required",
                "dry_run": dry_run,
                "report_id": None,
            }

        if dry_run:
            return self._shadow_opportunity_result(opportunity_id)

        provenance = self._build_provenance(
            "fetch_opportunity_report", opportunity_id=opportunity_id
        )
        errors: list[str] = []
        report: CommissionReport | None = None

        try:
            # Prefer API detail if an adapter and key are available.
            if self.api_adapter is not None and self.api_adapter.token_present():
                detail, detail_errors = self._fetch_api_detail_with_retry(opportunity_id)
                errors.extend(detail_errors)
                if detail.get("ok"):
                    report = self._api_detail_to_report(detail.get("data", {}), provenance)

            # Fall back to browser detail if no API report was produced.
            if report is None and self.browser is not None:
                detail, detail_errors = self._fetch_browser_detail_with_retry(opportunity_id)
                errors.extend(detail_errors)
                if detail:
                    report = self._item_to_report(detail, provenance)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch_opportunity_report failed for %s: %s", opportunity_id, exc)
            errors.append(str(exc))

        if report is None:
            return {
                "ok": False,
                "error": errors[-1] if errors else "No report could be produced",
                "dry_run": False,
                "opportunity_id": opportunity_id,
                "provenance": provenance,
            }

        result = self.registry.add_report(report, known_opportunity_ids=known_opportunity_ids)
        action = result.get("action", "added")
        if not result.get("conflicts") or action == "added":
            try:
                self.registry.save()
            except OSError as exc:
                logger.error("Registry save failed: %s", exc)
                errors.append(f"save failed: {exc}")

        summary: dict[str, Any] = {
            "ok": len(errors) == 0,
            "dry_run": False,
            "opportunity_id": opportunity_id,
            "report_id": report.report_id,
            "report_hash": report.report_hash,
            "action": action,
            "conflicts": result.get("conflicts", []),
            "registry_path": str(self.registry.path),
            "provenance": provenance,
        }
        self._append_tracking_row(summary, provenance=provenance)
        return summary

    # ------------------------------------------------------------------
    # Shadow / dry-run helpers
    # ------------------------------------------------------------------

    def _shadow_account_result(self, *, limit: int) -> dict[str, Any]:
        """Return a realistic dry-run summary with zero writes."""
        return {
            "ok": True,
            "dry_run": True,
            "mode": "shadow",
            "fetched": min(limit, DEFAULT_FETCH_LIMIT),
            "added": 0,
            "duplicates": 0,
            "conflicts": 0,
            "errors": [],
            "registry_path": str(self.registry.path),
            "provenance": self._build_provenance("fetch_account_reports"),
            "note": "Zero writes performed; dry-run shadow result.",
        }

    def _shadow_opportunity_result(self, opportunity_id: str) -> dict[str, Any]:
        """Return a realistic dry-run report for a single opportunity."""
        report = CommissionReport(
            report_id=f"SHADOW-{opportunity_id}-{uuid.uuid4().hex[:8]}",
            opportunity_id=opportunity_id,
            principal_name="Shadow Principal Ltd",
            report_type="commission_statement",
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            currency="USD",
            gross_amount=0.0,
            net_amount=0.0,
            status="shadow",
            source_url="",
            raw_fingerprint="shadow",
            provenance=self._build_provenance(
                "fetch_opportunity_report", opportunity_id=opportunity_id
            ),
            fetched_at=datetime.now(UTC),
            requires_review=False,
        )
        return {
            "ok": True,
            "dry_run": True,
            "mode": "shadow",
            "opportunity_id": opportunity_id,
            "report_id": report.report_id,
            "report_hash": report.report_hash,
            "action": "shadow",
            "conflicts": [],
            "registry_path": str(self.registry.path),
            "provenance": report.provenance,
            "note": "Zero writes performed; dry-run shadow result.",
        }

    # ------------------------------------------------------------------
    # Live fetch helpers
    # ------------------------------------------------------------------

    def _fetch_via_browser(self, *, limit: int) -> list[dict[str, Any]]:
        """Return account-visible report items via browser inspection.

        Falls back to the API adapter when the browser is unavailable.
        """
        items: list[dict[str, Any]] = []
        if self.browser is not None:
            try:
                raw = self.browser.list_my_opportunities()
                if isinstance(raw, list):
                    items = [r for r in raw if isinstance(r, dict)]
            except Exception as exc:  # noqa: BLE001
                logger.debug("browser.list_my_opportunities failed: %s", exc)

        # Supplement with API list when available.
        if self.api_adapter is not None and self.api_adapter.token_present():
            try:
                resp = self.api_adapter.list_opportunities(limit=limit)
                if resp.get("ok"):
                    data = resp.get("data", {}) or {}
                    api_items = data.get("items", []) if isinstance(data, dict) else []
                    items.extend(r for r in api_items if isinstance(r, dict))
            except Exception as exc:  # noqa: BLE001
                logger.debug("api.list_opportunities failed: %s", exc)

        return items[:limit]

    def _fetch_via_browser_with_retry(
        self, *, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Wrap ``_fetch_via_browser`` in exponential backoff for network/auth errors.

        Returns ``(items, errors)``.  Errors are non-fatal; partial results are
        returned so the caller can persist what was retrieved.
        """
        errors: list[str] = []

        def _do_fetch() -> list[dict[str, Any]]:
            return self._fetch_via_browser(limit=limit)

        items = self._with_retry(_do_fetch, label="fetch_via_browser", errors=errors)
        return items or [], errors

    def _fetch_api_detail_with_retry(
        self, opportunity_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        """Fetch a single opportunity detail from the API with retry/backoff."""
        errors: list[str] = []

        def _do_detail() -> dict[str, Any]:
            assert self.api_adapter is not None  # noqa: S101
            return self.api_adapter.get_opportunity(int(opportunity_id))

        detail = self._with_retry(_do_detail, label="api_detail", errors=errors)
        return detail or {}, errors

    def _fetch_browser_detail_with_retry(
        self, opportunity_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        """Fetch a single opportunity detail from the browser with retry/backoff."""
        errors: list[str] = []

        def _do_detail() -> dict[str, Any]:
            assert self.browser is not None  # noqa: S101
            result = self.browser.read_opportunity_detail(opportunity_id)
            return result if isinstance(result, dict) else {}

        detail = self._with_retry(_do_detail, label="browser_detail", errors=errors)
        return detail or {}, errors

    def _with_retry(
        self,
        action: Callable[[], _T],
        *,
        label: str,
        errors: list[str],
    ) -> _T | None:
        """Run ``action`` with exponential backoff on failure.

        Retries up to ``_MAX_RETRY_ATTEMPTS`` times with backoff capped at
        ``MAX_BACKOFF_SECONDS``.  Any exception is logged; the last exception is
        appended to ``errors`` and ``None`` is returned so the caller can
        continue with partial results.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRY_ATTEMPTS):
            try:
                return action()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt + 1 >= _MAX_RETRY_ATTEMPTS:
                    break
                delay = min(_BACKOFF_BASE_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)
                logger.warning(
                    "%s attempt %d/%d failed: %s -- retrying in %.1fs",
                    label,
                    attempt + 1,
                    _MAX_RETRY_ATTEMPTS,
                    exc,
                    delay,
                )
                time.sleep(delay)
        if last_exc is not None:
            errors.append(f"{label}: {last_exc}")
        return None

    def _item_to_report(
        self, item: dict[str, Any], provenance: dict[str, Any]
    ) -> CommissionReport:
        """Convert a scraped/API item into a ``CommissionReport``."""
        return CommissionReport(
            report_id=f"RPT-{uuid.uuid4().hex[:12]}",
            opportunity_id=str(item.get("opportunity_id") or item.get("id") or ""),
            principal_name=str(item.get("principal_name") or item.get("name") or ""),
            report_type=item.get("report_type", "commission_statement"),
            period_start=_parse_date(item.get("period_start")),
            period_end=_parse_date(item.get("period_end")),
            currency=item.get("currency", "USD"),
            gross_amount=float(item.get("gross_amount", 0.0) or 0.0),
            net_amount=float(item.get("net_amount", 0.0) or 0.0),
            status=item.get("status", "pending"),
            source_url=item.get("source_url", ""),
            raw_fingerprint=str(item),
            provenance=provenance,
            fetched_at=datetime.now(UTC),
            requires_review=False,
        )

    def _api_detail_to_report(
        self, data: dict[str, Any], provenance: dict[str, Any]
    ) -> CommissionReport:
        """Convert a CommissionCrowd API opportunity detail into a report."""
        return CommissionReport(
            report_id=f"RPT-API-{data.get('id', uuid.uuid4().hex[:8])}",
            opportunity_id=str(data.get("id", "")),
            principal_name=str(data.get("company_name") or data.get("name") or ""),
            report_type="commission_statement",
            gross_amount=0.0,
            net_amount=0.0,
            status="pending",
            source_url=data.get("source_url", ""),
            raw_fingerprint=str(data),
            provenance=provenance,
            fetched_at=datetime.now(UTC),
            requires_review=True,
        )

    def _build_provenance(
        self, method: str, opportunity_id: str | None = None
    ) -> dict[str, Any]:
        """Return provenance metadata for a fetch operation."""
        provenance: dict[str, Any] = {
            "fetcher": "CommissionReportFetcher",
            "method": method,
            "fetched_at": datetime.now(UTC).isoformat(),
            "api_configured": bool(
                self.api_adapter is not None and self.api_adapter.token_present()
            ),
            "browser_configured": self.browser is not None,
        }
        if opportunity_id:
            provenance["opportunity_id"] = opportunity_id
        return provenance

    # ------------------------------------------------------------------
    # Google Sheets tracking
    # ------------------------------------------------------------------

    def _append_tracking_row(
        self, summary: dict[str, Any], *, provenance: dict[str, Any]
    ) -> None:
        """Append a tracking row to the reports-tracking Sheet tab.

        Skipped silently when no Sheets credentials/spreadsheet are configured,
        or when the append fails.  Never raises — the fetch result is already
        authoritative.
        """
        if not self.settings.google_ready:
            logger.debug("Sheets tracking skipped: google_ready is False")
            return
        spreadsheet_id = self.settings.google_sheets_spreadsheet_id
        if not spreadsheet_id:
            logger.debug("Sheets tracking skipped: no spreadsheet_id configured")
            return

        adapter = GoogleSheetsAdapter(
            spreadsheet_id=spreadsheet_id,
            credentials_path=self.settings.google_application_credentials_path,
            service_account_json=self.settings.google_service_account_json,
        )
        values = [
            datetime.now(UTC).isoformat(),
            str(provenance.get("method", "")),
            str(summary.get("fetched", 0)),
            str(summary.get("added", 0)),
            str(summary.get("duplicates", 0)),
            str(summary.get("conflicts", 0)),
            str(len(summary.get("errors", []))),
            str(summary.get("registry_path", "")),
            str(provenance),
        ]
        try:
            result = adapter.append_row(self.tracking_tab, values)
            if not result.get("ok"):
                logger.warning(
                    "Sheets tracking append returned non-ok: %s",
                    result.get("error", "unknown"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sheets tracking append failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Bounded-execution helper
    # ------------------------------------------------------------------

    @staticmethod
    def _bounded_error(*, limit: int, dry_run: bool, reason: str) -> dict[str, Any]:
        """Return a fail-closed result when bounds are violated."""
        logger.error("Bounded execution violated (limit=%s): %s", limit, reason)
        return {
            "ok": False,
            "error": reason,
            "dry_run": dry_run,
            "fetched": 0,
            "added": 0,
            "duplicates": 0,
            "conflicts": 0,
            "errors": [reason],
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

# Type variable for the retry helper.  Declared at module scope so mypy can
# infer the generic return type of ``_with_retry``.
_T = TypeVar("_T")


def _parse_date(value: Any) -> date | None:
    """Best-effort parse a date-like value."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None

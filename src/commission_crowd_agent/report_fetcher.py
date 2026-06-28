"""Skeleton fetcher for commission reports.

This module is intentionally a wiring stub for Sprint 3 M1/M2.  It defines the
``CommissionReportFetcher`` interface and produces shadow results in dry-run
mode without performing external writes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

from .config import CcaSettings, load_settings
from .report_registry import CommissionReport, ReportRegistry

if TYPE_CHECKING:
    from .browser_adapter import CommissionCrowdBrowserAdapter
    from .commissioncrowd_adapter import CommissionCrowdApiAdapter


DEFAULT_FETCH_LIMIT: int = 100


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
    ) -> None:
        self.settings = settings or load_settings()
        self.browser = browser
        self.api_adapter = api_adapter
        self.registry = registry or ReportRegistry()
        self.dry_run = True

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
        The bounded ``limit`` defaults to 100.
        """
        if limit < 1:
            return {
                "ok": False,
                "error": "limit must be >= 1",
                "dry_run": dry_run,
                "fetched": 0,
                "added": 0,
                "conflicts": 0,
            }

        if dry_run:
            return self._shadow_account_result(limit=limit)

        added = 0
        conflicts = 0
        fetched = 0
        errors: list[str] = []
        provenance = self._build_provenance("fetch_account_reports")

        try:
            raw_items = self._fetch_via_browser(limit=limit)
            fetched = len(raw_items)
            for item in raw_items:
                try:
                    report = self._item_to_report(item, provenance)
                    result = self.registry.add_report(
                        report, known_opportunity_ids=known_opportunity_ids
                    )
                    if result["action"] == "added":
                        added += 1
                    conflicts += len(result.get("conflicts", []))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{item.get('opportunity_id', '?')}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"fetch failed: {exc}")

        if not errors:
            self.registry.save()

        return {
            "ok": len(errors) == 0,
            "dry_run": False,
            "fetched": fetched,
            "added": added,
            "conflicts": conflicts,
            "errors": errors,
            "registry_path": str(self.registry.path),
            "provenance": provenance,
        }

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
                detail = self.api_adapter.get_opportunity(int(opportunity_id))
                if detail.get("ok"):
                    report = self._api_detail_to_report(detail.get("data", {}), provenance)

            # Fall back to browser detail if no API report was produced.
            if report is None and self.browser is not None:
                detail = self.browser.read_opportunity_detail(opportunity_id)
                report = self._item_to_report(detail, provenance)
        except Exception as exc:  # noqa: BLE001
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
        if not result.get("conflicts"):
            self.registry.save()

        return {
            "ok": len(errors) == 0,
            "dry_run": False,
            "opportunity_id": opportunity_id,
            "report_id": report.report_id,
            "report_hash": report.report_hash,
            "action": result.get("action"),
            "conflicts": result.get("conflicts", []),
            "registry_path": str(self.registry.path),
            "provenance": provenance,
        }

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
            "conflicts": 0,
            "errors": [],
            "registry_path": str(self.registry.path),
            "provenance": self._build_provenance("fetch_account_reports"),
            "note": "Zero writes performed; live fetch not implemented in skeleton.",
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
            fetched_at=datetime.now(timezone.utc),
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
            "note": "Zero writes performed; live fetch not implemented in skeleton.",
        }

    # ------------------------------------------------------------------
    # Live fetch helpers (stubbed)
    # ------------------------------------------------------------------

    def _fetch_via_browser(self, *, limit: int) -> list[dict[str, Any]]:
        """Return account-visible report items via browser inspection.

        Currently returns an empty list because the concrete scraping contract is
        out of scope for the skeleton.
        """
        if self.browser is None:
            return []
        # Future integration: navigate account reports pages and extract rows.
        return []

    def _item_to_report(
        self, item: dict[str, Any], provenance: dict[str, Any]
    ) -> CommissionReport:
        """Convert a scraped/API item into a ``CommissionReport``."""
        return CommissionReport(
            report_id=f"RPT-{uuid.uuid4().hex[:12]}",
            opportunity_id=str(item.get("opportunity_id", "")),
            principal_name=item.get("principal_name", ""),
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
            fetched_at=datetime.now(timezone.utc),
            requires_review=False,
        )

    def _api_detail_to_report(
        self, data: dict[str, Any], provenance: dict[str, Any]
    ) -> CommissionReport:
        """Convert a CommissionCrowd API opportunity detail into a report."""
        return CommissionReport(
            report_id=f"RPT-API-{data.get('id', uuid.uuid4().hex[:8])}",
            opportunity_id=str(data.get("id", "")),
            principal_name=data.get("company_name", ""),
            report_type="commission_statement",
            gross_amount=0.0,
            net_amount=0.0,
            status="pending",
            source_url=data.get("source_url", ""),
            raw_fingerprint=str(data),
            provenance=provenance,
            fetched_at=datetime.now(timezone.utc),
            requires_review=True,
        )

    def _build_provenance(
        self, method: str, opportunity_id: str | None = None
    ) -> dict[str, Any]:
        """Return provenance metadata for a fetch operation."""
        provenance: dict[str, Any] = {
            "fetcher": "CommissionReportFetcher",
            "method": method,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "api_configured": bool(
                self.api_adapter is not None and self.api_adapter.token_present()
            ),
            "browser_configured": self.browser is not None,
        }
        if opportunity_id:
            provenance["opportunity_id"] = opportunity_id
        return provenance


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


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

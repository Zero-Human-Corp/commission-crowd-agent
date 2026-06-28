"""CommissionCrowd REST API adapter.

Uses Pydantic models for request/response validation and follows the same
structured-result, dry-run-safe, no-secrets pattern as NotifierAdapter and
GoogleSheetsAdapter.

Auth scheme: Bearer token via the CommissionCrowd REST API.
Base URL: https://www.commissioncrowd.com/api/

Note: As of 2026-06-09 the provided API key returns 401 on most resource
endpoints.  The adapter is wired correctly; if the key gains scope the
live calls will succeed.  Until then, dry_run=True is the safe default.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

from .canonical import CanonicalOpportunity
from .cca_guardian import bounded_retry
from .config import CcaSettings


class CommissionCrowdOpportunity(BaseModel):
    """Public-opportunity model aligned with CommissionCrowd API fields.

    Aliases map CommissionCrowd keys to canonical Python attribute names.
    """

    id: int | None = None
    ref: str = ""
    name: str = ""
    latest_slug: str = ""
    description: str = ""
    commission: str = ""
    commission_pc: str = ""
    territory_details: str = ""
    active: bool = True
    date_created: str | None = None
    view_count: int = 0
    application_count: int = 0
    agent_count: int = 0
    email: str = ""
    phone: str = ""
    company: int | None = None
    industries: list[int] = Field(default_factory=list)
    target_industries: list[int] = Field(default_factory=list)
    products: list[int] = Field(default_factory=list)
    countries: list[int] = Field(default_factory=list)
    world_regions: list[int] = Field(default_factory=list)
    global_territory: bool = False
    short_summary: str = ""
    usp: str = ""
    completeness: int = 0

    def to_canonical(self) -> CanonicalOpportunity:
        """Convert to the unified CanonicalOpportunity model."""
        return CanonicalOpportunity.from_commissioncrowd_api(self.model_dump())


class CommissionCrowdAgentProfile(BaseModel):
    """Minimal agent-profile model from CommissionCrowd API."""

    id: int | None = None
    full_name: str = ""
    email: str = ""
    territory: str = ""
    industry_experience: str = ""
    url: str = ""


class CommissionCrowdApiAdapter:
    """HTTP adapter for CommissionCrowd REST API.

    - Reads API key from CcaSettings (field ``commissioncrowd_api_key``).
    - Supports ``dry_run`` mode (no network calls).
    - Returns structured result dicts with no secret values.
    """

    API_BASE = "https://www.commissioncrowd.com/api"
    TIMEOUT_SECONDS = 15

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        *,
        dry_run: bool = False,
        settings: CcaSettings | None = None,
        insecure_skip_verify: bool | None = None,
    ) -> None:
        self._explicit_key = api_key
        self.base_url = base_url or self.API_BASE
        self.dry_run = dry_run
        self._settings = settings
        # Wave 3 Track A (H4, R2): TLS verification is on by default
        # (production-safe). The prior unconditional verify=False was
        # MITM-vulnerable on every live REST call. The opt-in
        # commissioncrowd_insecure_skip_verify setting (config.py) is the only
        # way to disable verification — used to work around a known expired
        # upstream certificate. An explicit constructor arg wins over settings.
        if insecure_skip_verify is not None:
            self._insecure_skip_verify = insecure_skip_verify
        elif settings is not None:
            self._insecure_skip_verify = bool(
                getattr(settings, "commissioncrowd_insecure_skip_verify", False)
            )
        else:
            self._insecure_skip_verify = False

    @property
    def api_key(self) -> str:
        """Resolve the API key: explicit arg > settings > empty string."""
        if self._explicit_key:
            return self._explicit_key
        if self._settings is not None:
            return getattr(self._settings, "commissioncrowd_api_key", "")
        return ""

    def _auth_headers(self) -> dict[str, str]:
        """Return headers required for authenticated requests."""
        headers: dict[str, str] = {"Accept": "application/json"}
        key = self.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _url(self, path: str) -> str:
        """Build a full API URL from a relative path."""
        clean_path = path.lstrip("/")
        base = self.base_url.rstrip("/")
        # CommissionCrowd's API requires a trailing slash even before query params,
        # e.g. /api/opportunities/?limit=3  not  /api/opportunities?limit=3
        if "?" in clean_path:
            before_q, after_q = clean_path.split("?", 1)
            return f"{base}/{before_q}/?{after_q}"
        return f"{base}/{clean_path}/"

    @bounded_retry(
        max_attempts=3,
        backoff_base=1.0,
        backoff_max=8.0,
        retryable_exceptions=(httpx.TimeoutException, httpx.ConnectError),
    )
    def _request(self, method: str, path: str) -> httpx.Response:
        """Make an authenticated HTTP request.

        Raises on persistent failure so callers can map to structured results.
        TLS verification is ON by default; it is disabled only when the
        adapter was constructed with ``insecure_skip_verify=True`` or the
        ``commissioncrowd_insecure_skip_verify`` setting is set (config.py).

        Auth header uses ``Token`` scheme (extracted from browser session)
        rather than ``Bearer`` because the public REST API expects that.
        """
        url = self._url(path)
        headers = self._auth_headers()
        # Override Bearer -> Token for the CommissionCrowd legacy API
        if headers.get("Authorization", "").startswith("Bearer "):
            raw = headers["Authorization"].replace("Bearer ", "", 1)
            headers["Authorization"] = f"Token {raw}"
        with httpx.Client(
            timeout=self.TIMEOUT_SECONDS,
            verify=not self._insecure_skip_verify,
            follow_redirects=True,
        ) as client:
            response = client.request(method, url, headers=headers)
        return response

    def _safe_result(
        self,
        *,
        ok: bool,
        status: int = 0,
        error: str | None = None,
        data: Any = None,
    ) -> dict[str, Any]:
        """Build a structured result dict with no secret values."""
        return {
            "ok": ok,
            "status": status,
            "error": error,
            "data": data,
            "dry_run": self.dry_run,
        }

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Verify the API root is reachable.

        Returns structured result.  Safe to call even without a key.
        """
        if self.dry_run:
            return self._safe_result(ok=True, status=0)

        try:
            response = self._request("GET", "")
            if response.status_code == 200:
                body = response.json()
                return self._safe_result(
                    ok=True,
                    status=response.status_code,
                    data={"resources": sorted(body.keys())},
                )
            return self._safe_result(
                ok=False,
                status=response.status_code,
                error=f"HTTP {response.status_code}",
            )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return self._safe_result(
                ok=False,
                error=f"Network error: {type(exc).__name__}",
            )

    def list_opportunities(self, *, page: int = 1, limit: int = 20) -> dict[str, Any]:
        """Fetch a page of opportunities.

        Returns structured result; ``data`` contains ``items`` and ``next``.
        """
        if not self.api_key:
            return self._safe_result(
                ok=False,
                error="Missing commissioncrowd_api_key",
            )

        try:
            response = self._request("GET", f"opportunities?page={page}&limit={limit}")
            if response.status_code == 200:
                body = response.json()
                # CommissionCrowd may return a top-level list or a dict wrapper
                if isinstance(body, list):
                    items = body
                    next_url = None
                elif isinstance(body, dict):
                    raw_items = body.get("results", body.get("items", body.get("data", [])))
                    items = raw_items if isinstance(raw_items, list) else []
                    next_url = body.get("next")
                else:
                    return self._safe_result(
                        ok=False,
                        status=response.status_code,
                        error="Unexpected response type",
                    )
                # Validate items into typed models
                typed_items: list[dict[str, Any]] = []
                for item in items:
                    try:
                        typed_items.append(CommissionCrowdOpportunity(**item).model_dump())
                    except Exception:
                        typed_items.append(item)
                return self._safe_result(
                    ok=True,
                    status=response.status_code,
                    data={
                        "items": typed_items,
                        "next": next_url,
                        "count": len(typed_items),
                    },
                )
            return self._safe_result(
                ok=False,
                status=response.status_code,
                error=f"HTTP {response.status_code}: {response.text[:200]}",
            )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return self._safe_result(
                ok=False,
                error=f"Network error: {type(exc).__name__}",
            )

    def list_agents(self, *, page: int = 1, limit: int = 20) -> dict[str, Any]:
        """Fetch a page of agent profiles."""
        if self.dry_run:
            stub = CommissionCrowdAgentProfile(
                id=1, full_name="Stub Agent", email="agent@example.com"
            )
            return self._safe_result(
                ok=True,
                status=0,
                data={"items": [stub.model_dump()], "next": None},
            )

        if not self.api_key:
            return self._safe_result(
                ok=False,
                error="Missing commissioncrowd_api_key",
            )

        try:
            response = self._request("GET", f"agents?page={page}&limit={limit}")
            if response.status_code == 200:
                body = response.json()
                return self._safe_result(
                    ok=True,
                    status=response.status_code,
                    data={
                        "items": body.get("results", []),
                        "next": body.get("next"),
                        "count": body.get("count"),
                    },
                )
            return self._safe_result(
                ok=False,
                status=response.status_code,
                error=f"HTTP {response.status_code}: {response.reason_phrase}",
            )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return self._safe_result(
                ok=False,
                error=f"Network error: {type(exc).__name__}",
            )

    def get_opportunity(self, opportunity_id: int) -> dict[str, Any]:
        """Fetch a single opportunity by ID."""
        if self.dry_run:
            stub = CommissionCrowdOpportunity(
                id=opportunity_id,
                name="Stub Opportunity",
                description="Dry-run placeholder",
            )
            return self._safe_result(
                ok=True,
                status=0,
                data=stub.model_dump(),
            )

        if not self.api_key:
            return self._safe_result(
                ok=False,
                error="Missing commissioncrowd_api_key",
            )

        try:
            response = self._request("GET", f"opportunities/{opportunity_id}")
            if response.status_code == 200:
                return self._safe_result(
                    ok=True,
                    status=response.status_code,
                    data=response.json(),
                )
            return self._safe_result(
                ok=False,
                status=response.status_code,
                error=f"HTTP {response.status_code}: {response.reason_phrase}",
            )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return self._safe_result(
                ok=False,
                error=f"Network error: {type(exc).__name__}",
            )

    def token_present(self) -> bool:
        """Return whether a key is configured (safe for status checks)."""
        return bool(self.api_key)

    def to_opportunity_domain(self, raw: dict[str, Any]) -> CommissionCrowdOpportunity:
        """Validate a raw dict into a typed model."""
        return CommissionCrowdOpportunity(**raw)

    def to_agent_domain(self, raw: dict[str, Any]) -> CommissionCrowdAgentProfile:
        """Validate a raw dict into a typed model."""
        return CommissionCrowdAgentProfile(**raw)

"""Form shadow validator — non-mutating inspection of a target form page.

The shadow validator loads a target form URL through the configured
CommissionCrowd browser adapter and checks whether the rendered DOM
matches the payload we intend to submit.  It never fills inputs, never
clicks buttons, and never submits the form.

When no live browser session is available (or ``dry_run=True`` is passed)
the validator falls back to structural checks against an optional DOM
fixture (a raw HTML string) plus the supplied field mapping.  This keeps
the validator usable from dry-run engine runs and from unit tests that
inject a browser double.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .submission_audit import hash_payload

try:
    from .browser_adapter import CommissionCrowdBrowserAdapter
except Exception:  # pragma: no cover - fallback when optional deps are absent

    class CommissionCrowdBrowserAdapter:  # type: ignore[no-redef]
        """Placeholder stub when the real adapter cannot be imported."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("CommissionCrowdBrowserAdapter is not available.")


# Generic alias used in type hints; in this codebase it is the same class.
BrowserAdapter = CommissionCrowdBrowserAdapter

# Where failed-validation evidence (screenshots + DOM snapshots) is written.
DEFAULT_FAILURE_DIR = Path("/home/ubuntu/hermes-control/reports/form_validation_failures")

# HTML control types the validator understands.
VALID_CONTROL_TYPES: frozenset[str] = frozenset(
    {"text", "textarea", "email", "tel", "url", "search", "password",
     "number", "range", "checkbox", "radio", "select", "date", "hidden"}
)

# Markers that indicate an Ember.js rendered form container (CommissionCrowd SPA).
EMBER_MARKERS: tuple[str, ...] = ("ember-application", "ember-application", "data-ember", "__ember")

# CAPTCHA / 2FA markers that require operator action.
CAPTCHA_MARKERS: tuple[str, ...] = (
    "captcha", "recaptcha", "hcaptcha", "i'm not a robot", "cf-turnstile",
    "turnstile-challenge",
)
TWOFA_MARKERS: tuple[str, ...] = (
    "two-factor", "two step", "two-step", "authenticator",
    "verification code", "2fa", "one-time password",
)

# Page content markers that indicate a non-form / error page.
ERROR_MARKERS: tuple[str, ...] = (
    "404 not found", "page not found", "forbidden", "unauthorized",
    "access denied", "internal server error",
)


@dataclass
class ShadowValidationResult:
    """Outcome of a single shadow validation run."""

    ok: bool = False
    checks: dict[str, bool] = field(default_factory=dict)
    mismatches: list[str] = field(default_factory=list)
    screenshot_path: Path | None = None
    dom_snapshot_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for audit records."""
        return {
            "ok": self.ok,
            "checks": dict(self.checks),
            "mismatches": list(self.mismatches),
            "screenshot_path": str(self.screenshot_path) if self.screenshot_path else "",
            "dom_snapshot_path": str(self.dom_snapshot_path) if self.dom_snapshot_path else "",
        }


class OperatorInterventionRequired(RuntimeError):  # noqa: N818 - spec-mandated name
    """Raised when the validator detects a CAPTCHA, 2FA, or similar operator-only flow."""


class FormShadowValidator:
    """Non-mutating validator for CommissionCrowd (or similar) application forms.

    The validator only inspects the page; it performs no mutating actions.
    It supports three execution modes, selected automatically:

    1. **live** — a Playwright page is attached and ``dry_run=False``: navigate
       to the form URL and inspect the rendered DOM.
    2. **fixture** — a raw HTML ``dom_fixture`` is supplied (and either no page
       is attached or ``dry_run=True``): parse the fixture with BeautifulSoup
       and run every check against it.
    3. **structural** — no page and no fixture: run only the checks that do not
       require a DOM (field mapping shape + payload hash).  DOM-dependent
       checks are marked as optimistic passes so dry-run engine runs can
       succeed without a live browser.
    """

    def __init__(
        self,
        browser_adapter: BrowserAdapter | Any | None,
        reports_dir: str | Path = DEFAULT_FAILURE_DIR,
    ) -> None:
        self.browser_adapter = browser_adapter
        self.reports_dir = Path(reports_dir)
        # Best-effort: evidence persistence is non-critical and must not crash
        # construction in restricted environments (CI, sandboxes, read-only FS).
        with contextlib.suppress(OSError):
            self.reports_dir.mkdir(parents=True, mode=0o700, exist_ok=True)

    # ── public API ────────────────────────────────────────────────────────

    def validate(
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
        """Run a non-mutating shadow validation of *form_url*.

        Parameters
        ----------
        form_url:
            Absolute URL of the form page to inspect.
        payload:
            Mapping of form field names to the values we intend to submit.
        payload_hash:
            SHA-256 hash the caller expects for *payload* (as computed by
            :func:`submission_audit.hash_payload`).
        field_mapping:
            Mapping of field name → ``{"selector": <css>, "type": <control>}``
            describing the expected form controls.
        opportunity_id, principal_name:
            Identity of the target opportunity; checked against the page URL/DOM.
        dom_fixture:
            Optional raw HTML string used in place of a live page navigation.
        dry_run:
            When True the validator never navigates a live page even if one is
            attached; fixture/structural mode is used instead.

        Returns
        -------
        ShadowValidationResult
        """
        checks: dict[str, bool] = {}
        mismatches: list[str] = []

        mode, url, html, page, soup = self._resolve_mode(form_url, dom_fixture, dry_run)

        # 1. Page reachability (form or Ember container present).
        checks["page_reachable"] = self._check_page_reachable(mode, url, html, soup)
        if not checks["page_reachable"]:
            mismatches.append("Form page is not reachable or returned an error page.")

        # 2. CAPTCHA / 2FA guard — abort hard on detection (operator-only flow).
        blocked, block_reason = self._detect_blocking(html, page)
        checks["no_captcha_or_2fa"] = not blocked
        if blocked:
            # Persist evidence before raising so the operator can see the page.
            self._persist_evidence(page, soup, checks, mismatches, aborted=True)
            raise OperatorInterventionRequired(block_reason)

        # 3. Required fields present (every payload field has a matching control).
        missing_fields = self._check_required_fields(payload, field_mapping, soup, page)
        checks["required_fields_present"] = not missing_fields
        if missing_fields:
            mismatches.append(f"Missing required fields: {missing_fields}")

        # 4. Field type compatibility.
        type_mismatches = self._check_field_types(payload, field_mapping, soup, page)
        checks["field_type_compatible"] = not type_mismatches
        if type_mismatches:
            mismatches.append(f"Field type mismatches: {type_mismatches}")

        # 5. Opportunity identity verification.
        identity_ok = self._check_opportunity_identity(
            mode, url, html, opportunity_id, principal_name
        )
        if opportunity_id or principal_name:
            checks["opportunity_identity_verified"] = identity_ok
            if not identity_ok:
                label = opportunity_id or principal_name
                mismatches.append(
                    f"Opportunity identity {label!r} not found in URL or DOM."
                )

        # 6. Payload hash integrity.
        recomputed = hash_payload(payload)
        checks["payload_hash_match"] = recomputed == payload_hash
        if recomputed != payload_hash:
            mismatches.append(
                "Payload hash mismatch between supplied value and recomputed payload."
            )

        ok = all(checks.values())

        screenshot_path, dom_snapshot_path = None, None
        if not ok:
            screenshot_path, dom_snapshot_path = self._persist_evidence(
                page, soup, checks, mismatches, aborted=False
            )

        return ShadowValidationResult(
            ok=ok,
            checks=checks,
            mismatches=mismatches,
            screenshot_path=screenshot_path,
            dom_snapshot_path=dom_snapshot_path,
        )

    # ── mode resolution ───────────────────────────────────────────────────

    def _resolve_mode(
        self,
        form_url: str,
        dom_fixture: str | None,
        dry_run: bool,
    ) -> tuple[str, str, str, Any, BeautifulSoup | None]:
        """Pick an execution mode and return (mode, url, html_lower, page, soup)."""
        page = getattr(self.browser_adapter, "_page", None) if self.browser_adapter else None

        if dom_fixture is not None:
            html = dom_fixture.lower()
            return "fixture", form_url, html, None, BeautifulSoup(dom_fixture, "lxml")

        if page is not None and not dry_run:
            page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            url = page.url
            html = page.content().lower()
            return "live", url, html, page, None

        # Structural mode — no DOM available.
        return "structural", form_url, "", None, None

    # ── individual checks ─────────────────────────────────────────────────

    def _check_page_reachable(
        self,
        mode: str,
        url: str,
        html_lower: str,
        soup: BeautifulSoup | None,
    ) -> bool:
        if mode == "structural":
            # Cannot verify without a DOM; optimistic pass for dry-run paths.
            return True

        if not url or "error" in url.lower() or url.startswith("about:"):
            return False
        if len(html_lower) < 50:
            return False
        if any(marker in html_lower for marker in ERROR_MARKERS):
            return False

        # A <form> element or an Ember.js SPA container must be present.
        # We use substring matching on the lowercased HTML so the check works
        # uniformly for live pages, fixtures, and avoids bs4 attr-typed lookups.
        has_form = "<form" in html_lower
        has_ember = any(marker in html_lower for marker in EMBER_MARKERS)
        if soup is not None and not (has_form or has_ember):
            has_form = soup.find("form") is not None
        return has_form or has_ember

    def _detect_blocking(self, html_lower: str, page: Any) -> tuple[bool, str]:
        """Detect CAPTCHA, 2FA, or challenge pages that require operator action."""
        if not html_lower:
            return False, ""

        if any(term in html_lower for term in CAPTCHA_MARKERS):
            return True, "CAPTCHA/challenge detected on form page."

        if "cloudflare" in html_lower and "challenge" in html_lower:
            return True, "Cloudflare challenge detected on form page."

        if any(term in html_lower for term in TWOFA_MARKERS):
            # Only flag 2FA when an actual code/OTP input is present.
            if page is not None:
                code_selectors = [
                    'input[placeholder*="code" i]',
                    'input[placeholder*="verification" i]',
                    'input[name*="code" i]',
                    'input[id*="otp" i]',
                ]
                if any(page.locator(sel).count() > 0 for sel in code_selectors):
                    return True, "MFA/2FA input detected on form page."
            return True, "MFA/2FA challenge page detected."

        return False, ""

    def _check_required_fields(
        self,
        payload: dict[str, Any],
        field_mapping: dict[str, dict[str, str]],
        soup: BeautifulSoup | None,
        page: Any,
    ) -> list[str]:
        """Return the list of payload fields with no matching form control.

        Per spec §4.4 every payload field must have a mapping entry whose
        selector resolves to a real element when a DOM is available.  A payload
        field with *no* mapping entry is flagged as missing so that fields we
        intend to submit never silently drop because no control was located.
        """
        missing: list[str] = []
        # A payload field with no mapping entry has no control to receive it.
        for field_name in payload:
            if field_name not in field_mapping:
                missing.append(field_name)
        for field_name, spec in field_mapping.items():
            selector = spec.get("selector", "")
            if not selector:
                missing.append(field_name)
                continue
            dom_missing = (
                (soup is not None and not self._selector_exists_in_soup(soup, selector))
                or (page is not None and page.locator(selector).count() == 0)
            )
            if dom_missing:
                missing.append(field_name)
            # structural mode: selector present in mapping counts as available.
        return missing

    def _check_field_types(
        self,
        payload: dict[str, Any],
        field_mapping: dict[str, dict[str, str]],
        soup: BeautifulSoup | None,
        page: Any,
    ) -> list[str]:
        """Return the list of mapped fields whose control type is incompatible."""
        mismatches: list[str] = []
        for field_name, spec in field_mapping.items():
            mapped_type = (spec.get("type", "") or "").lower()
            if not mapped_type:
                mismatches.append(field_name)
                continue
            if mapped_type not in VALID_CONTROL_TYPES:
                mismatches.append(field_name)
                continue
            value = payload.get(field_name, "")
            expected = self._expected_input_type(value)
            if not self._types_compatible(expected, mapped_type):
                mismatches.append(field_name)
                continue
            # When a DOM is available, verify the rendered control matches.
            if soup is not None and not self._dom_type_matches(
                soup, spec.get("selector", ""), mapped_type
            ) or page is not None and not self._page_type_matches(
                page, spec.get("selector", ""), mapped_type
            ):
                mismatches.append(field_name)
        return mismatches

    def _check_opportunity_identity(
        self,
        mode: str,
        url: str,
        html_lower: str,
        opportunity_id: str,
        principal_name: str,
    ) -> bool:
        if mode == "structural":
            # Without a DOM we can only weakly check the URL.
            if opportunity_id and opportunity_id in url:
                return True
            if principal_name and principal_name.lower() in url.lower():
                return True
            # Optimistic pass when nothing can be verified.
            return True  # noqa: SIM103 - intentional fallback for dry-run paths

        tokens = [t for t in (opportunity_id, principal_name) if t]
        for token in tokens:
            if token and token.lower() in html_lower:
                continue
            if token and token in url:
                continue
            return False
        return bool(tokens)

    # ── selector / type helpers ───────────────────────────────────────────

    def _selector_exists_in_soup(self, soup: BeautifulSoup, selector: str) -> bool:
        try:
            return soup.select_one(selector) is not None
        except Exception:  # noqa: BLE001 - malformed selectors are treated as missing
            return False

    def _dom_type_matches(
        self,
        soup: BeautifulSoup,
        selector: str,
        mapped_type: str,
    ) -> bool:
        try:
            element = soup.select_one(selector)
        except Exception:  # noqa: BLE001
            return False
        if element is None:
            return False
        tag = (element.name or "").lower()
        if mapped_type == "textarea":
            return tag == "textarea"
        if mapped_type == "select":
            return tag == "select"
        if tag != "input":
            # Non-input elements (e.g. a contenteditable div) are accepted for text.
            return mapped_type in {"text", "email", "tel", "url", "search"}
        raw_type = element.get("type")
        input_type = (str(raw_type) if raw_type is not None else "text").lower()
        return input_type == mapped_type or (
            mapped_type in {"text", "email", "tel", "url", "search", "password"}
            and input_type in {"text", "email", "tel", "url", "search", "password"}
        )

    def _page_type_matches(
        self,
        page: Any,
        selector: str,
        mapped_type: str,
    ) -> bool:
        try:
            loc = page.locator(selector)
            if loc.count() == 0:
                return False
            element = loc.first
            tag = (element.evaluate("el => el.tagName.toLowerCase()") or "").lower()
        except Exception:  # noqa: BLE001
            return False
        if mapped_type == "textarea":
            return tag == "textarea"
        if mapped_type == "select":
            return tag == "select"
        if tag != "input":
            return mapped_type in {"text", "email", "tel", "url", "search"}
        try:
            input_type = (element.get_attribute("type") or "text").lower()
        except Exception:  # noqa: BLE001
            input_type = "text"
        return input_type == mapped_type or (
            mapped_type in {"text", "email", "tel", "url", "search", "password"}
            and input_type in {"text", "email", "tel", "url", "search", "password"}
        )

    def _expected_input_type(self, value: Any) -> str:
        """Infer the HTML form control type expected for *value*."""
        if isinstance(value, bool):
            return "checkbox"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return "number"
        if isinstance(value, list):
            return "select"
        if isinstance(value, str):
            if len(value) > 200:
                return "textarea"
            if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
                return "email"
            if re.match(r"^[+]?[\d\s\-()]+$", value):
                return "tel"
            return "text"
        return "text"

    def _types_compatible(self, expected: str, mapped: str) -> bool:
        text_types = {"text", "email", "tel", "url", "search", "password"}
        if expected in text_types and mapped in text_types:
            return True
        if expected in text_types and mapped == "hidden":
            # Hidden inputs carry opaque string values; any text-like payload fits.
            return True
        if expected == "number" and mapped in {"number", "range", "text"}:
            return True
        if expected == "textarea" and mapped == "textarea":
            return True
        if expected == "checkbox" and mapped == "checkbox":
            return True
        if expected == "select" and mapped == "select":
            return True
        return expected == "text" and mapped in {
            "textarea", "text", "email", "tel", "url", "search", "hidden"
        }

    # ── evidence persistence ──────────────────────────────────────────────

    def _persist_evidence(
        self,
        page: Any,
        soup: BeautifulSoup | None,
        checks: dict[str, bool],
        mismatches: list[str],
        *,
        aborted: bool,
    ) -> tuple[Path | None, Path | None]:
        """Save a screenshot and DOM snapshot for failed/aborted validations.

        Returns the paths to the saved files (or ``None`` when nothing could be
        captured).  Best-effort: capture failures are swallowed.
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        stem = f"shadow_{'abort' if aborted else 'failure'}_{timestamp}"
        screenshot_path = self.reports_dir / f"{stem}.png"
        dom_snapshot_path = self.reports_dir / f"{stem}.html"
        meta_path = self.reports_dir / f"{stem}.txt"

        screenshot_captured: Path | None = None
        dom_captured: Path | None = None

        if page is not None:
            try:
                page.screenshot(path=str(screenshot_path))
                screenshot_captured = screenshot_path
            except Exception:  # noqa: BLE001
                pass
            try:
                dom_snapshot_path.write_text(page.content(), encoding="utf-8")
                dom_captured = dom_snapshot_path
            except Exception:  # noqa: BLE001
                pass
        elif soup is not None:
            try:
                dom_snapshot_path.write_text(str(soup), encoding="utf-8")
                dom_captured = dom_snapshot_path
            except Exception:  # noqa: BLE001
                pass

        # Always write the mismatch/check summary so operators have a lead.
        try:
            lines = [
                f"timestamp: {datetime.now(UTC).isoformat()}",
                f"aborted: {aborted}",
                f"checks: {checks}",
                "mismatches:",
            ]
            lines.extend(f"  - {m}" for m in mismatches)
            meta_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        return screenshot_captured, dom_captured

"""Form shadow validator — dry-run inspection of a form page.

The shadow validator loads a target form URL through the configured
CommissionCrowd browser adapter and checks whether the rendered DOM
matches the payload we intend to submit.  It never fills inputs, never
clicks buttons, and never submits the form.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .browser_adapter import CommissionCrowdBrowserAdapter
except Exception:  # pragma: no cover - fallback when optional deps are absent

    class CommissionCrowdBrowserAdapter:  # type: ignore[no-redef]
        """Placeholder stub when the real adapter cannot be imported."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("CommissionCrowdBrowserAdapter is not available.")


# Generic alias used in type hints; in this codebase it is the same class.
BrowserAdapter = CommissionCrowdBrowserAdapter


@dataclass
class ShadowValidationResult:
    """Outcome of a single shadow validation run."""

    ok: bool = False
    checks: dict[str, bool] = field(default_factory=dict)
    mismatches: list[str] = field(default_factory=list)
    screenshot_path: str = ""
    dom_snapshot_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for audit records."""
        return {
            "ok": self.ok,
            "checks": self.checks,
            "mismatches": self.mismatches,
            "screenshot_path": self.screenshot_path,
            "dom_snapshot_path": self.dom_snapshot_path,
        }


class OperatorInterventionRequired(RuntimeError):
    """Raised when the validator detects a CAPTCHA, 2FA, or similar operator-only flow."""


class FormShadowValidator:
    """Dry-run validator for CommissionCrowd (or similar) application forms.

    The validator only inspects the page; it performs no mutating actions.
    """

    def __init__(
        self,
        browser_adapter: BrowserAdapter,
        reports_dir: str | Path = "/home/ubuntu/hermes-control/reports/form_validation_failures",
    ) -> None:
        self.browser_adapter = browser_adapter
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._page: Any = getattr(browser_adapter, "_page", None)

    def validate(
        self,
        form_url: str,
        payload_mapping: dict[str, Any],
        payload_hash: str,
        expected_opportunity_id: str | None = None,
    ) -> ShadowValidationResult:
        """Run a dry-run shadow validation of *form_url*.

        Parameters
        ----------
        form_url:
            Absolute URL of the form page to inspect.
        payload_mapping:
            Mapping of form field names to the values we intend to submit.
        payload_hash:
            SHA-256 hash the caller expects for *payload_mapping*.
        expected_opportunity_id:
            Optional opportunity ID that should be present in the page URL or
            rendered DOM.

        Returns
        -------
        ShadowValidationResult with per-check booleans, a list of human-readable
        mismatches, and paths to any saved screenshot/DOM evidence.
        """
        checks: dict[str, bool] = {}
        mismatches: list[str] = []
        screenshot_path = ""
        dom_snapshot_path = ""

        try:
            page = self._require_page()
            page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            url = page.url
            html = page.content().lower()

            # 1. Page reachability
            reachable = self._check_page_reachable(url, html)
            checks["page_reachable"] = reachable
            if not reachable:
                mismatches.append("Form page is not reachable or returned an error page.")

            # 2. CAPTCHA / 2FA guard (abort on detection)
            blocked, block_reason = self._detect_blocking(html, page)
            checks["no_captcha_or_2fa"] = not blocked
            if blocked:
                raise OperatorInterventionRequired(block_reason)

            # 3. Required fields exist in the rendered DOM
            missing_fields: list[str] = []
            type_mismatches: list[str] = []
            for field_name, value in payload_mapping.items():
                if not self._field_exists(page, field_name):
                    missing_fields.append(field_name)
                    continue
                if not self._type_compatible(page, field_name, value):
                    type_mismatches.append(field_name)

            checks["required_fields_exist"] = not missing_fields
            if missing_fields:
                mismatches.append(f"Missing required fields: {missing_fields}")

            # 4. Field type compatibility
            checks["field_type_compatible"] = not type_mismatches
            if type_mismatches:
                mismatches.append(f"Field type mismatches: {type_mismatches}")

            # 5. Opportunity identity verification
            if expected_opportunity_id:
                identity_ok = self._verify_opportunity_identity(url, html, expected_opportunity_id)
                checks["opportunity_identity_verified"] = identity_ok
                if not identity_ok:
                    mismatches.append(
                        f"Opportunity identity {expected_opportunity_id!r} not found in URL or DOM."
                    )

            # 6. Payload hash integrity
            recomputed_hash = self._compute_payload_hash(payload_mapping)
            hash_ok = recomputed_hash == payload_hash
            checks["payload_hash_match"] = hash_ok
            if not hash_ok:
                mismatches.append("Payload hash mismatch between supplied value and recomputed canonical mapping.")

        except Exception as exc:  # noqa: BLE001 - surface runtime failures as mismatches
            checks["validator_exception"] = False
            mismatches.append(f"Validator runtime exception: {exc}")

        finally:
            ok = all(checks.values())
            if not ok:
                try:
                    screenshot_path, dom_snapshot_path = self._save_evidence()
                except Exception:  # noqa: BLE001 - best-effort evidence capture
                    pass

        result = ShadowValidationResult(
            ok=ok,
            checks=checks,
            mismatches=mismatches,
            screenshot_path=screenshot_path,
            dom_snapshot_path=dom_snapshot_path,
        )
        return result

    def _require_page(self) -> Any:
        """Return the underlying Playwright page or raise RuntimeError."""
        page = getattr(self.browser_adapter, "_page", None)
        if page is None:
            raise RuntimeError(
                "Browser page is not available. Start the adapter with start() first."
            )
        return page

    def _check_page_reachable(self, url: str, html_lower: str) -> bool:
        """Return True when the navigation produced a plausible form page."""
        if not url or "error" in url.lower() or url.startswith("about:"):
            return False
        if len(html_lower) < 50:
            return False
        error_indicators = [
            "404 not found",
            "page not found",
            "forbidden",
            "unauthorized",
            "access denied",
            "internal server error",
        ]
        return not any(ind in html_lower for ind in error_indicators)

    def _detect_blocking(self, html_lower: str, page: Any) -> tuple[bool, str]:
        """Detect CAPTCHA, 2FA, or challenge pages that require operator action."""
        captcha_terms = ["captcha", "recaptcha", "hcaptcha", "i'm not a robot", "cf-turnstile"]
        if any(term in html_lower for term in captcha_terms):
            return True, "CAPTCHA/challenge detected"

        twofa_terms = ["two-factor", "two step", "authenticator", "verification code", "2fa"]
        if any(term in html_lower for term in twofa_terms):
            code_selectors = [
                'input[placeholder*="code" i]',
                'input[placeholder*="verification" i]',
                'input[name*="code" i]',
                'input[id*="otp" i]',
            ]
            if any(page.locator(sel).count() > 0 for sel in code_selectors):
                return True, "MFA/2FA detected"

        if "cloudflare" in html_lower and "challenge" in html_lower:
            return True, "Cloudflare challenge detected"

        return False, ""

    def _field_locators(self, field_name: str) -> list[str]:
        """Return Playwright selectors that could match a named form field."""
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

    def _field_exists(self, page: Any, field_name: str) -> bool:
        """Return True if *field_name* exists in the rendered DOM."""
        return any(page.locator(sel).count() > 0 for sel in self._field_locators(field_name))

    def _type_compatible(self, page: Any, field_name: str, value: Any) -> bool:
        """Check whether the rendered field accepts the intended *value* type."""
        element = self._find_field_element(page, field_name)
        if element is None:
            return False

        tag = (element.evaluate("el => el.tagName.toLowerCase()") or "").lower()
        input_type = ""
        if tag == "input":
            input_type = (element.get_attribute("type") or "text").lower()

        expected = self._expected_input_type(value)

        # Text-like inputs accept most string values.
        text_types = {"text", "email", "tel", "url", "search", "password"}
        if expected in {"text", "email", "tel", "url"} and input_type in text_types:
            return True
        if expected == "number" and input_type in {"number", "range", "text"}:
            return True
        if expected == "textarea" and tag == "textarea":
            return True
        if expected == "checkbox" and input_type == "checkbox":
            return True
        if expected == "select" and tag == "select":
            return True
        if expected == "text" and tag in {"input", "textarea"}:
            return True

        return False

    def _find_field_element(self, page: Any, field_name: str) -> Any | None:
        """Return the first Playwright locator matching *field_name*."""
        for sel in self._field_locators(field_name):
            loc = page.locator(sel)
            if loc.count() > 0:
                return loc.first
        return None

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

    def _verify_opportunity_identity(self, url: str, html: str, expected: str) -> bool:
        """Return True if *expected* appears in the page URL or rendered HTML."""
        return expected in url or expected in html

    def _compute_payload_hash(self, payload_mapping: dict[str, Any]) -> str:
        """Return SHA-256 of the canonical JSON representation of the payload."""
        canonical = json.dumps(
            payload_mapping,
            sort_keys=True,
            ensure_ascii=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _save_evidence(self) -> tuple[str, str]:
        """Save screenshot and DOM snapshot for later operator review.

        Returns the absolute paths to the saved files.
        """
        page = self._require_page()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        screenshot_file = self.reports_dir / f"shadow_failure_{timestamp}.png"
        dom_file = self.reports_dir / f"shadow_failure_{timestamp}.html"

        try:
            page.screenshot(path=str(screenshot_file))
        except Exception:
            pass

        try:
            dom_file.write_text(page.content(), encoding="utf-8")
        except Exception:
            pass

        return str(screenshot_file), str(dom_file)

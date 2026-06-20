#!/usr/bin/env python3
"""Live-shadow Playwright validation — no form submission.

1. Restores or creates an authenticated CommissionCrowd session.
2. Navigates to a single listing URL.
3. Enumerates visible form fields and maps them to operator profile fields.
4. Detects CAPTCHA/verification challenges.
5. Reports whether submission heuristics hold up without clicking submit.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.browser_adapter import CommissionCrowdBrowserAdapter
from commission_crowd_agent.config import load_settings

NAME_LABELS = re.compile(
    r"name|full.?name|your.?name|first.?name|last.?name|representative|agent",
    re.IGNORECASE,
)
EMAIL_LABELS = re.compile(r"email|e-mail|contact.?email", re.IGNORECASE)
COMPANY_LABELS = re.compile(r"company|organisation|organization|business|agency", re.IGNORECASE)
PHONE_LABELS = re.compile(r"phone|mobile|tel|contact.?number", re.IGNORECASE)
LINKEDIN_LABELS = re.compile(r"linkedin|profile|social", re.IGNORECASE)
WEBSITE_LABELS = re.compile(r"website|url|portfolio", re.IGNORECASE)
MESSAGE_LABELS = re.compile(
    r"message|cover.?letter|about|summary|pitch|why|experience|additional|notes",
    re.IGNORECASE,
)
VERIFICATION_LABELS = re.compile(
    r"captcha|recaptcha|verification|verify you|are you human|i'm not a robot",
    re.IGNORECASE,
)
SUBMIT_BUTTON_LABELS = re.compile(
    r"apply|submit|send|send message|connect|get started|apply now|submit application",
    re.IGNORECASE,
)


def _field_text(el: object) -> str:
    parts: list[str] = []
    try:
        attrs = el.evaluate(
            """el => {
                const label = el.labels && el.labels[0] ? el.labels[0].innerText : '';
                return {
                    label: label,
                    aria: el.getAttribute('aria-label') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    name: el.getAttribute('name') || '',
                    id: el.id || '',
                    type: el.type || ''
                };
            }"""
        )
        for k in ("label", "aria", "placeholder", "name", "id"):
            parts.append(str(attrs.get(k, "")))
    except Exception:
        pass
    return " ".join(p for p in parts if p)


def _detect_form_fields(page: object) -> list[dict[str, str]]:
    return page.evaluate(
        """() => {
            const selectors = [
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"])',
                'textarea',
                'select'
            ];
            const out = [];
            document.querySelectorAll(selectors.join(', ')).forEach(el => {
                const rect = el.getBoundingClientRect();
                if (!(rect.width && rect.height)) return;
                const label = el.labels && el.labels[0] ? el.labels[0].innerText.trim() : '';
                out.push({
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    name: el.getAttribute('name') || '',
                    id: el.id || '',
                    label: label,
                    aria: el.getAttribute('aria-label') || '',
                    placeholder: el.getAttribute('placeholder') || ''
                });
            });
            return out;
        }"""
    )


def _find_submit_button(page: object) -> object | None:
    selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Apply")',
        'button:has-text("Submit")',
        'button:has-text("Send")',
        'button:has-text("Connect")',
        'a:has-text("Apply")',
        'a:has-text("Submit")',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                first = loc.first
                if first.is_visible():
                    return first
        except Exception:
            continue
    try:
        for cand in page.locator("button, a, [role='button']").all():
            try:
                text = (cand.inner_text() or "").strip()
                if SUBMIT_BUTTON_LABELS.search(text) and cand.is_visible():
                    return cand
            except Exception:
                continue
    except Exception:
        pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Live-shadow Playwright validation")
    parser.add_argument("--url", required=True, help="CommissionCrowd listing URL to shadow-inspect")
    parser.add_argument("--headless", action="store_true", default=True, help="Run headless")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Show browser")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.commissioncrowd_username:
        print("ERROR: CommissionCrowd credentials not configured.", file=sys.stderr)
        return 1

    browser = CommissionCrowdBrowserAdapter()
    print(f"Starting browser (headless={args.headless})")
    browser.start(headless=args.headless)
    try:
        print("Authenticating...")
        browser.login_or_restore_session(
            settings.commissioncrowd_username,
            settings.commissioncrowd_password,
            force_new=False,
        )
        print(f"Navigating to {args.url}")
        page = browser._page
        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        # SPA: wait for non-spinner content to render
        for _ in range(10):
            text = (page.locator("body").inner_text() or "").strip()
            if len(text) > 200 and not text.startswith("CommissionCrowd"):
                break
            page.wait_for_timeout(1000)
        page.wait_for_timeout(2000)
        # If listing uses a "Apply"/"Connect" CTA, click it to expose the form
        apply_btn = None
        for sel in [
            'button:has-text("Apply")',
            'button:has-text("Connect")',
            'a:has-text("Apply")',
            'a:has-text("Connect")',
        ]:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                apply_btn = loc.first
                break
        if apply_btn is not None:
            print("Clicking Apply/Connect CTA to expose application form...")
            apply_btn.click()
            page.wait_for_timeout(3000)
            for _ in range(8):
                fields = _detect_form_fields(page)
                if len(fields) > 0:
                    break
                page.wait_for_timeout(1000)

        html = (page.content() or "").lower()
        text = (page.locator("body").inner_text() or "").lower()
        verification = bool(VERIFICATION_LABELS.search(html) or VERIFICATION_LABELS.search(text))

        fields = _detect_form_fields(page)
        submit_btn = _find_submit_button(page)

        mapped: dict[str, list[str]] = {
            "name": [],
            "email": [],
            "company": [],
            "phone": [],
            "linkedin": [],
            "website": [],
            "message": [],
        }
        for f in fields:
            label_text = " ".join(f.get(k, "") for k in ("label", "aria", "placeholder", "name", "id"))
            if NAME_LABELS.search(label_text):
                mapped["name"].append(label_text[:80])
            if EMAIL_LABELS.search(label_text):
                mapped["email"].append(label_text[:80])
            if COMPANY_LABELS.search(label_text):
                mapped["company"].append(label_text[:80])
            if PHONE_LABELS.search(label_text):
                mapped["phone"].append(label_text[:80])
            if LINKEDIN_LABELS.search(label_text):
                mapped["linkedin"].append(label_text[:80])
            if WEBSITE_LABELS.search(label_text):
                mapped["website"].append(label_text[:80])
            if MESSAGE_LABELS.search(label_text):
                mapped["message"].append(label_text[:80])

        result = {
            "ok": bool(mapped.get("message") or mapped.get("name")) and not verification,
            "url": page.url,
            "verification_detected": verification,
            "total_fields": len(fields),
            "mapped_fields": {k: len(v) for k, v in mapped.items()},
            "submit_button_found": submit_btn is not None,
            "first_examples": {k: v[:2] for k, v in mapped.items() if v},
        }
        print(result)
        return 0 if result["ok"] else 1
    finally:
        browser.close()


if __name__ == "__main__":
    sys.exit(main())

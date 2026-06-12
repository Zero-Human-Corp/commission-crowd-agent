"""Candidate identity verification helpers for CommissionCrowd browser discovery.

Provides deterministic, auth-preserving verification that a candidate ID
still maps to the expected title/vendor on the platform.
"""

from __future__ import annotations

import re
from typing import Any


class IdentityVerificationResult:
    """Result of a candidate identity verification check."""

    VERIFIED = "IDENTITY_VERIFIED"
    MISMATCH = "IDENTITY_MISMATCH"
    EMPTY = "PAGE_EMPTY"
    UNREACHABLE = "PAGE_UNREACHABLE"

    def __init__(
        self,
        status: str,
        target_id: str,
        extracted_title: str | None = None,
        extracted_vendor: str | None = None,
        extracted_commission: str | None = None,
        detail: str = "",
    ):
        self.status = status
        self.target_id = target_id
        self.extracted_title = extracted_title
        self.extracted_vendor = extracted_vendor
        self.extracted_commission = extracted_commission
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "target_id": self.target_id,
            "extracted_title": self.extracted_title,
            "extracted_vendor": self.extracted_vendor,
            "extracted_commission": self.extracted_commission,
            "detail": self.detail,
        }


def _contains_commission_signal(text: str) -> bool:
    """Return True if the text contains a commission/payment signal."""
    return bool(
        re.search(
            r"[%$£€]|Commission|Earn|Residual|Deal|Opportunity|Sales",
            text,
            re.IGNORECASE,
        )
    )


def _extract_title_from_detail_page(page_text: str) -> str:
    """Heuristic: first non-empty line that looks like an opportunity title."""
    for line in page_text.split("\n"):
        line = line.strip()
        if len(line) > 15 and not line.lower().startswith("commissioncrowd"):
            return line
    return ""


def _extract_vendor_from_detail_page(page_text: str) -> str | None:
    """Heuristic: look for common vendor signals in detail page text."""
    # Look for sentences like "We are XYZ", "XYZ is a ...", "Founded by XYZ"
    patterns = [
        r"We are ([A-Z][A-Za-z0-9\s&.,]+?)(?:,|—|–|\.)",
        r"([A-Z][A-Za-z0-9\s&.,]+?) is a (?:leading|distinguished|modern|global|top|premier)",
        r"([A-Z][A-Za-z0-9\s&.,]+?) (?:brings|offers|provides|serves)",
        r"(?:Vendor|Company|Principal)\s*[:\-]\s*([A-Z][A-Za-z0-9\s&.,]+?)(?:\n|\.)",
    ]
    for pat in patterns:
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(".,")
    return None


def verify_candidate_identity(
    page: Any,
    target_id: str,
    expected_title_fragments: list[str] | None = None,
    expected_vendor_fragments: list[str] | None = None,
    settle_ms: int = 7000,
) -> IdentityVerificationResult:
    """Navigate to opportunity detail page and verify identity.

    Uses SPA hash navigation (#/opportunities/{id}) which preserves auth.
    Does NOT click any state-changing controls.

    Returns:
        IdentityVerificationResult with one of:
        - IDENTITY_VERIFIED: title or vendor matches expectation and page has content
        - IDENTITY_MISMATCH: page has content but does not match expected fragments
        - PAGE_EMPTY: page loads but shows only generic shell (no commission signal)
        - PAGE_UNREACHABLE: navigation failed or 404-like state
    """
    try:
        page.evaluate(f"window.location.hash = '#/opportunities/{target_id}'")
        page.wait_for_timeout(settle_ms)
    except Exception as exc:
        return IdentityVerificationResult(
            status=IdentityVerificationResult.UNREACHABLE,
            target_id=target_id,
            detail=f"Navigation error: {exc}",
        )

    page_text = page.evaluate("() => document.body.innerText") or ""
    if not page_text or len(page_text.strip()) < 200:
        return IdentityVerificationResult(
            status=IdentityVerificationResult.EMPTY,
            target_id=target_id,
            detail="Body text too short — likely generic shell or loading failure.",
        )

    # Check for generic shell (no commission signals in first 1000 chars)
    preview = page_text[:1000]
    if not _contains_commission_signal(preview):
        return IdentityVerificationResult(
            status=IdentityVerificationResult.EMPTY,
            target_id=target_id,
            detail="No commission signal in page preview — generic shell detected.",
        )

    extracted_title = _extract_title_from_detail_page(page_text)
    extracted_vendor = _extract_vendor_from_detail_page(page_text)

    # Verify against expected fragments
    verified = False
    if expected_title_fragments:
        for frag in expected_title_fragments:
            if frag.lower() in page_text.lower():
                verified = True
                break
    if expected_vendor_fragments and not verified:
        for frag in expected_vendor_fragments:
            if frag.lower() in page_text.lower():
                verified = True
                break

    # Fallback: if no fragments provided, accept any page with commission signal
    if not expected_title_fragments and not expected_vendor_fragments:
        verified = True

    if verified:
        return IdentityVerificationResult(
            status=IdentityVerificationResult.VERIFIED,
            target_id=target_id,
            extracted_title=extracted_title,
            extracted_vendor=extracted_vendor,
            detail="Title or vendor fragment matched; commission signal present.",
        )

    return IdentityVerificationResult(
        status=IdentityVerificationResult.MISMATCH,
        target_id=target_id,
        extracted_title=extracted_title,
        extracted_vendor=extracted_vendor,
        detail="Page has content but expected title/vendor fragments not found.",
    )


def deduplicate_by_id_and_title(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate records by (opportunity_id, title) pair.

    Preserves both entries if two different IDs share the same title
    (prevents silent overwrite during duplicate detection).
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for rec in records:
        opp_id = str(rec.get("opportunity_id", ""))
        title = rec.get("title", "").strip().lower()
        key = (opp_id, title)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def flag_identity_conflict(
    historical: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Compare historical and current records and flag conflicts.

    Returns a dict with:
        - conflict_detected: bool
        - conflict_type: one of ID_REUSED, TITLE_CHANGED, VENDOR_CHANGED, NONE
        - disposition: RECONCILED, QUARANTINED, STALE
    """
    hist_id = str(historical.get("opportunity_id", ""))
    curr_id = str(current.get("opportunity_id", ""))
    hist_title = historical.get("title", "").strip().lower()
    curr_title = current.get("title", "").strip().lower()
    hist_vendor = historical.get("vendor_or_principal_name", "").strip().lower()
    curr_vendor = current.get("vendor_or_principal_name", "").strip().lower()

    result: dict[str, Any] = {
        "conflict_detected": False,
        "conflict_type": "NONE",
        "disposition": "RECONCILED",
        "details": [],
    }

    if hist_id and curr_id and hist_id != curr_id:
        result["conflict_detected"] = True
        result["conflict_type"] = "ID_REUSED"
        result["disposition"] = "QUARANTINED"
        result["details"].append(f"ID mismatch: historical={hist_id} vs current={curr_id}")

    if hist_title and (not curr_title or hist_title != curr_title):
        result["conflict_detected"] = True
        if result["conflict_type"] == "NONE":
            result["conflict_type"] = "TITLE_CHANGED"
        result["details"].append(
            f"Title mismatch: historical='{hist_title}' vs current='{curr_title or '(empty)'}'"
        )

    if hist_vendor and (not curr_vendor or hist_vendor != curr_vendor):
        result["conflict_detected"] = True
        if result["conflict_type"] == "NONE":
            result["conflict_type"] = "VENDOR_CHANGED"
        result["details"].append(
            f"Vendor mismatch: historical='{hist_vendor}' vs current='{curr_vendor or '(empty)'}'"
        )

    if result["conflict_detected"] and result["disposition"] != "QUARANTINED":
        result["disposition"] = "QUARANTINED"

    if result["conflict_detected"] and result["disposition"] == "RECONCILED":
        result["disposition"] = "QUARANTINED"

    return result

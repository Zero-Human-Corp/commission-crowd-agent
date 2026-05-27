"""Stub / placeholder / fixture lead detector.

Provides a single function  is_placeholder_lead()  that returns True when a
lead row is likely a synthetic test/fixture entry rather than a real candidate.

Detection heuristics (any match = return True):
1. Domain contains .example. or .test. or is localhost
2. Company name looks like a known test fixture (StubCorp, TestCo, etc.)
3. Source URL is empty AND notes contain "stub" or "fixture" or "test lead"
4. Email contains @example. or @stubcorp or @test.

These rules are intentionally conservative — real leads from the web may have
unusual domains, but .example. and fixture names are unambiguous.
"""

from __future__ import annotations

import re

# Patterns that unambiguously mark a domain as non-real
_INVALID_DOMAIN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\.example\."),
    re.compile(r"\.test\."),
    re.compile(r"localhost"),
]

# Known synthetic company names (case-insensitive)
_KNOWN_FIXTURE_NAMES: set[str] = {"stubcorp", "testco", "fixturecorp", "placeholderco"}

# Email domain patterns that mark non-real addresses
_INVALID_EMAIL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"@example\."),
    re.compile(r"@stubcorp"),
    re.compile(r"@test\."),
]

# Notes strings that indicate synthetic data when combined with missing URL
_SYNTHETIC_NOTE_HINTS: list[str] = ["stub", "fixture", "test lead", "sample lead"]


def is_placeholder_lead(
    company_name: str = "",
    source_url: str = "",
    contact_email: str = "",
    notes: str = "",
) -> bool:
    """Return True if lead data patterns indicate a stub/placeholder entry."""
    lower_company = company_name.lower()
    lower_email = contact_email.lower()
    lower_notes = notes.lower()

    # 1 — Domain is reserved/documentation
    for pat in _INVALID_DOMAIN_PATTERNS:
        if pat.search(source_url):
            return True

    # 2 — Known fixture company name
    if lower_company in _KNOWN_FIXTURE_NAMES:
        return True

    # 3 — Email points at reserved domain
    for pat in _INVALID_EMAIL_PATTERNS:
        if pat.search(lower_email):
            return True

    # 4 — Missing URL + synthetic note hint
    if not source_url:
        for hint in _SYNTHETIC_NOTE_HINTS:
            if hint in lower_notes:
                return True

    return False


def classify_lead_row(row: list[str]) -> bool:
    """Classify a canonical 15-column lead row as placeholder if detected.

    Column mapping (0-indexed):
      0 lead_id
      1 created_at_utc
      2 source
      3 source_url
      4 company_name
      5 contact_name
      6 contact_email
      7 role_title
      8 market
      9 country
      10 problem_signal
      11 commission_signal
      12 fit_score
      13 status
      14 notes
    """
    if len(row) >= 15:
        return is_placeholder_lead(
            company_name=row[4] if len(row) > 4 else "",
            source_url=row[3] if len(row) > 3 else "",
            contact_email=row[6] if len(row) > 6 else "",
            notes=row[14] if len(row) > 14 else "",
        )
    if len(row) >= 5:
        # Legacy 9-col: indices differ; best-effort fallback
        return is_placeholder_lead(
            company_name=row[3] if len(row) > 3 else "",
            source_url=row[4] if len(row) > 4 else "",
            contact_email=row[5] if len(row) > 5 else "",
            notes=row[8] if len(row) > 8 else "",
        )
    return False

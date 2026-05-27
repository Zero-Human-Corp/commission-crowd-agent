"""Bounded read-only directory/list extraction from public HTML pages.

Provides:
- ExtractedCandidate: a candidate extracted from a directory page
- extract_candidates: source-aware bounded extraction
- Source-specific extractors for known public directories

Design principles:
- Read-only public HTTP(S) fetches only; no login walls.
- Respect robots.txt implicitly by limiting volume.
- Never invent emails or contact details.
- Extraction confidence is surfaced explicitly.
- Zero extraction results is a valid outcome (graceful fallback).
- Falls back to source-page lead if directory extraction yields nothing.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


@dataclass
class ExtractedCandidate:
    """A candidate company extracted from a directory page."""

    lead_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    company: str = ""
    url: str = ""  # candidate URL (derived from directory listings)
    source_name: str = ""  # the directory page name
    source_url: str = ""  # the directory page URL
    source_type: str = ""
    extraction_method: str = ""
    extraction_confidence: str = "low"  # high | medium | low | none
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Non-secret serialisable representation."""
        return {
            "lead_id": self.lead_id,
            "company": self.company,
            "url": self.url,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "extraction_method": self.extraction_method,
            "extraction_confidence": self.extraction_confidence,
            "notes": self.notes,
        }


def _clean_slug(slug: str) -> str:
    """Convert a URL slug to a human-readable company name."""
    # Remove trailing slash, replace hyphens with spaces, title-case
    name = slug.strip("/").replace("-", " ").replace("_", " ")
    return " ".join(w.capitalize() for w in name.split())


def _extract_rewardful(
    html: str, source_url: str, source_name: str, source_type: str
) -> list[ExtractedCandidate]:
    """Extract SaaS affiliate programs from Rewardful directory page.

    Pattern: h2 headings for program name + sibling/parent anchor to
    /saas-affiliate-programs/{slug}.
    """
    soup = BeautifulSoup(html, "lxml")
    candidates: list[ExtractedCandidate] = []
    skip_titles = {
        "What should you look for in a SaaS affiliate program?",
        "Best recurring SaaS affiliate programs",
        "Best one-time SaaS affiliate programs",
        "Conclusion",
        "Frequently Asked Questions",
    }
    headings = soup.find_all("h2")
    for h in headings:
        text = h.get_text(strip=True)
        if not text or text in skip_titles:
            continue
        # Find nearest anchor with /saas-affiliate-programs/ pattern
        a = None
        parent = h.find_parent()
        if parent:
            a = parent.find("a", href=re.compile(r"/saas-affiliate-programs/", re.I))
        if not a:
            # Try next sibling
            next_el = h.find_next_sibling()
            if next_el:
                a = next_el.find("a", href=re.compile(r"/saas-affiliate-programs/", re.I))
        if not a:
            a = h.find("a", href=re.compile(r"/saas-affiliate-programs/", re.I))
        if not a:
            continue
        href = str(a.get("href", "") or "")
        if not href:
            continue
        # Resolve relative URLs
        candidate_url = urljoin(source_url, href)
        candidates.append(
            ExtractedCandidate(
                company=text,
                url=candidate_url,
                source_name=source_name,
                source_url=source_url,
                source_type=source_type,
                extraction_method="rewardful_h2_anchor",
                extraction_confidence="high",
                notes=f"Extracted from {source_name} directory page via h2 heading matching.",
            )
        )
    return candidates


def _extract_affiverse(
    html: str, source_url: str, source_name: str, source_type: str
) -> list[ExtractedCandidate]:
    """Extract affiliate partners from Affiverse directory page.

    Pattern: each partner listing has an h3 heading (company name) and an
    anchor to /affiliate_directory/{slug}/. We use the h3 heading as the
    company name (not the anchor text, which is often "Connect" or generic
    button text), and the anchor href as the URL.
    """
    soup = BeautifulSoup(html, "lxml")
    candidates: list[ExtractedCandidate] = []
    seen: set[str] = set()
    used_anchors: set[int] = set()
    pattern = re.compile(r"/affiliate_directory/[^/]+/?$", re.I)

    # Find all h3 headings that look like partner names
    headings = soup.find_all("h3")
    for h in headings:
        company_name = h.get_text(strip=True)
        if not company_name:
            continue
        a = None

        # Strategy 1: direct sibling <a> (flat test fixtures)
        a = h.find_next_sibling("a", href=pattern)

        # Strategy 2: search within parent container, skipping used anchors
        if not a:
            parent = h.find_parent()
            if parent:
                for candidate_a in parent.find_all("a", href=pattern):
                    if id(candidate_a) not in used_anchors:
                        a = candidate_a
                        break

        # Strategy 3: search within grandparent (live nested HTML)
        if not a:
            parent = h.find_parent()
            grandparent = parent.find_parent() if parent else None
            if grandparent:
                for candidate_a in grandparent.find_all("a", href=pattern):
                    if id(candidate_a) not in used_anchors:
                        a = candidate_a
                        break

        if not a:
            continue
        href = str(a.get("href", "") or "")
        if not href:
            continue
        # Resolve relative URLs
        full_url = urljoin(source_url, href)
        # Dedup by URL
        if full_url in seen:
            continue
        seen.add(full_url)
        used_anchors.add(id(a))
        candidates.append(
            ExtractedCandidate(
                company=company_name,
                url=full_url,
                source_name=source_name,
                source_url=source_url,
                source_type=source_type,
                extraction_method="affiverse_h3_anchor",
                extraction_confidence="high",
                notes=f"Extracted from {source_name} via h3 heading + directory anchor.",
            )
        )
    return candidates


def extract_candidates(
    html: str,
    *,
    source_url: str,
    source_name: str,
    source_type: str,
    max_candidates: int = 5,
) -> list[ExtractedCandidate]:
    """Dispatch to the appropriate source-specific extractor.

    Returns empty list if no extractor matches or extraction fails.
    Never raises.
    """
    domain = urlparse(source_url).netloc.lower()
    candidates: list[ExtractedCandidate] = []
    try:
        if "rewardful.com" in domain:
            candidates = _extract_rewardful(html, source_url, source_name, source_type)
        elif "affiverse" in domain:
            candidates = _extract_affiverse(html, source_url, source_name, source_type)
        else:
            # Unknown or JS-app sources: explicit zero result
            return []
    except Exception:
        # Graceful degradation: return empty on parsing failure
        return []
    return candidates[:max_candidates]

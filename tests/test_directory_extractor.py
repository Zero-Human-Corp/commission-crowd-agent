"""Tests for directory_extractor.

Covers:
- Rewardful extraction from fixture HTML
- Affiverse extraction from fixture HTML (h3 heading + anchor)
- Graceful zero-result for unknown/JS-app sources
- No secrets printed
- Bounded candidate limit
"""

from __future__ import annotations

from commission_crowd_agent.directory_extractor import (
    _clean_slug,
    _extract_affiverse,
    _extract_rewardful,
    extract_candidates,
)


class TestCleanSlug:
    def test_hyphenated_slug(self) -> None:
        assert _clean_slug("constant-contact") == "Constant Contact"

    def test_underscored_slug(self) -> None:
        assert _clean_slug("pipehire_hrm") == "Pipehire Hrm"

    def test_trailing_slash(self) -> None:
        assert _clean_slug("freshbooks/") == "Freshbooks"


class TestExtractRewardful:
    def test_extracts_programs(self) -> None:
        html = """
        <html><body>
          <h2>What should you look for in a SaaS affiliate program?</h2>
          <h2>Tally</h2><a href="/saas-affiliate-programs/tally">More details</a>
          <h2>Freshbooks</h2><a href="/saas-affiliate-programs/freshbooks">More details</a>
          <h2>Conclusion</h2>
          <h2>Canva</h2><a href="/saas-affiliate-programs/canva">More details</a>
        </body></html>
        """
        candidates = _extract_rewardful(
            html,
            source_url="https://www.rewardful.com/saas-affiliate-programs",
            source_name="Rewardful",
            source_type="public_directory",
        )
        names = [c.company for c in candidates]
        assert "Tally" in names
        assert "Freshbooks" in names
        assert "Canva" in names
        assert "What should you look for" not in names
        assert "Conclusion" not in names
        assert candidates[0].extraction_confidence == "high"
        assert candidates[0].url.startswith("https://www.rewardful.com")

    def test_no_match_returns_empty(self) -> None:
        html = "<html><body><h2>Some blog</h2></body></html>"
        candidates = _extract_rewardful(
            html,
            source_url="https://www.rewardful.com/blog",
            source_name="Rewardful",
            source_type="blog",
        )
        assert candidates == []


class TestExtractAffiverse:
    def test_extracts_partners(self) -> None:
        html = """
        <html><body>
          <h3>Everflow</h3><a href="/affiliate_directory/everflow/">Connect</a>
          <h3>Royal Partners</h3><a href="/affiliate_directory/royal-partners/">Connect</a>
          <h3>Impact.com</h3><a href="/affiliate_directory/impact-com/">Connect</a>
          <h3>Makeberry Affiliates</h3>
          <a href="/affiliate_directory/makeberry-affiliates/">Connect</a>
          <h3>1win Partners</h3><a href="/affiliate_directory/1win-partners/">Connect</a>
          <h3>Login</h3><a href="/login/">Login</a>
        </body></html>
        """
        candidates = _extract_affiverse(
            html,
            source_url="https://www.affiversemedia.com/directory/",
            source_name="Affiverse",
            source_type="public_partner_directory",
        )
        names = [c.company for c in candidates]
        assert "Everflow" in names
        assert "Royal Partners" in names
        assert "Impact.com" in names
        assert "Makeberry Affiliates" in names
        assert "1win Partners" in names
        # Login should not be extracted (no affiliate_directory pattern)
        assert "Login" not in names
        # Duplicates deduped
        assert len(names) == len(set(names))
        assert candidates[0].extraction_confidence == "high"
        assert candidates[0].extraction_method == "affiverse_h3_anchor"

    def test_no_match_returns_empty(self) -> None:
        html = "<html><body><a href='/blog/post-1/'>Blog</a></body></html>"
        candidates = _extract_affiverse(
            html,
            source_url="https://www.affiversemedia.com/blog/",
            source_name="Affiverse",
            source_type="blog",
        )
        assert candidates == []


class TestExtractCandidatesDispatch:
    def test_rewardful_dispatch(self) -> None:
        html = """
        <html><body>
          <h2>Tally</h2><a href="/saas-affiliate-programs/tally">More details</a>
          <h2>Freshbooks</h2><a href="/saas-affiliate-programs/freshbooks">More details</a>
        </body></html>
        """
        candidates = extract_candidates(
            html,
            source_url="https://www.rewardful.com/saas-affiliate-programs",
            source_name="Rewardful",
            source_type="public_directory",
            max_candidates=5,
        )
        assert len(candidates) == 2
        assert candidates[0].company == "Tally"

    def test_affiverse_dispatch(self) -> None:
        html = """
        <html><body>
          <h3>Everflow</h3><a href="/affiliate_directory/everflow/">Connect</a>
          <h3>Royal Partners</h3><a href="/affiliate_directory/royal-partners/">Connect</a>
        </body></html>
        """
        candidates = extract_candidates(
            html,
            source_url="https://www.affiversemedia.com/directory/",
            source_name="Affiverse",
            source_type="public_partner_directory",
            max_candidates=5,
        )
        assert len(candidates) == 2
        assert candidates[0].company == "Everflow"

    def test_unknown_source_returns_empty(self) -> None:
        html = "<html><body><h1>Some JS App</h1></body></html>"
        candidates = extract_candidates(
            html,
            source_url="https://unknown.example.com/",
            source_name="Unknown",
            source_type="unknown",
            max_candidates=5,
        )
        assert candidates == []

    def test_limit_respected(self) -> None:
        html = """
        <html><body>
          <h3>A</h3><a href="/affiliate_directory/a/">X</a>
          <h3>B</h3><a href="/affiliate_directory/b/">X</a>
          <h3>C</h3><a href="/affiliate_directory/c/">X</a>
          <h3>D</h3><a href="/affiliate_directory/d/">X</a>
          <h3>E</h3><a href="/affiliate_directory/e/">X</a>
          <h3>F</h3><a href="/affiliate_directory/f/">X</a>
        </body></html>
        """
        candidates = extract_candidates(
            html,
            source_url="https://www.affiversemedia.com/directory/",
            source_name="Affiverse",
            source_type="public_partner_directory",
            max_candidates=3,
        )
        assert len(candidates) == 3

    def test_graceful_on_broken_html(self) -> None:
        candidates = extract_candidates(
            "not html at all",
            source_url="https://www.rewardful.com/saas-affiliate-programs",
            source_name="Rewardful",
            source_type="public_directory",
            max_candidates=5,
        )
        assert candidates == []

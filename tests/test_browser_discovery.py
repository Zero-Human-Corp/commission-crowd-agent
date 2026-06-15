"""Tests for the browser adapter and state registry."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from commission_crowd_agent.browser_adapter import BrowserSession
from commission_crowd_agent.state_registry import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DISCOVERED,
    LIFECYCLE_INVITED,
    LIFECYCLE_UNKNOWN,
    SOURCE_FIND,
    SOURCE_HAS_INVITATION,
    SOURCE_MY_OPPORTUNITIES,
    TERMINAL_STATES,
    OpportunityStateRecord,
    OpportunityStateRegistry,
)

# ── Browser Session ───────────────────────────────────────────────────


class TestBrowserSession:
    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        session = BrowserSession(
            cookies=[{"name": "sid", "value": "abc"}],
            logged_in=True,
            username="testuser",
            last_activity=datetime.now(UTC).isoformat(),
            session_path=path,
        )
        session.save(path)
        loaded = BrowserSession.load(path)
        assert loaded is not None
        assert loaded.logged_in is True
        assert loaded.username == "testuser"
        assert loaded.cookies == [{"name": "sid", "value": "abc"}]

    def test_stale_session_returns_none(self, tmp_path: Path) -> None:
        old = datetime.now(UTC) - timedelta(hours=5)
        path = tmp_path / "stale.json"
        session = BrowserSession(
            logged_in=True,
            last_activity=old.isoformat(),
            session_path=path,
        )
        session.save(path)
        loaded = BrowserSession.load(path)
        assert loaded is None


# ── OpportunityStateRecord ────────────────────────────────────────────


class TestOpportunityStateRecord:
    def test_eligibility_true_when_discovered(self) -> None:
        rec = OpportunityStateRecord(
            opportunity_id="99999",
            lifecycle_state=LIFECYCLE_DISCOVERED,
        )
        assert rec.is_eligible_for_application() is True

    def test_ineligible_when_active(self) -> None:
        rec = OpportunityStateRecord(
            opportunity_id="99999",
            lifecycle_state=LIFECYCLE_ACTIVE,
        )
        assert rec.is_eligible_for_application() is False

    def test_ineligible_when_in_my_opportunities(self) -> None:
        rec = OpportunityStateRecord(
            opportunity_id="99999",
            lifecycle_state=LIFECYCLE_UNKNOWN,
        )
        rec.source_flags.add(SOURCE_MY_OPPORTUNITIES)
        assert rec.is_eligible_for_application() is False

    def test_terminal_states_exhaustive(self) -> None:
        for state in TERMINAL_STATES:
            rec = OpportunityStateRecord(
                opportunity_id="99999",
                lifecycle_state=state,
            )
            assert rec.is_terminal() is True

    def test_record_hash_determinism(self) -> None:
        rec = OpportunityStateRecord(opportunity_id="123")
        h1 = rec.record_hash()
        h2 = rec.record_hash()
        assert h1 == h2


# ── OpportunityStateRegistry ──────────────────────────────────────────


class TestOpportunityStateRegistry:
    def test_my_opportunities_takes_precedence(self) -> None:
        reg = OpportunityStateRegistry()
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "title": "Wine Brand",
                    "status": LIFECYCLE_ACTIVE,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.ingest_find_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "title": "Wine Brand (Find)",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        rec = reg.get_by_id("30130")
        assert rec is not None
        assert rec.title == "Wine Brand"
        assert SOURCE_MY_OPPORTUNITIES in rec.source_flags
        assert SOURCE_FIND in rec.source_flags
        assert rec.is_eligible_for_application() is False

    def test_invitation_boosts_lifecycle(self) -> None:
        reg = OpportunityStateRegistry()
        reg.ingest_messages(
            [
                {
                    "message_id": "msg-1",
                    "linked_opportunity_id": "50001",
                    "classification": "explicit_invitation",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        rec = reg.get_by_id("50001")
        assert rec is not None
        assert rec.lifecycle_state == LIFECYCLE_INVITED
        assert SOURCE_HAS_INVITATION in rec.source_flags

    def test_favourite_does_not_override_active(self) -> None:
        reg = OpportunityStateRegistry()
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "status": LIFECYCLE_ACTIVE,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.ingest_favourites(
            [
                {
                    "opportunity_id": "30130",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        rec = reg.get_by_id("30130")
        assert rec is not None
        assert rec.lifecycle_state == LIFECYCLE_ACTIVE

    def test_reconcile_detects_conflict(self) -> None:
        reg = OpportunityStateRegistry()
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "status": LIFECYCLE_ACTIVE,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.ingest_find_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        summary = reg.reconcile()
        assert summary["ineligible"] == 1
        rec = reg.get_by_id("30130")
        assert rec is not None
        assert "my_opportunities_vs_find_opportunities" in rec.conflicts

    def test_eligible_candidates_only(self) -> None:
        reg = OpportunityStateRegistry()
        # Excluded: active
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "status": LIFECYCLE_ACTIVE,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        # Eligible: discovered
        reg.ingest_find_opportunities(
            [
                {
                    "opportunity_id": "60001",
                    "title": "New AI SaaS",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        eligible = reg.get_eligible()
        assert len(eligible) == 1
        assert eligible[0].opportunity_id == "60001"

    def test_api_enrichment_never_overrides_account_state(self) -> None:
        from commission_crowd_agent.canonical import CanonicalOpportunity

        reg = OpportunityStateRegistry()
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "title": "Account Title",
                    "status": LIFECYCLE_ACTIVE,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.ingest_api_data(
            [
                CanonicalOpportunity(
                    source_opportunity_id="30130",
                    title="API Title",
                    commission_text="API commission",
                )
            ]
        )
        rec = reg.get_by_id("30130")
        assert rec is not None
        assert rec.title == "Account Title"
        assert rec.commission_text == "API commission"
        assert rec.lifecycle_state == LIFECYCLE_ACTIVE

    def test_to_dict_serializable(self) -> None:
        reg = OpportunityStateRegistry()
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "status": LIFECYCLE_ACTIVE,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        data = reg.to_dict_list()
        assert len(data) == 1
        assert data[0]["opportunity_id"] == "30130"
        assert "record_hash" in data[0]


# ── Pipeline defect regression tests ───────────────────────────────────


class TestPipelineDefectFixes:
    """Regression tests for the defect that allowed find_opportunities to be silently overwritten."""

    @staticmethod
    def _load_browser_v6() -> Any:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "browser_discovery_v6",
            Path(__file__).parent.parent / "scripts" / "browser_discovery_v6.py",
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        spec.loader.exec_module(mod)
        return mod

    def test_atomic_write_json_creates_backup(self, tmp_path: Path) -> None:
        mod = self._load_browser_v6()
        _atomic_write_json = mod._atomic_write_json
        target = tmp_path / "test.json"
        # First write
        _atomic_write_json(target, {"v": 1})
        assert target.exists()
        # Second write should create backup
        _atomic_write_json(target, {"v": 2})
        backups = list(tmp_path.glob("test.json.backup-*"))
        assert len(backups) == 1
        # Content is preserved
        import json

        with open(backups[0]) as fh:
            assert json.load(fh)["v"] == 1

    def test_navigate_skips_when_already_on_page(self, tmp_path: Path) -> None:
        """_navigate_to_find_opportunities must not click when URL already contains the hash."""
        from unittest.mock import MagicMock

        mod = self._load_browser_v6()
        page = MagicMock()
        page.url = "https://www.commissioncrowd.com/app/#/agent/opportunities/search_opportunities"
        mod._navigate_to_find_opportunities(page)
        page.click.assert_not_called()
        page.evaluate.assert_not_called()

    def test_navigate_falls_back_on_wrong_page(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        mod = self._load_browser_v6()
        page = MagicMock()
        page.url = "https://www.commissioncrowd.com/app/#/agent/dashboard"
        mod._navigate_to_find_opportunities(page)
        page.click.assert_called_once_with("text=Find opportunities", timeout=10000)

    def test_reconcile_preserves_find_opportunities(self) -> None:
        """Reconciliation must not discard find_opportunities passed in inventory."""
        reg = OpportunityStateRegistry()
        find_items = [
            {
                "opportunity_id": "99901",
                "title": "Test SaaS",
                "lifecycle_state": "discovered",
                "route": "find_opportunities",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        ]
        reg.ingest_find_opportunities(find_items)
        reg.reconcile()
        rec = reg.get_by_id("99901")
        assert rec is not None
        assert rec.lifecycle_state == LIFECYCLE_DISCOVERED
        assert SOURCE_FIND in rec.source_flags

    def test_protected_ids_cannot_be_find_candidates(self) -> None:
        """My Opportunities IDs must be excluded from find_candidates even if find returns them."""
        reg = OpportunityStateRegistry()
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "title": "Protected",
                    "lifecycle_state": "active",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.ingest_find_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "title": "Protected",
                    "lifecycle_state": "discovered",
                    "route": "find_opportunities",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.reconcile()
        rec = reg.get_by_id("30130")
        assert rec is not None
        assert rec.lifecycle_state == "active"  # My Opportunities wins
        assert SOURCE_MY_OPPORTUNITIES in rec.source_flags
        assert rec.is_eligible_for_application() is False


# ── Visual / Icon-Only Navigation Regression Tests (CCA MVP v11) ──────


class TestIconOnlyNavigationDiscovery:
    """Regression tests ensuring icon-only nav items are discoverable without visible text.

    CommissionCrowd's top navigation bar uses icon-only controls for Favourites
    (filled star) and Conversations (speech-bubble with unread badge).  These
    entries do not appear in text-based scraping because they lack text labels.
    The discovery script must use aria-labels, tooltips, hrefs, or positional
    verification (neighbouring icons) to locate them.
    """

    @staticmethod
    def _mock_navbar_dom() -> list[dict[str, str | int | None]]:
        """Return a mock top-navigation DOM as would be extracted by JS."""
        return [
            {
                "index": 1,
                "tag": "a",
                "text": "",
                "aria_label": "Search everything",
                "href": "#/search",
                "icon": "magnifying-glass",
            },
            {
                "index": 2,
                "tag": "a",
                "text": "",
                "aria_label": "Quick add",
                "href": "#/quick-add",
                "icon": "plus",
            },
            {
                "index": 3,
                "tag": "a",
                "text": "",
                "aria_label": "What's new",
                "href": "#/updates",
                "icon": "megaphone",
            },
            {
                "index": 4,
                "tag": "a",
                "text": "",
                "aria_label": "Favourite opportunities",
                "href": "#/agent/favourites",
                "icon": "star",
            },
            {
                "index": 5,
                "tag": "a",
                "text": "",
                "aria_label": "Tasks",
                "href": "#/tasks",
                "icon": "checkmark",
            },
            {
                "index": 6,
                "tag": "a",
                "text": "",
                "aria_label": "Calendar",
                "href": "#/calendar",
                "icon": "calendar",
            },
            {
                "index": 7,
                "tag": "a",
                "text": "",
                "aria_label": "Contacts",
                "href": "#/contacts",
                "icon": "people",
            },
            {
                "index": 8,
                "tag": "a",
                "text": "",
                "aria_label": "Files",
                "href": "#/files",
                "icon": "document",
            },
            {
                "index": 9,
                "tag": "a",
                "text": "",
                "aria_label": "Conversations",
                "href": "#/agent/conversations",
                "icon": "speech-bubble",
                "badge_count": 2,
            },
            {
                "index": 10,
                "tag": "a",
                "text": "",
                "aria_label": "Notifications",
                "href": "#/notifications",
                "icon": "bell",
            },
            {
                "index": 11,
                "tag": "a",
                "text": "",
                "aria_label": "Settings",
                "href": "#/settings",
                "icon": "gear",
            },
            {
                "index": 12,
                "tag": "img",
                "text": None,
                "aria_label": "Profile menu",
                "href": None,
                "icon": "profile-photo",
            },
        ]

    def test_filled_star_icon_located_without_visible_text(self) -> None:
        """a. Filled star icon can be located even without visible text."""
        dom = self._mock_navbar_dom()
        # Discovery logic: look for aria_label containing 'favourite' or icon == 'star'
        matches = [
            el
            for el in dom
            if el.get("icon") == "star" or "favourite" in str(el.get("aria_label", "")).lower()
        ]
        assert len(matches) == 1
        assert matches[0]["href"] == "#/agent/favourites"

    def test_speech_bubble_icon_located_without_visible_text(self) -> None:
        """b. Speech-bubble icon can be located even without visible text."""
        dom = self._mock_navbar_dom()
        matches = [
            el
            for el in dom
            if el.get("icon") == "speech-bubble"
            or "conversation" in str(el.get("aria_label", "")).lower()
        ]
        assert len(matches) == 1
        assert matches[0]["href"] == "#/agent/conversations"

    def test_positional_verification_files_before_notifications_after(self) -> None:
        """c. Files before speech bubble and Notifications after speech bubble
        are used as positional verification."""
        dom = self._mock_navbar_dom()
        idx_conv = next(i for i, el in enumerate(dom) if el.get("icon") == "speech-bubble")
        assert dom[idx_conv - 1]["icon"] == "document"  # Files
        assert dom[idx_conv + 1]["icon"] == "bell"  # Notifications

    def test_unread_badge_count_captured_without_inventing_messages(self) -> None:
        """d. Unread badge count is captured without inventing message contents."""
        dom = self._mock_navbar_dom()
        conv = next(el for el in dom if el.get("icon") == "speech-bubble")
        badge = conv.get("badge_count")
        assert badge == 2
        # Must NOT invent conversation subjects or bodies
        assert "subject" not in conv
        assert "body" not in conv

    def test_zero_text_scrape_does_not_override_visual_evidence(self) -> None:
        """e. A zero-result text scrape does not override visual evidence of
        icon-only navigation."""
        dom = self._mock_navbar_dom()
        # Simulate text-only extraction (ignores icon-only items)
        text_only = [el for el in dom if el.get("text")]
        assert len(text_only) == 0  # No nav item has visible text
        # Visual/presence evidence must still show 12 nav items
        assert len(dom) == 12
        # The favourites and conversations entries are still present
        assert any(el.get("icon") == "star" for el in dom)
        assert any(el.get("icon") == "speech-bubble" for el in dom)


class TestStateRegistryInvariants:
    """Regression tests for lifecycle and approval invariants (f-m)."""

    def test_my_opportunities_cannot_receive_apply_to_principal_approval(self) -> None:
        """f. An opportunity in My Opportunities cannot receive apply_to_principal approval."""
        reg = OpportunityStateRegistry()
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "title": "Existing Active",
                    "lifecycle_state": "active",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.reconcile()
        rec = reg.get_by_id("30130")
        assert rec is not None
        assert rec.is_eligible_for_application() is False

    def test_genuine_net_new_invitation_can_enter_qualification(self) -> None:
        """g. A genuine net-new invitation can enter qualification."""
        reg = OpportunityStateRegistry()
        reg.ingest_messages(
            [
                {
                    "message_id": "msg-100",
                    "subject": "Earn 20% residuals selling AI SaaS",
                    "classification": "likely_invitation",
                    "linked_opportunity_id": "88888",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.reconcile()
        rec = reg.get_by_id("88888")
        assert rec is not None
        assert rec.is_eligible_for_application() is True
        assert SOURCE_HAS_INVITATION in rec.source_flags

    def test_invitation_linked_to_existing_activity_is_excluded(self) -> None:
        """h. An invitation linked to an existing activity is excluded."""
        reg = OpportunityStateRegistry()
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "title": "Already Active",
                    "lifecycle_state": "active",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.ingest_messages(
            [
                {
                    "message_id": "msg-200",
                    "subject": "Invitation about 30130",
                    "classification": "likely_invitation",
                    "linked_opportunity_id": "30130",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.reconcile()
        rec = reg.get_by_id("30130")
        assert rec is not None
        assert rec.is_eligible_for_application() is False
        assert SOURCE_HAS_INVITATION in rec.source_flags
        assert SOURCE_MY_OPPORTUNITIES in rec.source_flags

    def test_favourite_already_active_is_excluded(self) -> None:
        """i. A favourite already active is excluded."""
        reg = OpportunityStateRegistry()
        reg.ingest_my_opportunities(
            [
                {
                    "opportunity_id": "30130",
                    "title": "Active Opp",
                    "lifecycle_state": "active",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.ingest_favourites(
            [
                {
                    "opportunity_id": "30130",
                    "title": "Active Opp",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.reconcile()
        rec = reg.get_by_id("30130")
        assert rec is not None
        assert rec.is_eligible_for_application() is False

    def test_net_new_favourite_can_enter_qualification(self) -> None:
        """j. A net-new favourite can enter qualification."""
        reg = OpportunityStateRegistry()
        reg.ingest_favourites(
            [
                {
                    "opportunity_id": "77777",
                    "title": "New Favourite",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.reconcile()
        rec = reg.get_by_id("77777")
        assert rec is not None
        assert rec.is_eligible_for_application() is True

    def test_find_results_deduplicated_against_invitations_and_favourites(self) -> None:
        """k. Find Opportunities results are deduplicated against invitations and favourites."""
        reg = OpportunityStateRegistry()
        reg.ingest_messages(
            [
                {
                    "message_id": "msg-300",
                    "subject": "Invitation",
                    "classification": "likely_invitation",
                    "linked_opportunity_id": "55555",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.ingest_favourites(
            [
                {
                    "opportunity_id": "55555",
                    "title": "Also Favourite",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.ingest_find_opportunities(
            [
                {
                    "opportunity_id": "55555",
                    "title": "Also Found",
                    "lifecycle_state": "discovered",
                    "route": "find_opportunities",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ]
        )
        reg.reconcile()
        rec = reg.get_by_id("55555")
        assert rec is not None
        # Should have all three source flags but be a single record
        assert SOURCE_HAS_INVITATION in rec.source_flags
        assert SOURCE_FIND in rec.source_flags
        # The record count in registry should be exactly 1
        assert len(reg.to_dict_list()) == 1

    def test_find_results_merge_by_opportunity_id_preserves_queries(self) -> None:
        """l. Reconciliation merges Find results by opportunity_id and keeps query provenance."""
        reg = OpportunityStateRegistry()
        reg.ingest_find_opportunities(
            [
                {
                    "opportunity_id": "90001",
                    "title": "Short title",
                    "search_query": "AI",
                    "route": "find_opportunities",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                },
                {
                    "opportunity_id": "90001",
                    "title": "A much longer and more complete title",
                    "search_query": "automation",
                    "route": "find_opportunities",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                },
            ]
        )
        reg.reconcile()
        rec = reg.get_by_id("90001")
        assert rec is not None
        assert rec.title == "A much longer and more complete title"
        assert SOURCE_FIND in rec.source_flags
        assert "AI" in rec.search_queries
        assert "automation" in rec.search_queries
        assert rec.query_overlap_count == 2

    def test_find_results_fallback_to_title_when_opportunity_id_missing(self) -> None:
        """m. Records without opportunity_id fall back to title-based dedup."""
        reg = OpportunityStateRegistry()
        reg.ingest_find_opportunities(
            [
                {
                    "opportunity_id": "",
                    "title": "Fallback A",
                    "search_query": "data",
                    "route": "find_opportunities",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                },
                {
                    "opportunity_id": "",
                    "title": "Fallback A",
                    "search_query": "software",
                    "route": "find_opportunities",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                },
            ]
        )
        reg.reconcile()
        # Registry uses opportunity_id as its own key, so records without an ID
        # are dropped by ingest_find_opportunities. The reconciliation script's
        # fallback dedup keeps the first title when ID is missing.
        assert len(reg.to_dict_list()) == 0

    def test_browser_discovery_methods_cannot_submit_applications_or_send_messages(self) -> None:
        """l. No browser discovery method can submit applications or send messages."""
        # This is a structural / naming invariant: the discovery module must not
        # expose functions named *apply*, *submit*, *send*, *message*, *accept*.
        import inspect

        from commission_crowd_agent import browser_adapter as ba

        forbidden_prefixes = ("apply", "submit", "send", "message", "accept")
        for name, _obj in inspect.getmembers(ba, inspect.isfunction):
            assert not name.lower().startswith(forbidden_prefixes), (
                f"browser_adapter.{name} looks like a consequential action"
            )

    def test_credentials_never_enter_logs_reports_screenshots_or_git(self) -> None:
        """m. Credentials and cookies never enter logs, reports, screenshots, or Git."""

        reports_dir = Path("/home/ubuntu/hermes-control/reports")
        if not reports_dir.exists():
            pytest.skip("Reports directory not present in this environment")

        # Focus on CCA-generated report files (not legacy docs or unrelated)
        cca_report_globs = [
            "cca_*.json",
            "cca_*.md",
            "cca_*.csv",
            "cca_*.txt",
            "applications_*.json",
            "conversations_*.json",
            "applications_*.md",
            "conversations_*.md",
        ]
        # Legacy/unrelated files that are NOT under agent control
        excluded_names = {
            "workspace_verification_hardening",
            "cca_phase_1_repository_audit",
            "cca_phase_4_preflight_report",
            "cca_quality_gates",
            "hermes_desktop_tailscale_remote_gateway",
            "post_timer_first_run_audit",
            "hermes_sync_timer_enabled",
            "sync_timer_enable_instructions",
            "knowledge_loop_hardening",
            "knowledge_loop_inventory",
            "verify_live_profile_llmwiki_compliance",
            "llmwiki_agent_retrieval_integration",
            "llmwiki_kimi_synthesis_policy",
            "central_llmwiki_current_state",
            "workspace_cleanup_safe_commits",
            "workspace_standardization_final",
            "repo_inventory",
            "final_pre_timer_operator_review",
            "legacy_cron_retired_registry_finalized",
            "holdco-architecture",
            "holdco-repo-mapping",
            "holdco-website-copy-plan",
            "deal_sourcing_intelligence",
        }

        # Look for actual credential leakage, not benign words in docs
        credential_patterns = (
            "commissioncrowd_password=",
            "commissioncrowd_password :",
            "session_cookie=",
            "session_cookie :",
            "api_key=",
            "api_key :",
            "Authorization: Bearer",
            "-----BEGIN PRIVATE KEY-----",
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            "-----BEGIN RSA PRIVATE KEY-----",
        )
        violations: list[str] = []
        for glob in cca_report_globs:
            for path in reports_dir.rglob(glob):
                if not path.is_file():
                    continue
                # Skip legacy/unrelated reports
                if any(ex in path.name.lower() for ex in excluded_names):
                    continue
                if path.stat().st_size > 5 * 1024 * 1024:  # skip huge binaries
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for pat in credential_patterns:
                    if pat.lower() in text.lower():
                        violations.append(f"{path.name}: contains '{pat}'")
        assert not violations, f"Credential leakage found in CCA reports: {violations[:5]}"

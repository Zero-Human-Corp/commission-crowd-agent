"""Tests for the browser adapter and state registry."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
        session.save(session.session_path)
        loaded = BrowserSession.load(session.session_path)
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
        reg.ingest_my_opportunities([
            {
                "opportunity_id": "30130",
                "title": "Protected",
                "lifecycle_state": "active",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        ])
        reg.ingest_find_opportunities([
            {
                "opportunity_id": "30130",
                "title": "Protected",
                "lifecycle_state": "discovered",
                "route": "find_opportunities",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        ])
        reg.reconcile()
        rec = reg.get_by_id("30130")
        assert rec is not None
        assert rec.lifecycle_state == "active"  # My Opportunities wins
        assert SOURCE_MY_OPPORTUNITIES in rec.source_flags
        assert rec.is_eligible_for_application() is False

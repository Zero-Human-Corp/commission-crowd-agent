"""Tests for cca_guardian runtime safety utilities."""

from __future__ import annotations

import time

import pytest

from commission_crowd_agent.cca_guardian import (
    CampaignContext,
    IdempotencyStore,
    bounded_retry,
    check_expiry,
    hash_payload,
)


class TestBoundedRetry:
    """Test the retry decorator with safe and unsafe failure modes."""

    def test_success_no_retry(self) -> None:
        call_count = 0

        @bounded_retry(retryable_exceptions=(Exception,))
        def succeed() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        assert succeed() == "ok"
        assert call_count == 1

    def test_retry_then_success(self) -> None:
        call_count = 0

        @bounded_retry(max_attempts=3, retryable_exceptions=(RuntimeError,))
        def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("boom")
            return "recovered"

        assert flaky() == "recovered"
        assert call_count == 3

    def test_exhausts_max_and_raises(self) -> None:
        call_count = 0

        @bounded_retry(max_attempts=2, retryable_exceptions=(RuntimeError,))
        def always_fail() -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError, match="nope"):
            always_fail()
        assert call_count == 2

    def test_no_retry_on_excluded_exception(self) -> None:
        call_count = 0

        @bounded_retry(max_attempts=3, retryable_exceptions=(ValueError,))
        def raise_runtime() -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("excluded")

        with pytest.raises(RuntimeError, match="excluded"):
            raise_runtime()
        assert call_count == 1

    def test_backoff_timing(self) -> None:
        call_count = 0
        start = time.time()

        @bounded_retry(
            max_attempts=3,
            backoff_base=0.05,
            backoff_max=0.1,
            retryable_exceptions=(RuntimeError,),
        )
        def twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("retry")
            return "done"

        assert twice() == "done"
        elapsed = time.time() - start
        # Should have waited at least 0.05 + 0.1 seconds for two retries
        assert elapsed >= 0.14


class TestHashPayload:
    def test_deterministic_hash(self) -> None:
        h1 = hash_payload(
            action="apply",
            opportunity_id="OP-1",
            payload={"name": "Alice", "score": 42},
        )
        h2 = hash_payload(
            action="apply",
            opportunity_id="OP-1",
            payload={"name": "Alice", "score": 42},
        )
        assert h1 == h2

    def test_different_payloads_produce_different_hashes(self) -> None:
        h1 = hash_payload(action="apply", opportunity_id="OP-1", payload={"a": 1})
        h2 = hash_payload(action="apply", opportunity_id="OP-1", payload={"a": 2})
        assert h1 != h2

    def test_length_16_hex(self) -> None:
        h = hash_payload(action="x", opportunity_id="y", payload={})
        assert len(h) == 16
        int(h, 16)  # valid hex


class TestCampaignContext:
    def test_run_id_and_correlation_not_empty(self) -> None:
        ctx = CampaignContext()
        assert ctx.run_id
        assert ctx.correlation_id
        assert ctx.started_at_utc
        assert ctx.dry_run is True

    def test_to_dict_roundtrip(self) -> None:
        ctx = CampaignContext(dry_run=False)
        d = ctx.to_dict()
        assert d["run_id"] == ctx.run_id
        assert d["correlation_id"] == ctx.correlation_id
        assert d["dry_run"] is False

    def test_unique_per_instance(self) -> None:
        ctx1 = CampaignContext()
        ctx2 = CampaignContext()
        assert ctx1.run_id != ctx2.run_id
        assert ctx1.correlation_id != ctx2.correlation_id


class TestIdempotencyStore:
    def test_mark_processed_returns_false_first_time(self) -> None:
        store = IdempotencyStore()
        dup = store.mark_processed(action="a", opportunity_id="1", payload_hash="h")
        assert dup is False

    def test_is_processed_true_after_mark(self) -> None:
        store = IdempotencyStore()
        store.mark_processed(action="a", opportunity_id="1", payload_hash="h")
        assert store.is_processed(action="a", opportunity_id="1", payload_hash="h")

    def test_different_keys_are_independent(self) -> None:
        store = IdempotencyStore()
        store.mark_processed(action="a", opportunity_id="1", payload_hash="h1")
        assert not store.is_processed(action="a", opportunity_id="1", payload_hash="h2")

    def test_eviction_on_overflow(self) -> None:
        store = IdempotencyStore()
        # override max size via private attr for testability
        store._MAX_SIZE = 3
        store.mark_processed(action="a", opportunity_id="1", payload_hash="h1")
        store.mark_processed(action="a", opportunity_id="2", payload_hash="h2")
        store.mark_processed(action="a", opportunity_id="3", payload_hash="h3")
        store.mark_processed(action="a", opportunity_id="4", payload_hash="h4")
        assert not store.is_processed(action="a", opportunity_id="1", payload_hash="h1")
        assert store.is_processed(action="a", opportunity_id="4", payload_hash="h4")

    def test_clear_empties_store(self) -> None:
        store = IdempotencyStore()
        store.mark_processed(action="a", opportunity_id="1", payload_hash="h")
        store.clear()
        assert not store.is_processed(action="a", opportunity_id="1", payload_hash="h")


class TestCheckExpiry:
    def test_fresh_approval_not_expired(self) -> None:
        from datetime import datetime

        now = datetime.utcnow().isoformat()
        result = check_expiry(now, ttl_hours=168.0)
        assert result["expired"] is False
        assert result["remaining_hours"] > 167.0
        assert result["error"] is None

    def test_old_approval_is_expired(self) -> None:
        result = check_expiry("2020-01-01T00:00:00", ttl_hours=168.0)
        assert result["expired"] is True
        assert result["remaining_hours"] == 0.0
        assert result["error"] is None

    def test_invalid_timestamp_is_expired(self) -> None:
        result = check_expiry("garbage", ttl_hours=168.0)
        assert result["expired"] is True
        assert result["remaining_hours"] == 0.0
        assert result["error"] == "Invalid timestamp"

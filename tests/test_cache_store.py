"""Tests for cache_store.py — SQLite response cache."""

import time

import pytest

from cache_store import ResponseCache, CacheEntry, _sha256, _cache_key, DEFAULT_TTL


class TestHelpers:

    def test_sha256_deterministic(self):
        assert _sha256("hello") == _sha256("hello")
        assert _sha256("hello") != _sha256("world")

    def test_cache_key_includes_all_params(self):
        k1 = _cache_key("arch", "task", "advisory", "ctx")
        k2 = _cache_key("arch", "task", "advisory", "ctx2")
        k3 = _cache_key("arch", "task", "implementation", "ctx")
        assert k1 != k2
        assert k1 != k3


class TestResponseCache:

    @pytest.fixture
    def cache(self, tmp_path):
        db = str(tmp_path / "test.db")
        c = ResponseCache(db_path=db)
        yield c
        c.close()

    def test_put_and_get_exact(self, cache):
        cache.put("architect", "task1", "advisory", "ctx", "response text", tokens_used=100)
        entry = cache.get("architect", "task1", "advisory", "ctx")
        assert entry is not None
        assert entry.response == "response text"
        assert entry.tokens_used == 100
        assert entry.hit_count == 1

    def test_get_miss(self, cache):
        assert cache.get("architect", "task1", "advisory", "ctx") is None

    def test_get_expired(self, cache):
        cache.put("architect", "task1", "advisory", "ctx", "resp", ttl=-1)
        assert cache.get("architect", "task1", "advisory", "ctx") is None

    def test_get_similar(self, cache):
        cache.put("architect", "task1", "advisory", "ctx1", "resp1")
        cache.put("architect", "task1", "advisory", "ctx2", "resp2")
        entry = cache.get_similar("architect", "task1", "advisory")
        assert entry is not None
        # Should return the freshest (ctx2)
        assert entry.response == "resp2"

    def test_get_similar_miss(self, cache):
        assert cache.get_similar("architect", "no-task", "advisory") is None

    def test_hit_count_increments(self, cache):
        cache.put("architect", "task1", "advisory", "ctx", "resp")
        cache.get("architect", "task1", "advisory", "ctx")
        entry = cache.get("architect", "task1", "advisory", "ctx")
        assert entry.hit_count == 2

    def test_put_upsert(self, cache):
        cache.put("architect", "task1", "advisory", "ctx", "old")
        cache.put("architect", "task1", "advisory", "ctx", "new")
        entry = cache.get("architect", "task1", "advisory", "ctx")
        assert entry.response == "new"
        assert entry.hit_count == 1  # Reset on upsert

    def test_invalidate(self, cache):
        key = cache.put("architect", "task1", "advisory", "ctx", "resp")
        assert cache.invalidate(key) is True
        assert cache.get("architect", "task1", "advisory", "ctx") is None

    def test_invalidate_missing(self, cache):
        assert cache.invalidate("nonexistent") is False

    def test_invalidate_expert(self, cache):
        cache.put("architect", "task1", "advisory", "ctx1", "r1")
        cache.put("architect", "task2", "advisory", "ctx2", "r2")
        cache.put("code_reviewer", "task3", "advisory", "ctx3", "r3")
        removed = cache.invalidate_expert("architect")
        assert removed == 2
        assert cache.get("code_reviewer", "task3", "advisory", "ctx3") is not None

    def test_cleanup_expired(self, cache):
        cache.put("architect", "task1", "advisory", "ctx", "resp", ttl=-1)
        cache.put("architect", "task2", "advisory", "ctx", "resp", ttl=3600)
        removed = cache.cleanup_expired()
        assert removed == 1

    def test_record_stat_and_get_stats(self, cache):
        cache.record_stat("hit", "architect", tokens_saved=500)
        cache.record_stat("hit", "architect", tokens_saved=300)
        cache.record_stat("miss", "architect")
        stats = cache.get_stats(hours=1)
        assert stats["events"]["hit"]["count"] == 2
        assert stats["events"]["hit"]["tokens_saved"] == 800
        assert stats["events"]["miss"]["count"] == 1
        assert stats["hit_rate"] == round(2/3, 4)
        assert stats["total_tokens_saved"] == 800

    def test_get_stats_empty(self, cache):
        stats = cache.get_stats()
        assert stats["hit_rate"] == 0.0
        assert stats["cache_entries"] == 0

    def test_default_ttl_per_expert(self, cache):
        cache.put("plan_reviewer", "task", "advisory", "ctx", "resp")
        entry = cache.get("plan_reviewer", "task", "advisory", "ctx")
        assert entry is not None
        # TTL for plan_reviewer is 900s
        assert entry.expires_at - entry.created_at == pytest.approx(900, abs=2)

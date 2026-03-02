"""Tests for cache_metrics.py — aggregated metrics."""

import pytest

from cache_store import ResponseCache
from expert_memory import ExpertMemory
from cache_metrics import CacheMetrics


class TestCacheMetrics:

    @pytest.fixture
    def parts(self, tmp_path):
        rc = ResponseCache(db_path=str(tmp_path / "cache.db"))
        em = ExpertMemory(base_dir=str(tmp_path / "memory"))
        return rc, em

    @pytest.fixture
    def metrics(self, parts):
        rc, em = parts
        m = CacheMetrics(rc, em)
        yield m
        rc.close()

    def test_empty_report(self, metrics):
        report = metrics.get_report()
        assert report["prompt_cache"]["hits"] == 0
        assert report["response_cache"]["hit_rate"] == 0.0
        assert report["expert_memory"]["projects"] == 0

    def test_record_prompt_cache(self, metrics):
        metrics.record_prompt_cache(cache_creation_tokens=500, cache_read_tokens=None)
        metrics.record_prompt_cache(cache_creation_tokens=None, cache_read_tokens=400)
        metrics.record_prompt_cache(cache_creation_tokens=None, cache_read_tokens=300)

        report = metrics.get_report()
        assert report["prompt_cache"]["creations"] == 1
        assert report["prompt_cache"]["hits"] == 2
        assert report["prompt_cache"]["tokens_saved"] == 700

    def test_combined_report(self, parts):
        rc, em = parts
        m = CacheMetrics(rc, em)

        # Response cache activity
        rc.put("architect", "task1", "advisory", "ctx", "resp", tokens_used=100)
        rc.record_stat("miss", "architect")
        rc.get("architect", "task1", "advisory", "ctx")
        rc.record_stat("hit", "architect", tokens_saved=100)

        # Memory activity
        em.append("proj1", "architect", "Some learning")

        # Prompt cache
        m.record_prompt_cache(None, 200)

        report = m.get_report()
        assert report["response_cache"]["hits"] == 1
        assert report["response_cache"]["misses"] == 1
        assert report["response_cache"]["entries"] == 1
        assert report["expert_memory"]["total_entries"] == 1
        assert report["prompt_cache"]["tokens_saved"] == 200

        rc.close()

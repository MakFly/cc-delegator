"""
Cache Metrics — Aggregator for prompt cache, response cache, and expert memory stats.

Combines data from all three pillars into a single report, exposed via the
``glm_cache_stats`` MCP tool.
"""

import logging
from typing import Optional

from cache_store import ResponseCache
from expert_memory import ExpertMemory

logger = logging.getLogger("glm-delegator.metrics")


class CacheMetrics:
    """Aggregates statistics from cache and memory subsystems."""

    def __init__(
        self,
        response_cache: ResponseCache,
        expert_memory: ExpertMemory,
    ):
        self.response_cache = response_cache
        self.expert_memory = expert_memory
        # Prompt cache counters (updated by server after each provider call)
        self._prompt_cache_hits = 0
        self._prompt_cache_creations = 0
        self._prompt_cache_tokens_saved = 0

    # -- prompt cache tracking (called by server) ----------------------------

    def record_prompt_cache(
        self,
        cache_creation_tokens: Optional[int],
        cache_read_tokens: Optional[int],
    ):
        """Record prompt cache metrics from a ProviderResponse."""
        if cache_creation_tokens:
            self._prompt_cache_creations += 1
        if cache_read_tokens:
            self._prompt_cache_hits += 1
            self._prompt_cache_tokens_saved += cache_read_tokens

    # -- aggregate report ----------------------------------------------------

    def get_report(self, hours: int = 24) -> dict:
        """Build a combined metrics report."""
        response_stats = self.response_cache.get_stats(hours=hours)
        memory_stats = self.expert_memory.stats()

        return {
            "period_hours": hours,
            "prompt_cache": {
                "hits": self._prompt_cache_hits,
                "creations": self._prompt_cache_creations,
                "tokens_saved": self._prompt_cache_tokens_saved,
            },
            "response_cache": {
                "hit_rate": response_stats["hit_rate"],
                "hits": response_stats["events"].get("hit", {}).get("count", 0),
                "misses": response_stats["events"].get("miss", {}).get("count", 0),
                "tokens_saved": response_stats["total_tokens_saved"],
                "entries": response_stats["cache_entries"],
            },
            "expert_memory": memory_stats,
        }

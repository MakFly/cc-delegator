"""
Response Cache — SQLite-backed deduplication for expert responses.

Hash-based cache keyed on (expert, task, mode, context). Supports exact and
partial (task-only) matching, per-expert TTL, hit tracking, and periodic cleanup.
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("glm-delegator.cache")

# ---------------------------------------------------------------------------
# TTL defaults (seconds) per expert
# ---------------------------------------------------------------------------
DEFAULT_TTL = {
    "architect": 3600,        # 1h
    "code_reviewer": 1800,    # 30min
    "security_analyst": 3600, # 1h
    "plan_reviewer": 900,     # 15min
    "scope_analyst": 1800,    # 30min
}

FALLBACK_TTL = 1800  # 30min for unknown experts


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    """A single cached response."""
    cache_key: str
    expert: str
    response: str
    tokens_used: Optional[int]
    model: Optional[str]
    created_at: float
    expires_at: float
    hit_count: int
    last_hit_at: Optional[float]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS response_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT UNIQUE NOT NULL,
    expert TEXT NOT NULL,
    task_hash TEXT NOT NULL,
    mode TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    response TEXT NOT NULL,
    tokens_used INTEGER,
    model TEXT,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    hit_count INTEGER DEFAULT 0,
    last_hit_at REAL
);

CREATE INDEX IF NOT EXISTS idx_cache_expert ON response_cache(expert);
CREATE INDEX IF NOT EXISTS idx_cache_task_hash ON response_cache(task_hash);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON response_cache(expires_at);

CREATE TABLE IF NOT EXISTS cache_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    event_type TEXT NOT NULL,
    expert TEXT,
    tokens_saved INTEGER DEFAULT 0,
    cache_key TEXT
);

CREATE INDEX IF NOT EXISTS idx_stats_timestamp ON cache_stats(timestamp);
CREATE INDEX IF NOT EXISTS idx_stats_event ON cache_stats(event_type);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _cache_key(expert: str, task: str, mode: str, context: str) -> str:
    """Full cache key: hash of all parameters."""
    combined = f"{expert}:{task}:{mode}:{context}"
    return _sha256(combined)


# ---------------------------------------------------------------------------
# ResponseCache
# ---------------------------------------------------------------------------

class ResponseCache:
    """SQLite-backed response cache with per-expert TTL."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(Path.home(), ".glm", "cache", "responses.db")
        self.db_path = db_path
        self._ensure_dir()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # -- lifecycle -----------------------------------------------------------

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _init_db(self):
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # -- read ----------------------------------------------------------------

    def get(
        self, expert: str, task: str, mode: str, context: str
    ) -> Optional[CacheEntry]:
        """Exact match lookup. Returns None on miss, updates hit_count on hit."""
        key = _cache_key(expert, task, mode, context)
        now = time.time()

        row = self._conn.execute(
            "SELECT * FROM response_cache WHERE cache_key = ? AND expires_at > ?",
            (key, now),
        ).fetchone()

        if row is None:
            return None

        # Update hit stats
        self._conn.execute(
            "UPDATE response_cache SET hit_count = hit_count + 1, last_hit_at = ? "
            "WHERE cache_key = ?",
            (now, key),
        )
        self._conn.commit()

        return CacheEntry(
            cache_key=row["cache_key"],
            expert=row["expert"],
            response=row["response"],
            tokens_used=row["tokens_used"],
            model=row["model"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            hit_count=row["hit_count"] + 1,
            last_hit_at=now,
        )

    def get_similar(
        self, expert: str, task: str, mode: str
    ) -> Optional[CacheEntry]:
        """Partial match by task_hash only (ignores context). Returns freshest."""
        task_h = _sha256(task)
        now = time.time()

        row = self._conn.execute(
            "SELECT * FROM response_cache "
            "WHERE expert = ? AND task_hash = ? AND mode = ? AND expires_at > ? "
            "ORDER BY created_at DESC LIMIT 1",
            (expert, task_h, mode, now),
        ).fetchone()

        if row is None:
            return None

        # Update hit stats
        self._conn.execute(
            "UPDATE response_cache SET hit_count = hit_count + 1, last_hit_at = ? "
            "WHERE cache_key = ?",
            (now, row["cache_key"]),
        )
        self._conn.commit()

        return CacheEntry(
            cache_key=row["cache_key"],
            expert=row["expert"],
            response=row["response"],
            tokens_used=row["tokens_used"],
            model=row["model"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            hit_count=row["hit_count"] + 1,
            last_hit_at=now,
        )

    # -- write ---------------------------------------------------------------

    def put(
        self,
        expert: str,
        task: str,
        mode: str,
        context: str,
        response: str,
        tokens_used: Optional[int] = None,
        model: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        """Store a response. Returns the cache_key."""
        key = _cache_key(expert, task, mode, context)
        task_h = _sha256(task)
        context_h = _sha256(context)
        now = time.time()

        if ttl is None:
            ttl = DEFAULT_TTL.get(expert, FALLBACK_TTL)

        expires_at = now + ttl

        self._conn.execute(
            """INSERT INTO response_cache
               (cache_key, expert, task_hash, mode, context_hash, response,
                tokens_used, model, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(cache_key) DO UPDATE SET
                 response = excluded.response,
                 tokens_used = excluded.tokens_used,
                 model = excluded.model,
                 created_at = excluded.created_at,
                 expires_at = excluded.expires_at,
                 hit_count = 0,
                 last_hit_at = NULL
            """,
            (key, expert, task_h, mode, context_h, response, tokens_used, model, now, expires_at),
        )
        self._conn.commit()

        logger.debug(f"Cached response: expert={expert}, key={key[:16]}..., ttl={ttl}s")
        return key

    # -- invalidation --------------------------------------------------------

    def invalidate(self, cache_key: str) -> bool:
        """Remove a specific entry. Returns True if found."""
        cursor = self._conn.execute(
            "DELETE FROM response_cache WHERE cache_key = ?", (cache_key,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def invalidate_expert(self, expert: str) -> int:
        """Remove all entries for an expert. Returns count removed."""
        cursor = self._conn.execute(
            "DELETE FROM response_cache WHERE expert = ?", (expert,)
        )
        self._conn.commit()
        logger.info(f"Invalidated {cursor.rowcount} entries for expert={expert}")
        return cursor.rowcount

    # -- cleanup -------------------------------------------------------------

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.time()
        cursor = self._conn.execute(
            "DELETE FROM response_cache WHERE expires_at <= ?", (now,)
        )
        removed = cursor.rowcount
        self._conn.commit()
        if removed:
            logger.info(f"Cleaned up {removed} expired cache entries")
        return removed

    # -- stats ---------------------------------------------------------------

    def record_stat(
        self,
        event_type: str,
        expert: Optional[str] = None,
        tokens_saved: int = 0,
        cache_key: Optional[str] = None,
    ):
        """Record a cache event (hit, miss, eviction, prompt_cache_hit)."""
        self._conn.execute(
            "INSERT INTO cache_stats (timestamp, event_type, expert, tokens_saved, cache_key) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), event_type, expert, tokens_saved, cache_key),
        )
        self._conn.commit()

    def get_stats(self, hours: int = 24) -> dict:
        """Aggregate cache statistics for the last N hours."""
        cutoff = time.time() - (hours * 3600)

        rows = self._conn.execute(
            "SELECT event_type, COUNT(*) as count, SUM(tokens_saved) as total_tokens "
            "FROM cache_stats WHERE timestamp > ? GROUP BY event_type",
            (cutoff,),
        ).fetchall()

        stats = {
            "period_hours": hours,
            "events": {},
            "total_tokens_saved": 0,
        }
        for row in rows:
            stats["events"][row["event_type"]] = {
                "count": row["count"],
                "tokens_saved": row["total_tokens"] or 0,
            }
            stats["total_tokens_saved"] += row["total_tokens"] or 0

        # Hit rate
        hits = stats["events"].get("hit", {}).get("count", 0)
        misses = stats["events"].get("miss", {}).get("count", 0)
        total = hits + misses
        stats["hit_rate"] = round(hits / total, 4) if total > 0 else 0.0

        # Cache size
        size_row = self._conn.execute(
            "SELECT COUNT(*) as entries FROM response_cache"
        ).fetchone()
        stats["cache_entries"] = size_row["entries"]

        return stats

"""
Expert Memory — Persistent per-project, per-expert learning system.

Stores key insights extracted from expert responses in markdown files under
``~/.glm/memory/{project_id}/``, where *project_id* is a short hash of the
working directory.  Injected into future prompts so experts build on prior
knowledge.
"""

import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("glm-delegator.memory")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_INJECTION_CHARS = 2000

# Patterns to extract one-liner learnings from expert responses.
def _heading_pattern(label: str) -> re.Pattern:
    """Build a regex that matches e.g. **Recommendation:** or Recommendation: with markdown bold."""
    return re.compile(
        rf"(?:^|\n)\s*\*{{0,2}}{label}\*{{0,2}}\s*[:\-]\s*\**\s*(.+)",
        re.IGNORECASE,
    )

_LEARNING_PATTERNS = [
    _heading_pattern("Recommendation"),
    _heading_pattern(r"Bottom\s+line"),
    _heading_pattern("Verdict"),
    _heading_pattern(r"Risk\s+Rating"),
    _heading_pattern("Summary"),
    _heading_pattern(r"Key\s+Insight"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def project_id_from_dir(working_dir: str) -> str:
    """Derive a short, stable project id from the working directory path."""
    return hashlib.sha256(working_dir.encode()).hexdigest()[:12]


def _memory_dir() -> Path:
    return Path.home() / ".glm" / "memory"


# ---------------------------------------------------------------------------
# ExpertMemory
# ---------------------------------------------------------------------------

class ExpertMemory:
    """Read/write per-project expert memory files."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir) if base_dir else _memory_dir()

    # -- read ----------------------------------------------------------------

    def load(self, project_id: str, expert: str) -> str:
        """Load the full memory file for a given project+expert. Returns '' if absent."""
        path = self._path(project_id, expert)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"Failed to read memory {path}: {e}")
            return ""

    def get_injection(self, project_id: str, expert: str) -> str:
        """Return memory content truncated to MAX_INJECTION_CHARS for prompt injection."""
        content = self.load(project_id, expert)
        if not content:
            return ""
        if len(content) > MAX_INJECTION_CHARS:
            content = content[-MAX_INJECTION_CHARS:]
            # Trim to nearest section boundary to avoid broken markdown
            idx = content.find("\n## ")
            if idx != -1:
                content = content[idx:]
        return content.strip()

    # -- write ---------------------------------------------------------------

    def append(self, project_id: str, expert: str, learning: str):
        """Append a new learning entry with a date header."""
        path = self._path(project_id, expert)
        path.parent.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n## {date_str}\n{learning.strip()}\n"

        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(entry)
            logger.debug(f"Memory appended: {expert} @ {project_id}")
        except OSError as e:
            logger.warning(f"Failed to write memory {path}: {e}")

    # -- extraction ----------------------------------------------------------

    @staticmethod
    def extract_learning(response: str) -> Optional[str]:
        """
        Extract a one-liner learning from an expert response using regex.

        Returns the first match from known heading patterns, or None.
        """
        for pattern in _LEARNING_PATTERNS:
            m = pattern.search(response)
            if m:
                learning = m.group(1).strip()
                # Sanity: skip if too short or too long
                if 10 <= len(learning) <= 500:
                    return learning
        return None

    # -- stats ---------------------------------------------------------------

    def stats(self) -> dict:
        """Return global memory statistics."""
        if not self.base_dir.exists():
            return {"projects": 0, "total_entries": 0, "by_expert": {}}

        projects = 0
        total_entries = 0
        by_expert: dict[str, int] = {}

        for project_dir in self.base_dir.iterdir():
            if not project_dir.is_dir():
                continue
            projects += 1
            for md_file in project_dir.glob("*.md"):
                expert = md_file.stem
                content = md_file.read_text(encoding="utf-8")
                count = content.count("\n## ")
                total_entries += count
                by_expert[expert] = by_expert.get(expert, 0) + count

        return {
            "projects": projects,
            "total_entries": total_entries,
            "by_expert": by_expert,
        }

    # -- internal ------------------------------------------------------------

    def _path(self, project_id: str, expert: str) -> Path:
        return self.base_dir / project_id / f"{expert}.md"

"""
Claude Memory Bridge — Bidirectional memory between Claude Code and GLM Experts.

Direction 1 (Claude Code → Experts):
    Reads Claude Code project memory files and CLAUDE.md, returns injectable context.

Direction 2 (Experts → Claude Code):
    Promotes expert learnings into Claude Code's memory directory.

No-op graceful when paths don't exist.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("glm-delegator.claude-bridge")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_PROJECT_CONTEXT_CHARS = 1500
MAX_CLAUDE_MD_CHARS = 800

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def encode_working_dir(path: str) -> str:
    """Encode a working directory path into Claude Code's project directory name.

    ``/home/kev/foo`` → ``-home-kev-foo``

    This matches the encoding used by Claude Code for
    ``~/.claude/projects/{encoded_path}/``.
    """
    return path.replace("/", "-").lstrip("-")


# ---------------------------------------------------------------------------
# ClaudeMemoryBridge
# ---------------------------------------------------------------------------

class ClaudeMemoryBridge:
    """Bidirectional bridge between Claude Code memory and GLM expert prompts."""

    def __init__(self, projects_dir: Optional[str] = None):
        self.projects_dir = Path(projects_dir) if projects_dir else CLAUDE_PROJECTS_DIR

    # -- Direction 1: Claude Code → Experts ----------------------------------

    def get_project_context(self, working_dir: str) -> str:
        """Read Claude Code memory for a project and return injectable context.

        Reads (in priority order):
        1. Topic files from ``memory/*.md`` (excluding MEMORY.md)
        2. ``memory/MEMORY.md`` (root memory)
        3. ``{working_dir}/CLAUDE.md`` (project conventions, truncated)

        Returns empty string if nothing found. Total capped at MAX_PROJECT_CONTEXT_CHARS.
        """
        if not working_dir:
            return ""

        encoded = encode_working_dir(working_dir)
        project_path = self.projects_dir / encoded

        parts: list[str] = []

        # 1. Topic files (memory/*.md except MEMORY.md)
        memory_dir = project_path / "memory"
        if memory_dir.is_dir():
            try:
                for md_file in sorted(memory_dir.glob("*.md")):
                    if md_file.name.upper() == "MEMORY.MD":
                        continue
                    try:
                        content = md_file.read_text(encoding="utf-8").strip()
                        if content:
                            parts.append(f"### {md_file.stem}\n{content}")
                    except OSError:
                        continue
            except OSError:
                pass

        # 2. MEMORY.md (root memory)
        memory_md = project_path / "memory" / "MEMORY.md"
        if memory_md.is_file():
            try:
                content = memory_md.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"### Project Memory\n{content}")
            except OSError:
                pass

        # 3. {working_dir}/CLAUDE.md (project conventions)
        claude_md = Path(working_dir) / "CLAUDE.md"
        if claude_md.is_file():
            try:
                content = claude_md.read_text(encoding="utf-8").strip()
                if content:
                    if len(content) > MAX_CLAUDE_MD_CHARS:
                        content = content[:MAX_CLAUDE_MD_CHARS] + "\n[...truncated]"
                    parts.append(f"### CLAUDE.md\n{content}")
            except OSError:
                pass

        if not parts:
            return ""

        result = "\n\n".join(parts)

        # Cap total size
        if len(result) > MAX_PROJECT_CONTEXT_CHARS:
            result = result[:MAX_PROJECT_CONTEXT_CHARS] + "\n[...truncated]"

        return result

    # -- Direction 2: Experts → Claude Code ----------------------------------

    def promote_learning(
        self, working_dir: str, expert: str, learning: str
    ) -> bool:
        """Write an expert learning into Claude Code's memory directory.

        Creates/appends to ``~/.claude/projects/{encoded}/memory/glm-experts.md``.
        Deduplicates by substring match before writing.

        Returns True if written, False if skipped (empty, duplicate, or error).
        """
        if not working_dir or not expert or not learning:
            return False

        learning = learning.strip()
        if not learning:
            return False

        encoded = encode_working_dir(working_dir)
        memory_dir = self.projects_dir / encoded / "memory"
        target = memory_dir / "glm-experts.md"

        # Dedup: check if learning already exists
        if target.is_file():
            try:
                existing = target.read_text(encoding="utf-8")
                if learning in existing:
                    logger.debug(f"Duplicate learning skipped for {expert}")
                    return False
            except OSError:
                pass

        # Write
        try:
            memory_dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            entry = f"\n## {date_str} [{expert}]\n{learning}\n"

            with open(target, "a", encoding="utf-8") as f:
                f.write(entry)

            logger.debug(f"Learning promoted: {expert} → Claude Code memory")
            return True

        except OSError as e:
            logger.warning(f"Failed to promote learning: {e}")
            return False

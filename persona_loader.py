"""Load expert personas from markdown files in prompts/personas/."""

import re
from pathlib import Path
from typing import NamedTuple


class Persona(NamedTuple):
    key: str      # filename stem, e.g. "architect"
    name: str     # parsed from first "# Title" line
    prompt: str   # full file content


def _parse_title(content: str) -> str:
    """Extract the first H1 title from markdown content."""
    match = re.match(r"^#\s+(.+)", content.strip())
    return match.group(1).strip() if match else "Unknown"


def load_personas(personas_dir: Path) -> dict[str, Persona]:
    """Load all *.md files from personas_dir, return dict keyed by stem.

    Files are sorted alphabetically for deterministic ordering.
    """
    if not personas_dir.is_dir():
        raise FileNotFoundError(f"Personas directory not found: {personas_dir}")

    personas: dict[str, Persona] = {}
    for md_file in sorted(personas_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        if not content.strip():
            continue
        key = md_file.stem
        name = _parse_title(content)
        personas[key] = Persona(key=key, name=name, prompt=content)

    return personas


def load_truthfulness_policy(prompts_dir: Path) -> str:
    """Read truthfulness_policy.md from the prompts directory."""
    policy_file = prompts_dir / "truthfulness_policy.md"
    if not policy_file.exists():
        raise FileNotFoundError(f"Truthfulness policy not found: {policy_file}")
    return policy_file.read_text(encoding="utf-8")

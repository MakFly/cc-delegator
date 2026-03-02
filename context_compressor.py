"""
Context Compressor — Automatic context compression for MCP expert calls.

Applies static heuristics first (fast, zero LLM cost), then falls back to
LLM-based summarization if the context is still over the target length.
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from providers import BaseProvider


@dataclass
class CompressionResult:
    """Metadata about a compression operation."""

    original_length: int
    compressed_length: int
    method: str  # "none" | "static" | "llm" | "truncate"
    truncated_blocks: int


class ContextCompressor:
    """Compress context strings to fit within a character budget."""

    TARGET_LENGTH = 5000

    _CODE_BLOCK_RE = re.compile(
        r"(```[^\n]*\n)(.*?)(```)", re.DOTALL
    )
    _LINE_NUMBER_RE = re.compile(r"^\s*\d+[\s|:.]\s?", re.MULTILINE)
    _MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
    _MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
    _DEEP_HEADING_RE = re.compile(r"^#{4,}\s", re.MULTILINE)
    _SEPARATOR_RE = re.compile(r"^[-=]{3,}\s*$", re.MULTILINE)

    def __init__(self, provider: Optional["BaseProvider"] = None):
        self.provider = provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compress(
        self, context: str, target: int | None = None
    ) -> tuple[str, CompressionResult]:
        """Compress *context* to at most *target* characters.

        Returns ``(compressed_text, result_metadata)``.
        """
        if target is None:
            target = self.TARGET_LENGTH

        original_length = len(context)

        # 1. Already short enough — skip entirely
        if original_length <= target:
            return context, CompressionResult(
                original_length=original_length,
                compressed_length=original_length,
                method="none",
                truncated_blocks=0,
            )

        # 2. Static heuristics
        text, truncated_blocks = self._static_pass(context)

        if len(text) <= target:
            return text, CompressionResult(
                original_length=original_length,
                compressed_length=len(text),
                method="static",
                truncated_blocks=truncated_blocks,
            )

        # 3. LLM summarization (if provider available)
        if self.provider is not None:
            try:
                text = await self._llm_summarize(text, target)
                # Safety net — hard truncate if LLM exceeded budget
                if len(text) > target:
                    text = text[:target]
                return text, CompressionResult(
                    original_length=original_length,
                    compressed_length=len(text),
                    method="llm",
                    truncated_blocks=truncated_blocks,
                )
            except Exception:
                pass  # fall through to hard truncate

        # 4. Hard truncate as last resort
        text = text[:target]
        return text, CompressionResult(
            original_length=original_length,
            compressed_length=len(text),
            method="truncate",
            truncated_blocks=truncated_blocks,
        )

    # ------------------------------------------------------------------
    # Static heuristics
    # ------------------------------------------------------------------

    def _static_pass(self, text: str) -> tuple[str, int]:
        """Apply all static heuristics in order. Returns (text, truncated_blocks)."""
        text = self._collapse_whitespace(text)
        text = self._strip_line_numbers(text)
        text = self._strip_markdown_noise(text)
        text, truncated = self._truncate_code_blocks(text)
        text = self._deduplicate_paragraphs(text)
        return text, truncated

    @classmethod
    def _collapse_whitespace(cls, text: str) -> str:
        """Collapse 3+ consecutive newlines to 2, and multiple spaces to 1."""
        text = cls._MULTI_NEWLINE_RE.sub("\n\n", text)
        text = cls._MULTI_SPACE_RE.sub(" ", text)
        return text

    @classmethod
    def _strip_line_numbers(cls, text: str) -> str:
        """Remove leading line numbers inside fenced code blocks."""

        def _strip(match: re.Match) -> str:
            opener = match.group(1)
            body = match.group(2)
            closer = match.group(3)
            body = cls._LINE_NUMBER_RE.sub("", body)
            return f"{opener}{body}{closer}"

        return cls._CODE_BLOCK_RE.sub(_strip, text)

    @classmethod
    def _strip_markdown_noise(cls, text: str) -> str:
        """Flatten deep headings (####+ → ###) and remove separators."""
        text = cls._DEEP_HEADING_RE.sub("### ", text)
        text = cls._SEPARATOR_RE.sub("", text)
        return text

    @classmethod
    def _truncate_code_blocks(cls, text: str, max_lines: int = 20, keep: int = 8) -> tuple[str, int]:
        """Truncate code blocks longer than *max_lines* to first/last *keep* lines."""
        truncated = 0

        def _truncate(match: re.Match) -> str:
            nonlocal truncated
            opener = match.group(1)
            body = match.group(2)
            closer = match.group(3)
            lines = body.splitlines(keepends=True)
            if len(lines) <= max_lines:
                return match.group(0)
            truncated += 1
            head = "".join(lines[:keep])
            tail = "".join(lines[-keep:])
            omitted = len(lines) - 2 * keep
            return f"{opener}{head}... ({omitted} lines omitted)\n{tail}{closer}"

        result = cls._CODE_BLOCK_RE.sub(_truncate, text)
        return result, truncated

    @classmethod
    def _deduplicate_paragraphs(cls, text: str) -> str:
        """Remove duplicate paragraphs (split on blank lines)."""
        paragraphs = re.split(r"\n{2,}", text)
        seen: set[str] = set()
        unique: list[str] = []
        for p in paragraphs:
            normalized = " ".join(p.split()).strip()
            if not normalized:
                continue
            h = hashlib.md5(normalized.encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(p)
        return "\n\n".join(unique)

    # ------------------------------------------------------------------
    # LLM fallback
    # ------------------------------------------------------------------

    async def _llm_summarize(self, text: str, target: int) -> str:
        """Use the LLM provider to summarize *text* under *target* chars."""
        assert self.provider is not None

        system_prompt = (
            f"Summarize the following context to under {target} characters. "
            "Preserve all file paths, function/class signatures, and architectural relationships. "
            "Remove verbose explanations, redundant examples, and decorative formatting. "
            "Output ONLY the summarized context, nothing else."
        )

        response = await self.provider.call(
            system_prompt=system_prompt,
            user_prompt=text,
            temperature=0.1,
        )
        return response.text.strip()

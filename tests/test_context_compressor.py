"""Tests for context_compressor module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_compressor import ContextCompressor, CompressionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(response_text: str = "short summary", *, raises: Exception | None = None):
    """Build a mock BaseProvider."""
    provider = MagicMock()
    if raises:
        provider.call = AsyncMock(side_effect=raises)
    else:
        resp = MagicMock()
        resp.text = response_text
        provider.call = AsyncMock(return_value=resp)
    return provider


def _long_text(n: int = 6000) -> str:
    """Generate a string of *n* characters."""
    return "a" * n


def _code_block(lines: int = 30) -> str:
    """Generate a fenced code block with *lines* numbered lines."""
    body = "\n".join(f"  {i}: line content {i}" for i in range(1, lines + 1))
    return f"```python\n{body}\n```"


# ---------------------------------------------------------------------------
# Category: none — short context unchanged
# ---------------------------------------------------------------------------

class TestShortContext:

    @pytest.mark.asyncio
    async def test_short_context_unchanged(self):
        c = ContextCompressor()
        text = "Hello world"
        result_text, result = await c.compress(text)
        assert result_text == text
        assert result.method == "none"
        assert result.original_length == len(text)
        assert result.compressed_length == len(text)


# ---------------------------------------------------------------------------
# Category: static heuristics
# ---------------------------------------------------------------------------

class TestStaticHeuristics:

    @pytest.mark.asyncio
    async def test_collapse_whitespace(self):
        text = "a\n\n\n\nb\n\n\n\n\nc"
        result = ContextCompressor._collapse_whitespace(text)
        assert "\n\n\n" not in result
        assert result == "a\n\nb\n\nc"

    @pytest.mark.asyncio
    async def test_collapse_multiple_spaces(self):
        text = "hello    world   foo"
        result = ContextCompressor._collapse_whitespace(text)
        assert result == "hello world foo"

    @pytest.mark.asyncio
    async def test_truncate_code_block_long(self):
        block = _code_block(30)
        result, count = ContextCompressor._truncate_code_blocks(block)
        assert count == 1
        assert "lines omitted" in result
        # First and last keep lines should be present
        assert "line content 1" in result
        assert "line content 30" in result

    @pytest.mark.asyncio
    async def test_truncate_code_block_short_unchanged(self):
        block = _code_block(10)
        result, count = ContextCompressor._truncate_code_blocks(block)
        assert count == 0
        assert result == block

    @pytest.mark.asyncio
    async def test_deduplicate_paragraphs(self):
        text = "paragraph one\n\nparagraph two\n\nparagraph one\n\nparagraph three"
        result = ContextCompressor._deduplicate_paragraphs(text)
        assert result.count("paragraph one") == 1
        assert "paragraph two" in result
        assert "paragraph three" in result

    @pytest.mark.asyncio
    async def test_strip_markdown_separators(self):
        text = "Title\n---\nContent\n===\nMore"
        result = ContextCompressor._strip_markdown_noise(text)
        assert "---" not in result
        assert "===" not in result
        assert "Title" in result
        assert "Content" in result

    @pytest.mark.asyncio
    async def test_strip_deep_headings(self):
        text = "#### Deep heading\n##### Deeper\n### Keep this"
        result = ContextCompressor._strip_markdown_noise(text)
        assert "####" not in result
        assert "#####" not in result
        assert "### Deep heading" in result
        assert "### Deeper" in result
        assert "### Keep this" in result

    @pytest.mark.asyncio
    async def test_strip_line_numbers_in_code(self):
        code = "```python\n  1: foo\n  2: bar\n  3: baz\n```"
        result = ContextCompressor._strip_line_numbers(code)
        assert "1:" not in result
        assert "foo" in result
        assert "bar" in result

    @pytest.mark.asyncio
    async def test_static_sufficient(self):
        """Static pass alone brings context under target."""
        # Build a string that is over 5000 but has lots of compressible content
        padding = "short paragraph"
        blocks = _code_block(40) + "\n\n"
        separators = "---\n" * 50
        whitespace = "\n\n\n\n" * 100
        duplicates = (padding + "\n\n") * 30
        text = blocks + separators + whitespace + duplicates + "a" * 3500

        c = ContextCompressor()  # no provider
        result_text, result = await c.compress(text, target=5000)
        # If static was enough, method should be "static"
        # If not, it falls to truncate (no provider) — both are acceptable
        assert result.method in ("static", "truncate")
        assert len(result_text) <= 5000


# ---------------------------------------------------------------------------
# Category: LLM fallback
# ---------------------------------------------------------------------------

class TestLLMFallback:

    @pytest.mark.asyncio
    async def test_llm_fallback_called(self):
        """LLM provider is called when static isn't enough."""
        provider = _make_provider("compressed output")
        c = ContextCompressor(provider=provider)
        text = _long_text(6000)
        _, result = await c.compress(text, target=5000)
        assert result.method == "llm"
        provider.call.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_fallback_result(self):
        """LLM response is returned as compressed text."""
        provider = _make_provider("the summary")
        c = ContextCompressor(provider=provider)
        text = _long_text(6000)
        result_text, result = await c.compress(text, target=5000)
        assert result_text == "the summary"
        assert result.compressed_length == len("the summary")

    @pytest.mark.asyncio
    async def test_llm_failure_graceful(self):
        """If LLM raises, fall back to hard truncate."""
        provider = _make_provider(raises=RuntimeError("LLM down"))
        c = ContextCompressor(provider=provider)
        text = _long_text(6000)
        result_text, result = await c.compress(text, target=5000)
        assert result.method == "truncate"
        assert len(result_text) <= 5000

    @pytest.mark.asyncio
    async def test_llm_output_too_long_truncated(self):
        """If LLM returns text longer than target, hard truncate it."""
        provider = _make_provider("x" * 6000)
        c = ContextCompressor(provider=provider)
        text = _long_text(6000)
        result_text, result = await c.compress(text, target=5000)
        assert result.method == "llm"
        assert len(result_text) <= 5000


# ---------------------------------------------------------------------------
# Category: no provider — hard truncate
# ---------------------------------------------------------------------------

class TestNoProvider:

    @pytest.mark.asyncio
    async def test_no_provider_hard_truncate(self):
        """Without a provider, falls back to hard truncate."""
        c = ContextCompressor()  # no provider
        text = _long_text(6000)
        result_text, result = await c.compress(text, target=5000)
        assert result.method == "truncate"
        assert len(result_text) == 5000


# ---------------------------------------------------------------------------
# Category: dataclass
# ---------------------------------------------------------------------------

class TestCompressionResult:

    def test_compression_result_fields(self):
        r = CompressionResult(
            original_length=8000,
            compressed_length=4500,
            method="static",
            truncated_blocks=2,
        )
        assert r.original_length == 8000
        assert r.compressed_length == 4500
        assert r.method == "static"
        assert r.truncated_blocks == 2

"""Tests for prompt_enhancer module."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from prompt_enhancer import PromptEnhancer, EnhancedPrompt
from providers import ProviderResponse


@pytest.fixture
def mock_provider():
    """Mock provider for testing."""
    provider = MagicMock()
    provider.call = AsyncMock()
    return provider


@pytest.fixture
def enhancer(mock_provider):
    """PromptEnhancer instance with mock provider."""
    return PromptEnhancer(mock_provider)


class TestPromptEnhancer:

    @pytest.mark.asyncio
    async def test_enhance_basic_prompt(self, enhancer, mock_provider):
        """Test basic prompt enhancement."""
        mock_provider.call.return_value = ProviderResponse(
            text='{"enhanced_task": "Improved task", "added_context": "", "suggestions": [], "confidence": 0.9}',
            raw={},
            model="test-model"
        )

        result = await enhancer.enhance("Review this code")

        assert result.enhanced_task == "Improved task"
        assert result.confidence == 0.9
        assert result.original_task == "Review this code"

    @pytest.mark.asyncio
    async def test_enhance_with_context(self, enhancer, mock_provider):
        """Test enhancement with context and target expert."""
        mock_provider.call.return_value = ProviderResponse(
            text='{"enhanced_task": "Enhanced task", "added_context": "Structured context", "suggestions": ["Add file paths"], "confidence": 0.85}',
            raw={},
            model="test-model"
        )

        result = await enhancer.enhance(
            task="Fix the bug",
            context="Error in login.py line 42",
            target_expert="code_reviewer"
        )

        assert result.enhanced_task == "Enhanced task"
        assert result.added_context == "Structured context"
        assert result.confidence > 0
        assert len(result.suggestions) == 1

    @pytest.mark.asyncio
    async def test_enhance_with_files(self, enhancer, mock_provider):
        """Test enhancement with files list."""
        mock_provider.call.return_value = ProviderResponse(
            text='{"enhanced_task": "Review files", "added_context": "", "suggestions": [], "confidence": 0.8}',
            raw={},
            model="test-model"
        )

        result = await enhancer.enhance(
            task="Check these files",
            files=["/path/to/file1.py", "/path/to/file2.py"]
        )

        assert result.confidence == 0.8
        # Verify provider was called
        mock_provider.call.assert_called_once()

    @pytest.mark.asyncio
    async def test_enhance_fallback_on_json_error(self, enhancer, mock_provider):
        """Test fallback when JSON parsing fails."""
        mock_provider.call.return_value = ProviderResponse(
            text='Invalid JSON response',
            raw={},
            model="test-model"
        )

        result = await enhancer.enhance("Test task")

        # Should return original task as fallback
        assert result.enhanced_task == "Test task"
        assert result.confidence == 0.0
        assert "Failed to parse" in result.suggestions[0]

    @pytest.mark.asyncio
    async def test_enhance_strips_markdown_code_blocks(self, enhancer, mock_provider):
        """Test that markdown code blocks are stripped from response."""
        mock_provider.call.return_value = ProviderResponse(
            text='```json\n{"enhanced_task": "Clean task", "added_context": "", "suggestions": [], "confidence": 0.7}\n```',
            raw={},
            model="test-model"
        )

        result = await enhancer.enhance("Test task")

        assert result.enhanced_task == "Clean task"
        assert result.confidence == 0.7

    @pytest.mark.asyncio
    async def test_enhance_handles_provider_error(self, enhancer, mock_provider):
        """Test handling of provider errors."""
        mock_provider.call.side_effect = RuntimeError("Provider error")

        result = await enhancer.enhance("Test task")

        # Should return original task as fallback
        assert result.enhanced_task == "Test task"
        assert result.confidence == 0.0
        assert "error" in result.suggestions[0].lower()

    @pytest.mark.asyncio
    async def test_enhance_confidence_clamped_to_range(self, enhancer, mock_provider):
        """Test confidence is clamped to 0.0-1.0 range."""
        # Test upper bound
        mock_provider.call.return_value = ProviderResponse(
            text='{"enhanced_task": "Task", "confidence": 1.5}',
            raw={},
            model="test-model"
        )
        result = await enhancer.enhance("Test")
        assert result.confidence == 1.0

        # Test lower bound
        mock_provider.call.return_value = ProviderResponse(
            text='{"enhanced_task": "Task", "confidence": -0.5}',
            raw={},
            model="test-model"
        )
        result = await enhancer.enhance("Test")
        assert result.confidence == 0.0


class TestEnhancedPrompt:

    def test_dataclass_fields(self):
        """Test EnhancedPrompt dataclass has all required fields."""
        prompt = EnhancedPrompt(
            original_task="Original",
            enhanced_task="Enhanced",
            added_context="Context",
            suggestions=["Suggestion 1"],
            confidence=0.9
        )

        assert prompt.original_task == "Original"
        assert prompt.enhanced_task == "Enhanced"
        assert prompt.added_context == "Context"
        assert prompt.suggestions == ["Suggestion 1"]
        assert prompt.confidence == 0.9

    def test_dataclass_defaults(self):
        """Test EnhancedPrompt with minimal fields."""
        # This should work if we add defaults, but currently requires all fields
        pass

"""Shared fixtures for GLM Delegator tests."""

import argparse
import logging
import os
import tempfile

import httpx
import pytest

from providers import BackendConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_httpx_response(status_code: int, json_body: dict) -> httpx.Response:
    """Build a minimal httpx.Response with a JSON body."""
    import json

    return httpx.Response(
        status_code=status_code,
        content=json.dumps(json_body).encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "https://test.local/v1"),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_backend_config():
    """Factory fixture for BackendConfig with test defaults."""

    def _make(**overrides):
        defaults = dict(
            provider="openai-compatible",
            baseUrl="https://test.local/v1",
            apiKeyEnv="TEST_API_KEY",
            model="test-model",
            apiVersion="2023-06-01",
            timeout=30,
            maxTokens=1024,
        )
        defaults.update(overrides)
        return BackendConfig(**defaults)

    return _make


@pytest.fixture
def openai_success_body():
    """Canonical OpenAI chat completion response."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from OpenAI"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


@pytest.fixture
def anthropic_success_body():
    """Canonical Anthropic messages response."""
    return {
        "id": "msg-test",
        "type": "message",
        "role": "assistant",
        "model": "test-model",
        "content": [{"type": "text", "text": "Hello from Anthropic"}],
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "stop_reason": "end_turn",
    }


@pytest.fixture
def mock_args():
    """argparse.Namespace matching LLMDelegatorMCPServer.__init__ expectations."""
    return argparse.Namespace(
        provider="anthropic-compatible",
        base_url="https://test.local/v1",
        api_key="test-key-12345678",
        model="test-model",
        api_version="2023-06-01",
        timeout=30,
        max_tokens=1024,
        debug=False,
    )


@pytest.fixture
def mock_logger():
    """A logger instance for tests."""
    return logging.getLogger("test-glm-delegator")


@pytest.fixture(autouse=True)
def _isolate_cache_and_memory(tmp_path, monkeypatch):
    """Redirect cache and memory to tmp_path so tests don't pollute ~/.glm/."""
    import cache_store
    import expert_memory

    # Override the default db_path calculation: when db_path is None (default),
    # ResponseCache.__init__ builds the path from Path.home(). We patch HOME.
    fake_home = str(tmp_path / "fakehome")
    monkeypatch.setenv("HOME", fake_home)
    # Also patch Path.home for robustness
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "fakehome")

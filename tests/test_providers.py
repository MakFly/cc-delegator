"""Tests for providers.py — BackendConfig, BaseProvider, OpenAI, Anthropic, Factory, ConfigLoader."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from providers import (
    AnthropicCompatibleProvider,
    BackendConfig,
    BaseProvider,
    ConfigLoader,
    OpenAICompatibleProvider,
    ProviderFactory,
)
from tests.conftest import make_httpx_response


# ============================================================================
# BackendConfig
# ============================================================================


class TestBackendConfig:

    def test_get_api_key_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "secret-123")
        cfg = BackendConfig(
            provider="openai-compatible",
            baseUrl="https://x",
            apiKeyEnv="MY_KEY",
            model="m",
        )
        assert cfg.get_api_key() == "secret-123"

    def test_get_api_key_returns_empty_when_unset(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_KEY", raising=False)
        cfg = BackendConfig(
            provider="openai-compatible",
            baseUrl="https://x",
            apiKeyEnv="NONEXISTENT_KEY",
            model="m",
        )
        assert cfg.get_api_key() == ""

    def test_get_api_key_returns_empty_when_env_name_empty(self):
        cfg = BackendConfig(
            provider="openai-compatible",
            baseUrl="https://x",
            apiKeyEnv="",
            model="m",
        )
        assert cfg.get_api_key() == ""

    def test_from_dict_all_fields(self):
        data = {
            "provider": "anthropic-compatible",
            "baseUrl": "https://api.z.ai",
            "apiKeyEnv": "Z_KEY",
            "model": "glm-5",
            "apiVersion": "2024-01-01",
            "timeout": 120,
            "maxTokens": 4096,
        }
        cfg = BackendConfig.from_dict(data)
        assert cfg.provider == "anthropic-compatible"
        assert cfg.baseUrl == "https://api.z.ai"
        assert cfg.apiKeyEnv == "Z_KEY"
        assert cfg.model == "glm-5"
        assert cfg.apiVersion == "2024-01-01"
        assert cfg.timeout == 120
        assert cfg.maxTokens == 4096

    def test_from_dict_defaults(self):
        cfg = BackendConfig.from_dict({})
        assert cfg.provider == "openai-compatible"
        assert cfg.timeout == 600
        assert cfg.maxTokens == 8192


# ============================================================================
# BaseProvider start / stop
# ============================================================================


class TestBaseProviderLifecycle:

    def _make_provider(self, make_backend_config, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "k")
        cfg = make_backend_config()
        return OpenAICompatibleProvider(cfg)  # concrete subclass

    async def test_start_creates_client(self, make_backend_config, monkeypatch):
        p = self._make_provider(make_backend_config, monkeypatch)
        assert p._client is None
        await p.start()
        assert isinstance(p._client, httpx.AsyncClient)
        await p.stop()

    async def test_start_idempotent(self, make_backend_config, monkeypatch):
        p = self._make_provider(make_backend_config, monkeypatch)
        await p.start()
        first = p._client
        await p.start()
        assert p._client is first
        await p.stop()

    async def test_stop_closes_client(self, make_backend_config, monkeypatch):
        p = self._make_provider(make_backend_config, monkeypatch)
        await p.start()
        client = p._client
        await p.stop()
        assert client.is_closed

    async def test_stop_resets_client_to_none(self, make_backend_config, monkeypatch):
        p = self._make_provider(make_backend_config, monkeypatch)
        await p.start()
        assert p._client is not None
        await p.stop()
        assert p._client is None

    async def test_restart_after_stop(self, make_backend_config, monkeypatch):
        p = self._make_provider(make_backend_config, monkeypatch)
        await p.start()
        first_client = p._client
        await p.stop()
        assert p._client is None
        await p.start()
        assert p._client is not None
        assert p._client is not first_client
        await p.stop()


# ============================================================================
# _validate_api_key
# ============================================================================


class TestValidateApiKey:

    def test_validate_raises_when_missing(self, make_backend_config, monkeypatch):
        monkeypatch.delenv("TEST_API_KEY", raising=False)
        cfg = make_backend_config()
        p = OpenAICompatibleProvider(cfg)
        with pytest.raises(ValueError, match="API key required"):
            p._validate_api_key()

    def test_validate_passes_when_present(self, make_backend_config, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "present")
        cfg = make_backend_config()
        p = OpenAICompatibleProvider(cfg)
        p._validate_api_key()  # should not raise


# ============================================================================
# _call_with_retry — critical path
# ============================================================================


class TestCallWithRetry:

    def _provider(self, make_backend_config, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "k")
        return OpenAICompatibleProvider(make_backend_config())

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_success_first_attempt(self, mock_sleep, make_backend_config, monkeypatch):
        p = self._provider(make_backend_config, monkeypatch)
        ok = make_httpx_response(200, {"ok": True})
        func = AsyncMock(return_value=ok)

        result = await p._call_with_retry(func)

        assert result.status_code == 200
        mock_sleep.assert_not_called()

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_succeeds_after_429(self, mock_sleep, make_backend_config, monkeypatch):
        p = self._provider(make_backend_config, monkeypatch)
        err_resp = make_httpx_response(429, {"error": "rate limited"})
        ok_resp = make_httpx_response(200, {"ok": True})

        call_count = 0

        async def _func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = err_resp
                resp.raise_for_status()  # will raise
            return ok_resp

        # The first call raises, second succeeds
        func = AsyncMock(side_effect=[
            httpx.HTTPStatusError("429", request=httpx.Request("POST", "https://x"), response=err_resp),
            ok_resp,
        ])

        result = await p._call_with_retry(func)
        assert result.status_code == 200
        mock_sleep.assert_called_once_with(1.5)

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_succeeds_after_two_failures(self, mock_sleep, make_backend_config, monkeypatch):
        p = self._provider(make_backend_config, monkeypatch)
        err_resp = make_httpx_response(429, {"error": "rate limited"})
        ok_resp = make_httpx_response(200, {"ok": True})

        func = AsyncMock(side_effect=[
            httpx.HTTPStatusError("429", request=httpx.Request("POST", "https://x"), response=err_resp),
            httpx.HTTPStatusError("429", request=httpx.Request("POST", "https://x"), response=err_resp),
            ok_resp,
        ])

        result = await p._call_with_retry(func)
        assert result.status_code == 200
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.5)
        mock_sleep.assert_any_call(2.5)

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_exhausted_raises(self, mock_sleep, make_backend_config, monkeypatch):
        p = self._provider(make_backend_config, monkeypatch)
        err_resp = make_httpx_response(429, {"error": "rate limited"})

        func = AsyncMock(side_effect=[
            httpx.HTTPStatusError("429", request=httpx.Request("POST", "https://x"), response=err_resp),
            httpx.HTTPStatusError("429", request=httpx.Request("POST", "https://x"), response=err_resp),
            httpx.HTTPStatusError("429", request=httpx.Request("POST", "https://x"), response=err_resp),
        ])

        with pytest.raises(httpx.HTTPStatusError):
            await p._call_with_retry(func)

        assert mock_sleep.call_count == 2  # sleeps between attempts, not after last

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_non_retryable_401_raises_immediately(self, mock_sleep, make_backend_config, monkeypatch):
        p = self._provider(make_backend_config, monkeypatch)
        err_resp = make_httpx_response(401, {"error": "unauthorized"})

        func = AsyncMock(side_effect=[
            httpx.HTTPStatusError("401", request=httpx.Request("POST", "https://x"), response=err_resp),
        ])

        with pytest.raises(httpx.HTTPStatusError):
            await p._call_with_retry(func)

        mock_sleep.assert_not_called()
        assert func.call_count == 1

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_500_is_retryable(self, mock_sleep, make_backend_config, monkeypatch):
        p = self._provider(make_backend_config, monkeypatch)
        err_resp = make_httpx_response(500, {"error": "server error"})
        ok_resp = make_httpx_response(200, {"ok": True})

        func = AsyncMock(side_effect=[
            httpx.HTTPStatusError("500", request=httpx.Request("POST", "https://x"), response=err_resp),
            ok_resp,
        ])

        result = await p._call_with_retry(func)
        assert result.status_code == 200
        mock_sleep.assert_called_once_with(1.5)

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_529_is_retryable(self, mock_sleep, make_backend_config, monkeypatch):
        p = self._provider(make_backend_config, monkeypatch)
        err_resp = make_httpx_response(529, {"error": "overloaded"})
        ok_resp = make_httpx_response(200, {"ok": True})

        func = AsyncMock(side_effect=[
            httpx.HTTPStatusError("529", request=httpx.Request("POST", "https://x"), response=err_resp),
            ok_resp,
        ])

        result = await p._call_with_retry(func)
        assert result.status_code == 200
        mock_sleep.assert_called_once_with(1.5)


# ============================================================================
# OpenAICompatibleProvider
# ============================================================================


class TestOpenAICompatibleProvider:

    def _make(self, make_backend_config, monkeypatch, key="test-key"):
        monkeypatch.setenv("TEST_API_KEY", key)
        return OpenAICompatibleProvider(make_backend_config())

    def test_openai_headers_with_key(self, make_backend_config, monkeypatch):
        p = self._make(make_backend_config, monkeypatch, key="sk-abc")
        headers = p._build_headers()
        assert headers["Authorization"] == "Bearer sk-abc"
        assert headers["Content-Type"] == "application/json"

    async def test_openai_call_success(self, make_backend_config, monkeypatch, openai_success_body):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json=openai_success_body)
        )
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        resp = await p.call("You are helpful.", "Say hi")
        assert resp.text == "Hello from OpenAI"
        assert resp.tokens_used == 30
        assert resp.model == "test-model"

        await p.stop()

    async def test_openai_call_sends_correct_payload(self, make_backend_config, monkeypatch, openai_success_body):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        captured = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(req.content)
            captured["headers"] = dict(req.headers)
            return httpx.Response(200, json=openai_success_body)

        p._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=p.config.baseUrl)

        await p.call("sys prompt", "user prompt")

        body = captured["body"]
        assert body["model"] == "test-model"
        assert body["max_tokens"] == 1024
        assert body["messages"][0] == {"role": "system", "content": "sys prompt"}
        assert body["messages"][1] == {"role": "user", "content": "user prompt"}

        await p.stop()

    async def test_openai_call_429_raises(self, make_backend_config, monkeypatch):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(429, json={"error": "rate limited"})
        )
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="Rate limit"):
                await p.call("sys", "user")

        await p.stop()

    async def test_openai_call_bad_format_raises(self, make_backend_config, monkeypatch):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"unexpected": "format"})
        )
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        with pytest.raises(RuntimeError, match="Unexpected"):
            await p.call("sys", "user")

        await p.stop()

    async def test_openai_call_401_raises(self, make_backend_config, monkeypatch):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(401, json={"error": "invalid key"})
        )
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        with pytest.raises(RuntimeError, match="Invalid API key"):
            await p.call("sys", "user")

        await p.stop()

    async def test_openai_call_optional_kwargs(self, make_backend_config, monkeypatch, openai_success_body):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        captured = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(req.content)
            return httpx.Response(200, json=openai_success_body)

        p._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=p.config.baseUrl)

        await p.call("sys", "user", temperature=0.5, top_p=0.9)

        assert captured["body"]["temperature"] == 0.5
        assert captured["body"]["top_p"] == 0.9

        await p.stop()


# ============================================================================
# AnthropicCompatibleProvider
# ============================================================================


class TestAnthropicCompatibleProvider:

    def _make(self, make_backend_config, monkeypatch, key="test-key"):
        monkeypatch.setenv("TEST_API_KEY", key)
        return AnthropicCompatibleProvider(
            make_backend_config(provider="anthropic-compatible")
        )

    def test_anthropic_headers(self, make_backend_config, monkeypatch):
        p = self._make(make_backend_config, monkeypatch, key="ant-key")
        headers = p._build_headers()
        assert headers["x-api-key"] == "ant-key"
        assert headers["anthropic-version"] == "2023-06-01"
        assert headers["Content-Type"] == "application/json"

    async def test_anthropic_call_success(self, make_backend_config, monkeypatch, anthropic_success_body):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json=anthropic_success_body)
        )
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        resp = await p.call("You are helpful.", "Say hi")
        assert resp.text == "Hello from Anthropic"
        assert resp.tokens_used == 30  # 10 + 20
        assert resp.model == "test-model"

        await p.stop()

    async def test_anthropic_call_sends_correct_payload(self, make_backend_config, monkeypatch, anthropic_success_body):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        captured = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(req.content)
            return httpx.Response(200, json=anthropic_success_body)

        p._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=p.config.baseUrl)

        await p.call("sys prompt", "user prompt")

        body = captured["body"]
        assert body["system"] == "sys prompt"
        assert body["messages"] == [{"role": "user", "content": "user prompt"}]
        assert body["model"] == "test-model"
        assert body["max_tokens"] == 1024

        await p.stop()

    async def test_anthropic_tokens_none_values(self, make_backend_config, monkeypatch):
        """Regression: usage with None values should not blow up."""
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        body = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "m",
            "usage": {"input_tokens": None, "output_tokens": None},
        }
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        resp = await p.call("s", "u")
        assert resp.tokens_used == 0

        await p.stop()

    async def test_anthropic_tokens_missing_keys(self, make_backend_config, monkeypatch):
        """usage dict present but empty → tokens_used == 0."""
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        body = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "m",
            "usage": {},
        }
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        resp = await p.call("s", "u")
        assert resp.tokens_used == 0

        await p.stop()

    async def test_anthropic_tokens_no_usage(self, make_backend_config, monkeypatch):
        """No usage key at all → tokens_used == 0."""
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        body = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "m",
        }
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        resp = await p.call("s", "u")
        assert resp.tokens_used == 0

        await p.stop()

    async def test_anthropic_call_429_raises(self, make_backend_config, monkeypatch):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(429, json={"error": "rate limited"})
        )
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="Rate limit"):
                await p.call("s", "u")

        await p.stop()

    async def test_anthropic_call_401_raises(self, make_backend_config, monkeypatch):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(401, json={"error": "bad key"})
        )
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        with pytest.raises(RuntimeError, match="Invalid API key"):
            await p.call("s", "u")

        await p.stop()

    async def test_anthropic_call_other_http_error_raises(self, make_backend_config, monkeypatch):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(503, json={"error": "unavailable"})
        )
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="API error 503"):
                await p.call("s", "u")

        await p.stop()

    async def test_anthropic_call_bad_format_raises(self, make_backend_config, monkeypatch):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"bad": "format"})
        )
        p._client = httpx.AsyncClient(transport=transport, base_url=p.config.baseUrl)

        with pytest.raises(RuntimeError, match="Unexpected"):
            await p.call("s", "u")

        await p.stop()

    async def test_anthropic_call_optional_kwargs(self, make_backend_config, monkeypatch, anthropic_success_body):
        p = self._make(make_backend_config, monkeypatch)
        await p.start()

        captured = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(req.content)
            return httpx.Response(200, json=anthropic_success_body)

        p._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=p.config.baseUrl)

        await p.call("s", "u", temperature=0.7, top_p=0.8)

        assert captured["body"]["temperature"] == 0.7
        assert captured["body"]["top_p"] == 0.8

        await p.stop()


# ============================================================================
# ProviderFactory
# ============================================================================


class TestProviderFactory:

    def test_creates_openai_provider(self, make_backend_config, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "k")
        cfg = make_backend_config(provider="openai-compatible")
        p = ProviderFactory.create(cfg)
        assert isinstance(p, OpenAICompatibleProvider)

    def test_creates_anthropic_provider(self, make_backend_config, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "k")
        cfg = make_backend_config(provider="anthropic-compatible")
        p = ProviderFactory.create(cfg)
        assert isinstance(p, AnthropicCompatibleProvider)

    def test_unknown_raises_value_error(self, make_backend_config, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "k")
        cfg = make_backend_config(provider="magic-provider")
        with pytest.raises(ValueError, match="Unknown provider"):
            ProviderFactory.create(cfg)

    def test_register_provider(self, make_backend_config, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "k")

        class CustomProvider(BaseProvider):
            def _build_headers(self):
                return {}
            async def call(self, system_prompt, user_prompt, **kw):
                pass

        ProviderFactory.register_provider("custom", CustomProvider)
        cfg = make_backend_config(provider="custom")
        p = ProviderFactory.create(cfg)
        assert isinstance(p, CustomProvider)
        # Clean up
        del ProviderFactory._providers["custom"]


# ============================================================================
# ConfigLoader
# ============================================================================


class TestConfigLoader:

    def _write_config(self, tmp_path, data):
        path = tmp_path / "backend.config.json"
        path.write_text(json.dumps(data))
        return str(path)

    def test_load_from_file(self, tmp_path):
        path = self._write_config(tmp_path, {
            "activeProfile": "test",
            "profiles": {
                "test": {
                    "provider": "openai-compatible",
                    "baseUrl": "https://test.local",
                    "apiKeyEnv": "K",
                    "model": "m",
                }
            },
        })
        cfg, profile = ConfigLoader.load(config_path=path)
        assert profile == "test"
        assert cfg.provider == "openai-compatible"
        assert cfg.model == "m"

    def test_load_missing_file_fallback_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GLM_DELEGATOR_CONFIG", raising=False)
        path = str(tmp_path / "nonexistent.json")
        cfg, profile = ConfigLoader.load(config_path=path)
        assert profile == "default"
        assert cfg.provider == "anthropic-compatible"

    def test_load_missing_profile_raises(self, tmp_path):
        path = self._write_config(tmp_path, {
            "activeProfile": "missing",
            "profiles": {"other": {}},
        })
        with pytest.raises(ValueError, match="not found"):
            ConfigLoader.load(config_path=path)

    def test_list_profiles(self, tmp_path):
        path = self._write_config(tmp_path, {
            "activeProfile": "a",
            "profiles": {
                "a": {"model": "m1"},
                "b": {"model": "m2"},
            },
        })
        profiles = ConfigLoader.list_profiles(config_path=path)
        assert set(profiles.keys()) == {"a", "b"}

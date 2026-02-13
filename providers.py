#!/usr/bin/env python3
"""
Provider Abstraction Layer for GLM Delegator

Supports multiple LLM backends through a unified interface:
- OpenAI-compatible (OpenAI, DeepInfra, TogetherAI, Ollama, LM Studio...)
- Anthropic-compatible (Anthropic, Z.AI...)
- Easy to extend for other providers
"""

import asyncio
import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass

import httpx

logger = logging.getLogger("glm-delegator.providers")


# =============================================================================
# Configuration Data Classes
# =============================================================================

@dataclass
class BackendConfig:
    """Configuration for a backend provider."""
    provider: str  # 'openai-compatible' or 'anthropic-compatible'
    baseUrl: str
    apiKeyEnv: str
    model: str
    apiVersion: Optional[str] = None
    timeout: int = 600
    maxTokens: int = 8192

    def get_api_key(self) -> str:
        """Get API key from environment variable."""
        if not self.apiKeyEnv:
            return ""
        return os.environ.get(self.apiKeyEnv, "")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackendConfig":
        """Create config from dictionary."""
        return cls(
            provider=data.get("provider", "openai-compatible"),
            baseUrl=data.get("baseUrl", ""),
            apiKeyEnv=data.get("apiKeyEnv", ""),
            model=data.get("model", ""),
            apiVersion=data.get("apiVersion"),
            timeout=data.get("timeout", 600),
            maxTokens=data.get("maxTokens", 8192)
        )


@dataclass
class ProviderResponse:
    """Standardized response from any provider."""
    text: str
    raw: Dict[str, Any]
    model: str
    tokens_used: Optional[int] = None


# =============================================================================
# Abstract Base Provider
# =============================================================================

class BaseProvider(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self, config: BackendConfig):
        self.config = config
        self.api_key = config.get_api_key()
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self):
        """Initialize the HTTP client."""
        if self._client is not None:
            return  # Already initialized
        headers = self._build_headers()
        self._client = httpx.AsyncClient(
            base_url=self.config.baseUrl,
            headers=headers,
            timeout=self.config.timeout
        )
        logger.info(f"{self.__class__.__name__} initialized: {self.config.model}")

    async def stop(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()

    @abstractmethod
    def _build_headers(self) -> Dict[str, str]:
        """Build request headers for this provider."""
        pass

    @abstractmethod
    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> ProviderResponse:
        """Call the LLM with the given prompts."""
        pass

    def _validate_api_key(self):
        """Validate that API key is present if required."""
        if self.config.apiKeyEnv and not self.api_key:
            raise ValueError(
                f"API key required but not found. "
                f"Set environment variable: {self.config.apiKeyEnv}"
            )

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
    MAX_RETRIES = 3
    RETRY_DELAYS = [1.5, 2.5, 4.5]

    async def _call_with_retry(self, request_func):
        """
        Execute an HTTP request with exponential backoff retry.

        Args:
            request_func: Async callable that performs the HTTP request
                          and returns an httpx.Response.

        Returns:
            httpx.Response on success.

        Raises:
            The last httpx.HTTPStatusError if all retries are exhausted.
        """
        last_exception = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await request_func()
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                last_exception = e
                if e.response.status_code not in self.RETRYABLE_STATUS_CODES:
                    raise  # Non-retryable, fail immediately
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Retryable error {e.response.status_code}, "
                        f"attempt {attempt + 1}/{self.MAX_RETRIES}, "
                        f"retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    raise  # Last attempt, propagate


# =============================================================================
# OpenAI-Compatible Provider
# =============================================================================

class OpenAICompatibleProvider(BaseProvider):
    """
    Provider for OpenAI-compatible APIs.

    Supports: OpenAI, DeepInfra, TogetherAI, Ollama, LM Studio, vLLM, etc.
    API format: /v1/chat/completions
    """

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> ProviderResponse:
        """Call OpenAI-compatible chat completions endpoint."""
        if not self._client:
            await self.start()

        self._validate_api_key()

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": self.config.maxTokens
        }

        # Add optional parameters
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        if "top_p" in kwargs:
            payload["top_p"] = kwargs["top_p"]

        logger.debug(f"Calling {self.config.baseUrl}/chat/completions")

        try:
            response = await self._call_with_retry(
                lambda: self._client.post("/chat/completions", json=payload)
            )
            data = response.json()

            # Extract response text
            text = data["choices"][0]["message"]["content"]
            tokens_used = data.get("usage", {}).get("total_tokens")

            return ProviderResponse(
                text=text,
                raw=data,
                model=data.get("model", self.config.model),
                tokens_used=tokens_used
            )

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            logger.error(f"OpenAI-compatible API error: {e.response.status_code} - {error_body}")
            if e.response.status_code == 429:
                raise RuntimeError(f"Rate limit exceeded or insufficient credits. Check your Z.AI balance. Details: {error_body}")
            elif e.response.status_code == 401:
                raise RuntimeError(f"Invalid API key. Check your Z.AI API key. Details: {error_body}")
            raise RuntimeError(f"API error {e.response.status_code}: {error_body}")
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected response format: {e}")
            raise RuntimeError(f"Unexpected API response format: {e}")


# =============================================================================
# Anthropic-Compatible Provider
# =============================================================================

class AnthropicCompatibleProvider(BaseProvider):
    """
    Provider for Anthropic-compatible APIs.

    Supports: Anthropic, Z.AI, etc.
    API format: /v1/messages
    """

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.config.apiVersion or "2023-06-01"
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs
    ) -> ProviderResponse:
        """Call Anthropic-compatible messages endpoint."""
        if not self._client:
            await self.start()

        self._validate_api_key()

        payload = {
            "model": self.config.model,
            "max_tokens": self.config.maxTokens,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt}
            ]
        }

        # Add optional parameters
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        if "top_p" in kwargs:
            payload["top_p"] = kwargs["top_p"]

        logger.debug(f"Calling {self.config.baseUrl}/v1/messages")

        try:
            response = await self._call_with_retry(
                lambda: self._client.post("/v1/messages", json=payload)
            )
            data = response.json()

            # Extract response text
            text = data["content"][0]["text"]
            usage = data.get("usage", {})
            input_t = usage.get("input_tokens") or 0
            output_t = usage.get("output_tokens") or 0
            tokens_used = input_t + output_t

            return ProviderResponse(
                text=text,
                raw=data,
                model=data.get("model", self.config.model),
                tokens_used=tokens_used
            )

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            logger.error(f"Anthropic-compatible API error: {e.response.status_code} - {error_body}")
            if e.response.status_code == 429:
                raise RuntimeError(f"Rate limit exceeded or insufficient credits. Details: {error_body}")
            elif e.response.status_code == 401:
                raise RuntimeError(f"Invalid API key. Details: {error_body}")
            raise RuntimeError(f"API error {e.response.status_code}: {error_body}")
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected response format: {e}")
            raise RuntimeError(f"Unexpected API response format: {e}")


# =============================================================================
# Provider Factory
# =============================================================================

class ProviderFactory:
    """Factory for creating provider instances."""

    _providers: Dict[str, type] = {
        "openai-compatible": OpenAICompatibleProvider,
        "anthropic-compatible": AnthropicCompatibleProvider,
    }

    @classmethod
    def create(cls, config: BackendConfig) -> BaseProvider:
        """Create a provider instance from config."""
        provider_class = cls._providers.get(config.provider)

        if not provider_class:
            raise ValueError(
                f"Unknown provider type: {config.provider}. "
                f"Available: {list(cls._providers.keys())}"
            )

        return provider_class(config)

    @classmethod
    def register_provider(cls, name: str, provider_class: type):
        """Register a new provider type."""
        cls._providers[name] = provider_class


# =============================================================================
# Configuration Loader
# =============================================================================

class ConfigLoader:
    """Load and manage backend configuration."""

    DEFAULT_CONFIG_PATH = "backend.config.json"

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> tuple[BackendConfig, str]:
        """
        Load backend configuration from file.

        Returns:
            Tuple of (BackendConfig, active_profile_name)
        """
        config_path = config_path or os.environ.get(
            "GLM_DELEGATOR_CONFIG",
            cls.DEFAULT_CONFIG_PATH
        )

        logger.info(f"Loading config from: {config_path}")

        try:
            with open(config_path, "r") as f:
                data = __import__("json").load(f)
        except FileNotFoundError:
            logger.warning(f"Config file not found: {config_path}, using environment defaults")
            return cls._from_env(), "default"
        except (KeyError, ValueError) as e:
            logger.error(f"Invalid config file: {e}")
            raise

        active_profile = data.get("activeProfile", "glm")
        profiles = data.get("profiles", {})

        if active_profile not in profiles:
            raise ValueError(f"Active profile '{active_profile}' not found in config")

        profile_data = profiles[active_profile]
        config = BackendConfig.from_dict(profile_data)

        logger.info(f"Using profile: {active_profile} ({config.provider})")
        return config, active_profile

    @classmethod
    def _from_env(cls) -> BackendConfig:
        """Create config from environment variables (legacy fallback)."""
        return BackendConfig(
            provider="anthropic-compatible",
            baseUrl=os.environ.get("GLM_BASE_URL", "https://api.z.ai/api/anthropic"),
            apiKeyEnv="GLM_API_KEY",  # Will try GLM_API_KEY and Z_AI_API_KEY
            model=os.environ.get("GLM_MODEL", "glm-4.7"),
            apiVersion="2023-06-01",
            timeout=600,
            maxTokens=8192
        )

    @classmethod
    def list_profiles(cls, config_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """List all available profiles from config."""
        config_path = config_path or os.environ.get(
            "GLM_DELEGATOR_CONFIG",
            cls.DEFAULT_CONFIG_PATH
        )

        try:
            with open(config_path, "r") as f:
                data = __import__("json").load(f)
            return data.get("profiles", {})
        except FileNotFoundError:
            return {}

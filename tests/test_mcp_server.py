"""Tests for glm_mcp_server.py — EXPERT_PROMPTS, list_tools, call_expert, call_tool, handle_message."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from providers import ProviderResponse

# Import the module (not just classes) so we can patch module-level globals.
import glm_mcp_server
from glm_mcp_server import EXPERT_PROMPTS, LLMDelegatorMCPServer, setup_logging


# ============================================================================
# EXPERT_PROMPTS
# ============================================================================


class TestExpertPrompts:

    def test_has_five_experts(self):
        assert len(EXPERT_PROMPTS) == 5

    def test_expert_keys(self):
        expected = {"architect", "code_reviewer", "security_analyst", "plan_reviewer", "scope_analyst"}
        assert set(EXPERT_PROMPTS.keys()) == expected


# ============================================================================
# list_tools
# ============================================================================


class TestListTools:

    async def test_returns_five_tools(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        result = await srv.list_tools()
        assert len(result["tools"]) == 5

    async def test_names_prefixed_glm(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        result = await srv.list_tools()
        for tool in result["tools"]:
            assert tool["name"].startswith("glm_")

    async def test_schema_has_required_task(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        result = await srv.list_tools()
        for tool in result["tools"]:
            schema = tool["inputSchema"]
            assert "task" in schema["required"]
            assert "task" in schema["properties"]


# ============================================================================
# call_expert
# ============================================================================


class TestCallExpert:

    def _server(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        srv.provider = AsyncMock()
        return srv

    async def test_call_expert_success(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="expert reply", raw={}, model="m")
        )

        result = await srv.call_expert("architect", "design a system")
        assert result == "expert reply"

    async def test_call_expert_passes_system_prompt(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="ok", raw={}, model="m")
        )

        await srv.call_expert("code_reviewer", "review this")

        call_args = srv.provider.call.call_args
        system_prompt = call_args.kwargs.get("system_prompt") or call_args.args[0]
        assert "Code Reviewer" in system_prompt

    async def test_call_expert_unknown_raises(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        with pytest.raises(ValueError, match="Unknown expert"):
            await srv.call_expert("nonexistent", "task")

    async def test_call_expert_provider_error_raises_runtime(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(side_effect=Exception("connection failed"))

        with pytest.raises(RuntimeError, match="GLM Expert Error"):
            await srv.call_expert("architect", "task")

    async def test_call_expert_mode_in_prompt(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="ok", raw={}, model="m")
        )

        await srv.call_expert("architect", "task", mode="implementation")

        call_args = srv.provider.call.call_args
        user_prompt = call_args.kwargs.get("user_prompt") or call_args.args[1]
        assert "IMPLEMENTATION" in user_prompt

        await srv.call_expert("architect", "task", mode="advisory")

        call_args = srv.provider.call.call_args
        user_prompt = call_args.kwargs.get("user_prompt") or call_args.args[1]
        assert "ADVISORY" in user_prompt


# ============================================================================
# call_tool
# ============================================================================


class TestCallTool:

    def _server(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        srv.provider = AsyncMock()
        return srv

    async def test_call_tool_success(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="answer", raw={}, model="m")
        )

        result = await srv.call_tool("glm_architect", {"task": "design"})
        assert result["content"][0]["text"] == "answer"
        assert "isError" not in result

    async def test_call_tool_error_sets_is_error(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(side_effect=Exception("boom"))

        result = await srv.call_tool("glm_architect", {"task": "x"})
        assert result["isError"] is True

    async def test_call_tool_unknown_prefix_raises(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        with pytest.raises(ValueError, match="Unknown tool"):
            await srv.call_tool("other_tool", {"task": "x"})

    async def test_call_tool_default_mode_advisory(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="ok", raw={}, model="m")
        )

        await srv.call_tool("glm_architect", {"task": "x"})

        call_args = srv.provider.call.call_args
        user_prompt = call_args.kwargs.get("user_prompt") or call_args.args[1]
        assert "ADVISORY" in user_prompt


# ============================================================================
# handle_message
# ============================================================================


class TestHandleMessage:

    def _mock_server(self):
        srv = AsyncMock(spec=LLMDelegatorMCPServer)
        srv.start = AsyncMock()
        srv.list_tools = AsyncMock(return_value={"tools": [{"name": "glm_architect"}]})
        srv.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})
        return srv

    async def test_handle_initialize(self):
        result = await glm_mcp_server.handle_message({"method": "initialize"})
        assert result["result"]["protocolVersion"] == "2024-11-05"
        assert result["result"]["serverInfo"]["name"] == "llm-delegator"
        assert result["result"]["serverInfo"]["version"] == "2.0.0"

    async def test_handle_notifications_returns_none(self):
        result = await glm_mcp_server.handle_message({"method": "notifications/initialized"})
        assert result is None

    async def test_handle_tools_list(self):
        mock_srv = self._mock_server()
        original_server = glm_mcp_server.server
        try:
            glm_mcp_server.server = mock_srv

            result = await glm_mcp_server.handle_message({"method": "tools/list"})

            mock_srv.start.assert_called_once()
            mock_srv.list_tools.assert_called_once()
            assert "result" in result
        finally:
            glm_mcp_server.server = original_server

    async def test_handle_tools_call(self):
        mock_srv = self._mock_server()
        original_server = glm_mcp_server.server
        try:
            glm_mcp_server.server = mock_srv

            msg = {
                "method": "tools/call",
                "params": {
                    "name": "glm_architect",
                    "arguments": {"task": "design"},
                },
            }
            result = await glm_mcp_server.handle_message(msg)

            mock_srv.call_tool.assert_called_once_with("glm_architect", {"task": "design"})
            assert "result" in result
        finally:
            glm_mcp_server.server = original_server

    async def test_handle_unknown_method(self):
        result = await glm_mcp_server.handle_message({"method": "bogus/method"})
        assert result["error"]["code"] == -32601
        assert "bogus/method" in result["error"]["message"]


# ============================================================================
# setup_logging
# ============================================================================


class TestSetupLogging:

    def test_setup_logging_returns_logger(self):
        # Reset root logger handlers so basicConfig takes effect
        root = logging.getLogger()
        root.handlers.clear()
        lg = setup_logging(debug=False)
        assert isinstance(lg, logging.Logger)
        assert lg.name == "llm-delegator"

    def test_setup_logging_debug_level(self):
        root = logging.getLogger()
        root.handlers.clear()
        lg = setup_logging(debug=True)
        assert lg.getEffectiveLevel() == logging.DEBUG


# ============================================================================
# LLMDelegatorMCPServer start / stop
# ============================================================================


class TestServerLifecycle:

    async def test_server_start_calls_provider_start(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        srv.provider = AsyncMock()
        await srv.start()
        srv.provider.start.assert_called_once()

    async def test_server_stop_calls_provider_stop(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        srv.provider = AsyncMock()
        await srv.stop()
        srv.provider.stop.assert_called_once()

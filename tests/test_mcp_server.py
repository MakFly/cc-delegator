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

    async def test_returns_eleven_tools(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        result = await srv.list_tools()
        assert len(result["tools"]) == 11

    async def test_expected_tool_names(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        result = await srv.list_tools()
        tool_names = {tool["name"] for tool in result["tools"]}
        assert tool_names == {
            "glm_architect",
            "glm_code_reviewer",
            "glm_security_analyst",
            "glm_plan_reviewer",
            "glm_scope_analyst",
            "glm_enhance_prompt",
            "glm_validate_prompt",
            "glm_route",
            "glm_workflow",
            "glm_get_job_result",
            "glm_cache_stats",
        }

    async def test_names_prefixed_glm(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        result = await srv.list_tools()
        for tool in result["tools"]:
            assert tool["name"].startswith("glm_")

    async def test_schema_required_fields_by_tool(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        result = await srv.list_tools()
        by_name = {tool["name"]: tool["inputSchema"] for tool in result["tools"]}

        expected_required = {
            "glm_architect": ["task"],
            "glm_code_reviewer": ["task"],
            "glm_security_analyst": ["task"],
            "glm_plan_reviewer": ["task"],
            "glm_scope_analyst": ["task"],
            "glm_enhance_prompt": ["task"],
            "glm_validate_prompt": ["task"],
            "glm_route": ["task"],
            "glm_workflow": ["action"],
            "glm_get_job_result": ["job_id"],
        }

        for name, required in expected_required.items():
            schema = by_name[name]
            assert schema["required"] == required
            for field in required:
                assert field in schema["properties"]


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

    async def test_call_expert_includes_truthfulness_policy(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="ok", raw={}, model="m")
        )

        await srv.call_expert("architect", "Assess this design")
        call_args = srv.provider.call.call_args
        user_prompt = call_args.kwargs.get("user_prompt") or call_args.args[1]
        assert "Non-Negotiable Truthfulness Policy" in user_prompt
        assert "Never invent facts" in user_prompt
        assert "Request a targeted web search" in user_prompt


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

    async def test_call_tool_routes_many_files_to_background(self, mock_args, mock_logger):
        """Too many files for direct call are routed to background mode."""
        srv = self._server(mock_args, mock_logger)

        # 11 files > MAX_FILES_COUNT (10) → background job
        files = [f"file{i}.ts" for i in range(11)]
        result = await srv.call_tool("glm_architect", {
            "task": "review",
            "files": files
        })

        assert "isError" not in result
        response_data = json.loads(result["content"][0]["text"])
        assert "job_id" in response_data
        assert response_data["status"] == "pending"

    async def test_call_tool_routes_large_context_to_background(self, mock_args, mock_logger):
        """Large context is routed to background mode instead of being rejected."""
        srv = self._server(mock_args, mock_logger)

        # Bypass compressor so the raw 20K context reaches routing logic
        from context_compressor import CompressionResult
        async def _passthrough(ctx, target=None):
            return ctx, CompressionResult(len(ctx), len(ctx), "none", 0)
        srv.compressor.compress = _passthrough

        # Context larger than MAX_CONTEXT_CHARS (15000) → background job
        large_context = "x" * 20000
        result = await srv.call_tool("glm_architect", {
            "task": "review",
            "context": large_context
        })

        assert "isError" not in result
        response_data = json.loads(result["content"][0]["text"])
        assert "job_id" in response_data
        assert response_data["status"] == "pending"

    async def test_call_tool_accepts_valid_context(self, mock_args, mock_logger):
        """Timeout protection: accept when context is within limits."""
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="ok", raw={}, model="m")
        )

        # 3 files < MAX_FILES_COUNT (5), small context
        result = await srv.call_tool("glm_architect", {
            "task": "review this",
            "context": "some context",
            "files": ["file1.ts", "file2.ts", "file3.ts"]
        })

        assert "isError" not in result
        assert result["content"][0]["text"] == "ok"


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
        assert result["result"]["serverInfo"]["version"] == "3.0.0"

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

    def test_server_init_does_not_log_api_key_value(self, mock_args):
        fake_logger = MagicMock()
        LLMDelegatorMCPServer(mock_args, fake_logger)

        messages = [str(call.args[0]) for call in fake_logger.info.call_args_list if call.args]
        assert "API Key: configured" in messages
        assert not any("test-key-12345678" in msg for msg in messages)
        assert not any("12345678" in msg for msg in messages)

    async def test_server_start_starts_job_manager(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        srv.provider = AsyncMock()
        await srv.start()
        assert srv.job_manager._running is True
        await srv.job_manager.stop()

    async def test_server_stop_stops_job_manager(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        srv.provider = AsyncMock()
        await srv.start()
        await srv.stop()
        assert srv.job_manager._running is False


# ============================================================================
# Background Mode
# ============================================================================


class TestBackgroundMode:

    def _server(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        srv.provider = AsyncMock()
        return srv

    def test_should_use_background_mode_small_context(self, mock_args, mock_logger):
        """Small context (< 12000 chars) should use direct mode."""
        srv = self._server(mock_args, mock_logger)

        result = srv._should_use_background_mode(
            task="small task",
            context="small context",
            files=[]
        )

        assert result is False

    def test_should_use_background_mode_large_context(self, mock_args, mock_logger):
        """Large context (>= 12000 chars) should use background mode."""
        srv = self._server(mock_args, mock_logger)

        # Create context >= 12000 chars
        large_context = "x" * 12000

        result = srv._should_use_background_mode(
            task="task",
            context=large_context,
            files=[]
        )

        assert result is True

    def test_should_use_background_mode_threshold(self, mock_args, mock_logger):
        """Test exact threshold boundary."""
        srv = self._server(mock_args, mock_logger)

        # Task of 1000 chars + context of 10999 chars = 11999 (just under)
        result = srv._should_use_background_mode(
            task="x" * 1000,
            context="y" * 10999,
            files=[]
        )
        assert result is False

        # Task of 1000 chars + context of 11000 chars = 12000 (at threshold)
        result = srv._should_use_background_mode(
            task="x" * 1000,
            context="y" * 11000,
            files=[]
        )
        assert result is True

    async def test_call_tool_returns_job_id_for_large_context(self, mock_args, mock_logger):
        """Large context should return job_id instead of direct response."""
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="expert reply", raw={}, model="m")
        )

        # Bypass compressor so the raw 13K context reaches routing logic
        from context_compressor import CompressionResult
        async def _passthrough(ctx, target=None):
            return ctx, CompressionResult(len(ctx), len(ctx), "none", 0)
        srv.compressor.compress = _passthrough

        # Create context >= 12000 chars
        large_context = "x" * 13000

        result = await srv.call_tool("glm_architect", {
            "task": "review",
            "context": large_context
        })

        # Should return job_id, not direct response
        assert "isError" not in result
        response_data = json.loads(result["content"][0]["text"])
        assert "job_id" in response_data
        assert response_data["status"] == "pending"
        assert response_data["job_id"].startswith("job_")

    async def test_call_tool_direct_mode_for_small_context(self, mock_args, mock_logger):
        """Small context should return direct response."""
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="expert reply", raw={}, model="m")
        )

        result = await srv.call_tool("glm_architect", {
            "task": "review",
            "context": "small context"
        })

        # Should return direct response
        assert "isError" not in result
        assert result["content"][0]["text"] == "expert reply"

    async def test_get_job_result_not_found(self, mock_args, mock_logger):
        """get_job_result returns error for non-existent job."""
        srv = self._server(mock_args, mock_logger)

        result = await srv.call_tool("glm_get_job_result", {
            "job_id": "nonexistent"
        })

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["error"] == "job_not_found"

    async def test_get_job_result_missing_job_id(self, mock_args, mock_logger):
        """get_job_result returns error when job_id is missing."""
        srv = self._server(mock_args, mock_logger)

        result = await srv.call_tool("glm_get_job_result", {})

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["error"] == "job_id_required"

    async def test_get_job_result_pending_job(self, mock_args, mock_logger):
        """get_job_result returns pending status for queued job."""
        srv = self._server(mock_args, mock_logger)

        # Create a job directly
        job = await srv.job_manager.create_job(
            expert="architect",
            task="test task",
            mode="advisory",
            context="",
            files=[]
        )

        result = await srv.call_tool("glm_get_job_result", {
            "job_id": job.job_id
        })

        assert "isError" not in result
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "pending"
        assert "age_seconds" in response_data

    async def test_get_job_result_completed_job(self, mock_args, mock_logger):
        """get_job_result returns result for completed job."""
        srv = self._server(mock_args, mock_logger)

        # Create and complete a job
        job = await srv.job_manager.create_job(
            expert="architect",
            task="test task",
            mode="advisory",
            context="",
            files=[]
        )
        from job_manager import JobStatus
        await srv.job_manager.update_job(
            job.job_id,
            JobStatus.COMPLETED,
            result="Expert analysis complete"
        )

        result = await srv.call_tool("glm_get_job_result", {
            "job_id": job.job_id
        })

        assert "isError" not in result
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "completed"
        assert response_data["result"] == "Expert analysis complete"

    async def test_get_job_result_failed_job(self, mock_args, mock_logger):
        """get_job_result returns error for failed job."""
        srv = self._server(mock_args, mock_logger)

        # Create and fail a job
        job = await srv.job_manager.create_job(
            expert="architect",
            task="test task",
            mode="advisory",
            context="",
            files=[]
        )
        from job_manager import JobStatus
        await srv.job_manager.update_job(
            job.job_id,
            JobStatus.FAILED,
            error="Something went wrong"
        )

        result = await srv.call_tool("glm_get_job_result", {
            "job_id": job.job_id
        })

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "failed"
        assert "Something went wrong" in response_data["error"]

    async def test_get_job_result_long_poll_completed(self, mock_args, mock_logger):
        """wait=true returns completed once job finishes."""
        srv = self._server(mock_args, mock_logger)

        job = await srv.job_manager.create_job(
            expert="architect",
            task="test task",
            mode="advisory",
            context="",
            files=[]
        )
        from job_manager import JobStatus
        # Complete the job before calling (simulates fast completion)
        await srv.job_manager.update_job(
            job.job_id,
            JobStatus.COMPLETED,
            result="Done"
        )

        result = await srv.call_tool("glm_get_job_result", {
            "job_id": job.job_id,
            "wait": True,
            "timeout": 5
        })

        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "completed"
        assert response_data["result"] == "Done"

    async def test_get_job_result_long_poll_timeout(self, mock_args, mock_logger):
        """wait=true returns current status when timeout expires."""
        srv = self._server(mock_args, mock_logger)

        job = await srv.job_manager.create_job(
            expert="architect",
            task="test task",
            mode="advisory",
            context="",
            files=[]
        )
        # Job stays pending — timeout should fire quickly

        result = await srv.call_tool("glm_get_job_result", {
            "job_id": job.job_id,
            "wait": True,
            "timeout": 1
        })

        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "pending"

    async def test_get_job_result_no_wait(self, mock_args, mock_logger):
        """wait=false returns immediately without blocking."""
        srv = self._server(mock_args, mock_logger)

        job = await srv.job_manager.create_job(
            expert="architect",
            task="test task",
            mode="advisory",
            context="",
            files=[]
        )

        result = await srv.call_tool("glm_get_job_result", {
            "job_id": job.job_id,
            "wait": False
        })

        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "pending"


# ============================================================================
# CACHE & MEMORY INTEGRATION
# ============================================================================

class TestCacheIntegration:

    def _server(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        srv.provider = AsyncMock()
        return srv

    async def test_call_expert_caches_response(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="cached reply", raw={}, model="m", tokens_used=50)
        )

        # First call — provider called
        result1 = await srv.call_expert("architect", "design X")
        assert srv.provider.call.call_count == 1
        assert result1 == "cached reply"

        # Second call — served from cache, provider NOT called
        result2 = await srv.call_expert("architect", "design X")
        assert srv.provider.call.call_count == 1  # Still 1
        assert result2 == "cached reply"

    async def test_call_expert_different_context_misses_cache(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="reply", raw={}, model="m")
        )

        await srv.call_expert("architect", "task", context="ctx1")
        await srv.call_expert("architect", "task", context="ctx2")
        assert srv.provider.call.call_count == 2

    async def test_call_expert_records_miss_stat(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="reply", raw={}, model="m")
        )

        await srv.call_expert("architect", "task")
        stats = srv.response_cache.get_stats(hours=1)
        assert stats["events"].get("miss", {}).get("count", 0) == 1

    async def test_call_expert_records_hit_stat(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="reply", raw={}, model="m", tokens_used=100)
        )

        await srv.call_expert("architect", "task")
        await srv.call_expert("architect", "task")  # Cache hit
        stats = srv.response_cache.get_stats(hours=1)
        assert stats["events"].get("hit", {}).get("count", 0) == 1

    async def test_memory_injection_with_working_dir(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="reply", raw={}, model="m")
        )

        # Pre-populate memory
        from expert_memory import project_id_from_dir
        pid = project_id_from_dir("/my/project")
        srv.expert_memory.append(pid, "architect", "Always use dependency injection")

        await srv.call_expert("architect", "new task", working_dir="/my/project")

        # Verify the prompt includes the memory
        call_args = srv.provider.call.call_args
        user_prompt = call_args.kwargs.get("user_prompt") or call_args.args[1]
        assert "PRIOR LEARNINGS" in user_prompt
        assert "dependency injection" in user_prompt

    async def test_learning_extraction_after_call(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(
                text="Analysis complete.\nRecommendation: Use event-driven architecture for scalability.",
                raw={}, model="m",
            )
        )

        from expert_memory import project_id_from_dir
        await srv.call_expert("architect", "design system", working_dir="/my/project")

        pid = project_id_from_dir("/my/project")
        content = srv.expert_memory.load(pid, "architect")
        assert "event-driven architecture" in content


class TestCacheStatsTool:

    def _server(self, mock_args, mock_logger):
        srv = LLMDelegatorMCPServer(mock_args, mock_logger)
        srv.provider = AsyncMock()
        return srv

    async def test_cache_stats_tool_returns_report(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        result = await srv.call_tool("glm_cache_stats", {"action": "stats"})
        data = json.loads(result["content"][0]["text"])
        assert "prompt_cache" in data
        assert "response_cache" in data
        assert "expert_memory" in data

    async def test_cache_stats_invalidate_expert(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        srv.provider.call = AsyncMock(
            return_value=ProviderResponse(text="resp", raw={}, model="m")
        )

        # Populate cache
        await srv.call_expert("architect", "task1")

        # Invalidate
        result = await srv.call_tool("glm_cache_stats", {
            "action": "invalidate_expert",
            "expert": "architect"
        })
        data = json.loads(result["content"][0]["text"])
        assert data["entries_removed"] == 1

    async def test_cache_stats_invalidate_missing_expert(self, mock_args, mock_logger):
        srv = self._server(mock_args, mock_logger)
        result = await srv.call_tool("glm_cache_stats", {
            "action": "invalidate_expert"
        })
        assert result["isError"] is True

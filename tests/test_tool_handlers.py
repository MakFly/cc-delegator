"""Tests for tool_handlers.py — isolated handler tests with mock ServerServices."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tool_handlers import (
    ServerServices,
    handle_enhance_prompt,
    handle_validate_prompt,
    handle_route,
    handle_workflow,
    handle_get_job_result,
    handle_cache_stats,
    handle_expert_call,
    UTILITY_HANDLERS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_svc(**overrides) -> ServerServices:
    """Build a mock ServerServices."""
    defaults = dict(
        provider=AsyncMock(),
        enhancer=AsyncMock(),
        guard=MagicMock(),
        compressor=AsyncMock(),
        job_manager=AsyncMock(),
        response_cache=MagicMock(),
        expert_memory=MagicMock(),
        cache_metrics=MagicMock(),
        claude_bridge=MagicMock(),
        logger=logging.getLogger("test-handlers"),
        backend_config=MagicMock(),
        background_tasks=set(),
        call_expert=AsyncMock(return_value="expert reply"),
        spawn_background_job=AsyncMock(),
    )
    defaults.update(overrides)
    return ServerServices(**defaults)


# ---------------------------------------------------------------------------
# handle_enhance_prompt
# ---------------------------------------------------------------------------

class TestHandleEnhancePrompt:

    async def test_success(self):
        from prompt_enhancer import EnhancedPrompt
        enhanced = EnhancedPrompt(
            original_task="raw", enhanced_task="better", added_context="ctx",
            suggestions=["s1"], confidence=0.9
        )
        svc = _make_svc(enhancer=AsyncMock(enhance=AsyncMock(return_value=enhanced)))
        result = await handle_enhance_prompt({"task": "raw"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["enhanced_task"] == "better"
        assert data["confidence"] == 0.9

    async def test_error(self):
        svc = _make_svc(enhancer=AsyncMock(enhance=AsyncMock(side_effect=Exception("boom"))))
        result = await handle_enhance_prompt({"task": "raw"}, svc)
        assert result["isError"] is True


# ---------------------------------------------------------------------------
# handle_validate_prompt
# ---------------------------------------------------------------------------

class TestHandleValidatePrompt:

    async def test_valid(self):
        from prompt_guard import ValidationResult
        svc = _make_svc()
        svc.guard.validate.return_value = ValidationResult(is_valid=True)
        result = await handle_validate_prompt({"task": "do something useful"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["is_valid"] is True

    async def test_error(self):
        svc = _make_svc()
        svc.guard.validate.side_effect = Exception("fail")
        result = await handle_validate_prompt({"task": "x"}, svc)
        assert result["isError"] is True


# ---------------------------------------------------------------------------
# handle_route
# ---------------------------------------------------------------------------

class TestHandleRoute:

    async def test_security_routing(self):
        svc = _make_svc()
        result = await handle_route({"task": "check security vulnerability"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["recommended_expert"] == "security_analyst"

    async def test_architecture_routing(self):
        svc = _make_svc()
        result = await handle_route({"task": "design the architecture"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["recommended_expert"] == "architect"

    async def test_code_review_routing(self):
        svc = _make_svc()
        result = await handle_route({"task": "review this code"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["recommended_expert"] == "code_reviewer"

    async def test_plan_routing(self):
        svc = _make_svc()
        result = await handle_route({"task": "verify the plan"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["recommended_expert"] == "plan_reviewer"

    async def test_scope_routing(self):
        svc = _make_svc()
        result = await handle_route({"task": "clarify the requirements"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["recommended_expert"] == "scope_analyst"

    async def test_default_routing(self):
        svc = _make_svc()
        result = await handle_route({"task": "do something generic"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["recommended_expert"] == "architect"

    async def test_team_spawn_with_many_files(self):
        svc = _make_svc()
        result = await handle_route({"task": "review", "files": ["a", "b", "c", "d"], "decide_team": True}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["should_spawn_team"] is True


# ---------------------------------------------------------------------------
# handle_workflow
# ---------------------------------------------------------------------------

class TestHandleWorkflow:

    async def test_start(self):
        svc = _make_svc()
        result = await handle_workflow({"action": "start", "plan": {"steps": []}}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["message"] == "Workflow started"
        assert data["plan_received"] is True

    async def test_status(self):
        svc = _make_svc()
        result = await handle_workflow({"action": "status"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert "No active workflow" in data["message"]

    async def test_complete_test_passed(self):
        svc = _make_svc()
        result = await handle_workflow({"action": "complete_test", "passed": True}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["passed"] is True

    async def test_complete_review(self):
        svc = _make_svc()
        result = await handle_workflow({"action": "complete_review", "verdict": "APPROVE", "issues": []}, svc)
        data = json.loads(result["content"][0]["text"])
        assert "APPROVE" in data["message"]

    async def test_unknown_action(self):
        svc = _make_svc()
        result = await handle_workflow({"action": "bogus"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert "Unknown action" in data["message"]


# ---------------------------------------------------------------------------
# handle_get_job_result
# ---------------------------------------------------------------------------

class TestHandleGetJobResult:

    async def test_missing_job_id(self):
        svc = _make_svc()
        result = await handle_get_job_result({}, svc)
        assert result["isError"] is True
        data = json.loads(result["content"][0]["text"])
        assert data["error"] == "job_id_required"

    async def test_job_not_found(self):
        svc = _make_svc()
        svc.job_manager.wait_for_completion = AsyncMock(return_value=None)
        result = await handle_get_job_result({"job_id": "nope"}, svc)
        assert result["isError"] is True
        data = json.loads(result["content"][0]["text"])
        assert data["error"] == "job_not_found"

    async def test_completed_job(self):
        from job_manager import JobStatus
        job = MagicMock()
        job.job_id = "job_123"
        job.status = JobStatus.COMPLETED
        job.result = "done"
        job._age_seconds.return_value = 5.0
        svc = _make_svc()
        svc.job_manager.wait_for_completion = AsyncMock(return_value=job)
        result = await handle_get_job_result({"job_id": "job_123"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "completed"
        assert data["result"] == "done"

    async def test_failed_job(self):
        from job_manager import JobStatus
        job = MagicMock()
        job.job_id = "job_fail"
        job.status = JobStatus.FAILED
        job.error = "something broke"
        job._age_seconds.return_value = 2.0
        svc = _make_svc()
        svc.job_manager.wait_for_completion = AsyncMock(return_value=job)
        result = await handle_get_job_result({"job_id": "job_fail"}, svc)
        assert result["isError"] is True
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "failed"

    async def test_pending_job(self):
        from job_manager import JobStatus
        job = MagicMock()
        job.job_id = "job_p"
        job.status = JobStatus.PENDING
        job._age_seconds.return_value = 1.0
        svc = _make_svc()
        svc.job_manager.wait_for_completion = AsyncMock(return_value=job)
        result = await handle_get_job_result({"job_id": "job_p"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "pending"

    async def test_no_wait(self):
        from job_manager import JobStatus
        job = MagicMock()
        job.job_id = "job_nw"
        job.status = JobStatus.PROCESSING
        job._age_seconds.return_value = 3.0
        svc = _make_svc()
        svc.job_manager.get_job = AsyncMock(return_value=job)
        result = await handle_get_job_result({"job_id": "job_nw", "wait": False}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "processing"

    async def test_timeout_job(self):
        from job_manager import JobStatus
        job = MagicMock()
        job.job_id = "job_to"
        job.status = JobStatus.TIMEOUT
        job.error = "Timed out"
        job._age_seconds.return_value = 300.0
        svc = _make_svc()
        svc.job_manager.wait_for_completion = AsyncMock(return_value=job)
        result = await handle_get_job_result({"job_id": "job_to"}, svc)
        assert result["isError"] is True
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "timeout"


# ---------------------------------------------------------------------------
# handle_cache_stats
# ---------------------------------------------------------------------------

class TestHandleCacheStats:

    async def test_stats(self):
        svc = _make_svc()
        svc.cache_metrics.get_report.return_value = {"prompt_cache": {}, "response_cache": {}, "expert_memory": {}}
        result = await handle_cache_stats({"action": "stats"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert "prompt_cache" in data

    async def test_invalidate_missing_expert(self):
        svc = _make_svc()
        result = await handle_cache_stats({"action": "invalidate_expert"}, svc)
        assert result["isError"] is True

    async def test_invalidate_expert(self):
        svc = _make_svc()
        svc.response_cache.invalidate_expert.return_value = 3
        result = await handle_cache_stats({"action": "invalidate_expert", "expert": "architect"}, svc)
        data = json.loads(result["content"][0]["text"])
        assert data["entries_removed"] == 3


# ---------------------------------------------------------------------------
# handle_expert_call
# ---------------------------------------------------------------------------

class TestHandleExpertCall:

    def _personas(self):
        from persona_loader import Persona
        return {"architect": Persona(key="architect", name="Architect", prompt="# Architect\n")}

    async def test_direct_mode_success(self):
        svc = _make_svc()
        result = await handle_expert_call("architect", {"task": "design"}, svc, self._personas())
        assert result["content"][0]["text"] == "expert reply"

    async def test_direct_mode_error(self):
        svc = _make_svc(call_expert=AsyncMock(side_effect=Exception("boom")))
        result = await handle_expert_call("architect", {"task": "design"}, svc, self._personas())
        assert result["isError"] is True

    async def test_background_mode_large_context(self):
        from context_compressor import CompressionResult
        svc = _make_svc()
        # Compressor passthrough so raw context reaches background routing
        async def _passthrough(ctx, target=None):
            return ctx, CompressionResult(len(ctx), len(ctx), "none", 0)
        svc.compressor.compress = _passthrough
        svc.job_manager.create_job = AsyncMock(return_value=MagicMock(job_id="job_bg"))
        result = await handle_expert_call(
            "architect",
            {"task": "x", "context": "y" * 13000},
            svc, self._personas()
        )
        data = json.loads(result["content"][0]["text"])
        assert data["job_id"] == "job_bg"
        assert data["status"] == "pending"

    async def test_background_mode_many_files(self):
        svc = _make_svc()
        svc.job_manager.create_job = AsyncMock(return_value=MagicMock(job_id="job_files"))
        result = await handle_expert_call(
            "architect",
            {"task": "review", "files": [f"f{i}" for i in range(11)]},
            svc, self._personas()
        )
        data = json.loads(result["content"][0]["text"])
        assert "job_id" in data


# ---------------------------------------------------------------------------
# UTILITY_HANDLERS map
# ---------------------------------------------------------------------------

class TestUtilityHandlersMap:

    def test_has_six_entries(self):
        assert len(UTILITY_HANDLERS) == 6

    def test_expected_keys(self):
        expected = {"enhance_prompt", "validate_prompt", "route", "workflow", "get_job_result", "cache_stats"}
        assert set(UTILITY_HANDLERS.keys()) == expected

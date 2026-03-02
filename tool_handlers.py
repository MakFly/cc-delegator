"""Tool handler functions for GLM Delegator MCP tools.

All handlers receive a `ServerServices` dataclass for dependency injection,
avoiding circular imports with server.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from context_compressor import ContextCompressor
from prompt_enhancer import EnhancedPrompt
from prompt_guard import ValidationResult

if TYPE_CHECKING:
    from cache_metrics import CacheMetrics
    from cache_store import ResponseCache
    from claude_memory_bridge import ClaudeMemoryBridge
    from expert_memory import ExpertMemory
    from job_manager import Job, JobManager
    from persona_loader import Persona
    from prompt_enhancer import PromptEnhancer
    from prompt_guard import PromptQualityGuard
    from providers import BackendConfig, BaseProvider

# Timeout protection constants (mirrored from server)
MAX_CONTEXT_CHARS = 15000
MAX_FILES_COUNT = 10
BACKGROUND_MODE_THRESHOLD = 12000


@dataclass
class ServerServices:
    """Dependency container injected into handlers — no import of server module."""
    provider: BaseProvider
    enhancer: PromptEnhancer
    guard: PromptQualityGuard
    compressor: ContextCompressor
    job_manager: JobManager
    response_cache: ResponseCache
    expert_memory: ExpertMemory
    cache_metrics: CacheMetrics
    claude_bridge: ClaudeMemoryBridge
    logger: logging.Logger
    backend_config: BackendConfig
    background_tasks: set
    call_expert: Callable  # async (expert, task, mode, context, files, working_dir) -> str
    spawn_background_job: Callable  # async (Job) -> None


# =============================================================================
# Utility handlers
# =============================================================================


async def handle_enhance_prompt(args: dict, svc: ServerServices) -> dict:
    """Handle glm_enhance_prompt tool."""
    task = args.get("task", "")
    context = args.get("context", "")
    target_expert = args.get("target_expert", "")
    files = args.get("files", [])

    try:
        result: EnhancedPrompt = await svc.enhancer.enhance(
            task, context, target_expert, files
        )
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "original_task": result.original_task,
                    "enhanced_task": result.enhanced_task,
                    "added_context": result.added_context,
                    "suggestions": result.suggestions,
                    "confidence": result.confidence,
                }, indent=2),
            }]
        }
    except Exception as e:
        svc.logger.error(f"Enhance prompt failed: {e}")
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "error": str(e),
                    "original_task": task,
                    "enhanced_task": task,
                    "confidence": 0.0,
                }),
            }],
            "isError": True,
        }


async def handle_validate_prompt(args: dict, svc: ServerServices) -> dict:
    """Handle glm_validate_prompt tool."""
    task = args.get("task", "")
    context = args.get("context", "")
    files = args.get("files", [])
    working_dir = args.get("working_dir", "") or None

    try:
        result: ValidationResult = svc.guard.validate(task, context, files, working_dir)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "is_valid": result.is_valid,
                    "warnings": result.warnings,
                    "errors": result.errors,
                    "suggestions": result.suggestions,
                }, indent=2),
            }]
        }
    except Exception as e:
        svc.logger.error(f"Validate prompt failed: {e}")
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e), "is_valid": False}),
            }],
            "isError": True,
        }


async def handle_route(args: dict, svc: ServerServices) -> dict:
    """Handle glm_route tool."""
    task = args.get("task", "")
    files = args.get("files", [])
    decide_team = args.get("decide_team", True)

    routing: dict[str, Any] = {
        "task": task,
        "recommended_expert": None,
        "reasoning": "",
        "alternative_experts": [],
        "should_spawn_team": False,
    }

    task_lower = task.lower()

    if any(kw in task_lower for kw in ["security", "vulnerability", "exploit", "auth", "credential", "injection", "xss"]):
        routing["recommended_expert"] = "security_analyst"
        routing["reasoning"] = "Task involves security concerns"
    elif any(kw in task_lower for kw in ["architecture", "design", "structure", "tradeoff", "pattern", "scalab"]):
        routing["recommended_expert"] = "architect"
        routing["reasoning"] = "Task involves architectural decisions"
    elif any(kw in task_lower for kw in ["review", "check", "bug", "issue", "quality", "smell"]):
        routing["recommended_expert"] = "code_reviewer"
        routing["reasoning"] = "Task involves code review"
    elif any(kw in task_lower for kw in ["plan", "verify", "complete", "gap"]):
        routing["recommended_expert"] = "plan_reviewer"
        routing["reasoning"] = "Task involves plan validation"
    elif any(kw in task_lower for kw in ["scope", "requirement", "ambigui", "unclear", "clarify"]):
        routing["recommended_expert"] = "scope_analyst"
        routing["reasoning"] = "Task involves scope clarification"
    else:
        routing["recommended_expert"] = "architect"
        routing["reasoning"] = "Default to architect for general tasks"

    all_experts = ["architect", "code_reviewer", "security_analyst", "plan_reviewer", "scope_analyst"]
    routing["alternative_experts"] = [e for e in all_experts if e != routing["recommended_expert"]]

    if decide_team:
        routing["should_spawn_team"] = (
            len(files) > 3
            or any(kw in task_lower for kw in ["parallel", "multiple", "team", "comprehensive"])
        )

    return {"content": [{"type": "text", "text": json.dumps(routing, indent=2)}]}


async def handle_workflow(args: dict, svc: ServerServices) -> dict:
    """Handle glm_workflow tool."""
    action = args.get("action", "status")

    response: dict[str, Any] = {
        "action": action,
        "status": "acknowledged",
        "warning": "Workflow engine is experimental - state is not persisted between calls",
        "message": "",
    }

    if action == "start":
        plan = args.get("plan", {})
        response["message"] = "Workflow started"
        response["plan_received"] = bool(plan)
    elif action == "status":
        response["message"] = "No active workflow"
    elif action == "complete_execution":
        response["message"] = f"Execution completed: {args.get('result', 'No result')}"
    elif action == "complete_review":
        verdict = args.get("verdict", "UNKNOWN")
        issues = args.get("issues", [])
        response["message"] = f"Review completed with verdict: {verdict}"
        response["issues_count"] = len(issues)
    elif action == "complete_test":
        passed = args.get("passed", False)
        response["message"] = f"Tests {'passed' if passed else 'failed'}"
        response["passed"] = passed
    elif action == "complete_fix":
        response["message"] = f"Fix applied: {args.get('description', 'No description')}"
    elif action == "complete_report":
        response["message"] = "Workflow completed"
        response["report"] = args.get("report", "")
    else:
        response["message"] = f"Unknown action: {action}"

    return {"content": [{"type": "text", "text": json.dumps(response, indent=2)}]}


async def handle_get_job_result(args: dict, svc: ServerServices) -> dict:
    """Handle glm_get_job_result tool."""
    from job_manager import JobStatus

    job_id = args.get("job_id", "").strip()
    wait = args.get("wait", True)
    timeout = args.get("timeout", 55)
    timeout = max(1, min(55, int(timeout)))

    if not job_id:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": "job_id_required", "message": "job_id parameter is required"}, indent=2)}],
            "isError": True,
        }

    if wait:
        job = await svc.job_manager.wait_for_completion(job_id, timeout=timeout)
    else:
        job = await svc.job_manager.get_job(job_id)

    if not job:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": "job_not_found", "message": "Job expired or invalid job_id", "job_id": job_id}, indent=2)}],
            "isError": True,
        }

    age = int(job._age_seconds())

    if job.status == JobStatus.PENDING:
        return {"content": [{"type": "text", "text": json.dumps({"job_id": job.job_id, "status": "pending", "message": "Queued, waiting...", "age_seconds": age}, indent=2)}]}
    elif job.status == JobStatus.PROCESSING:
        return {"content": [{"type": "text", "text": json.dumps({"job_id": job.job_id, "status": "processing", "message": "In progress...", "age_seconds": age}, indent=2)}]}
    elif job.status == JobStatus.COMPLETED:
        return {"content": [{"type": "text", "text": json.dumps({"job_id": job.job_id, "status": "completed", "result": job.result, "age_seconds": age}, indent=2)}]}
    elif job.status == JobStatus.FAILED:
        return {
            "content": [{"type": "text", "text": json.dumps({"job_id": job.job_id, "status": "failed", "error": job.error or "Unknown error", "age_seconds": age}, indent=2)}],
            "isError": True,
        }
    elif job.status == JobStatus.TIMEOUT:
        return {
            "content": [{"type": "text", "text": json.dumps({"job_id": job.job_id, "status": "timeout", "error": job.error or "Timed out after 300s", "age_seconds": age}, indent=2)}],
            "isError": True,
        }
    else:
        return {"content": [{"type": "text", "text": json.dumps({"job_id": job.job_id, "status": job.status.value, "message": "Unknown status"}, indent=2)}]}


async def handle_cache_stats(args: dict, svc: ServerServices) -> dict:
    """Handle glm_cache_stats tool."""
    action = args.get("action", "stats")

    if action == "invalidate_expert":
        expert = args.get("expert", "").strip()
        if not expert:
            return {
                "content": [{"type": "text", "text": json.dumps({"error": "expert_required", "message": "Expert name required for invalidation"}, indent=2)}],
                "isError": True,
            }
        removed = svc.response_cache.invalidate_expert(expert)
        return {"content": [{"type": "text", "text": json.dumps({"action": "invalidate_expert", "expert": expert, "entries_removed": removed}, indent=2)}]}

    hours = args.get("hours", 24)
    report = svc.cache_metrics.get_report(hours=hours)
    return {"content": [{"type": "text", "text": json.dumps(report, indent=2)}]}


# =============================================================================
# Dispatcher map
# =============================================================================

UTILITY_HANDLERS: dict[str, Callable] = {
    "enhance_prompt": handle_enhance_prompt,
    "validate_prompt": handle_validate_prompt,
    "route": handle_route,
    "workflow": handle_workflow,
    "get_job_result": handle_get_job_result,
    "cache_stats": handle_cache_stats,
}


# =============================================================================
# Expert call handler
# =============================================================================


async def handle_expert_call(
    tool_name: str,
    arguments: dict,
    svc: ServerServices,
    personas: dict[str, Persona],
) -> dict:
    """Route expert call: compress -> background or direct -> return MCP response dict."""
    task = arguments.get("task", "")
    mode = arguments.get("mode", "advisory")
    if mode not in ("advisory", "implementation"):
        mode = "advisory"
    context = arguments.get("context", "")
    files = arguments.get("files", [])
    working_dir = arguments.get("working_dir", "")
    enhance = arguments.get("enhance", False)

    # Context compression
    if len(context) > ContextCompressor.TARGET_LENGTH:
        context, compression = await svc.compressor.compress(context)
        svc.logger.info(
            f"Context compressed: {compression.original_length} -> "
            f"{compression.compressed_length} ({compression.method})"
        )

    total_chars = len(task) + len(context)
    files_count = len(files) if files else 0

    # Background mode routing
    use_background = total_chars >= BACKGROUND_MODE_THRESHOLD
    if files_count > MAX_FILES_COUNT:
        use_background = True

    if use_background:
        try:
            job = await svc.job_manager.create_job(
                expert=tool_name, task=task, mode=mode,
                context=context, files=files,
                metadata={"enhance": enhance, "working_dir": working_dir},
            )
            bg_task = asyncio.create_task(
                svc.spawn_background_job(job), name=f"bg-job-{job.job_id}"
            )
            svc.background_tasks.add(bg_task)
            bg_task.add_done_callback(svc.background_tasks.discard)

            svc.logger.info(f"Background job created: {job.job_id} (context={total_chars} chars)")
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "job_id": job.job_id, "status": "pending",
                        "message": "Job queued. Use glm_get_job_result to retrieve result.",
                        "context_size": total_chars,
                    }, indent=2),
                }]
            }
        except RuntimeError as e:
            return {
                "content": [{"type": "text", "text": json.dumps({"error": "max_jobs_reached", "message": str(e)}, indent=2)}],
                "isError": True,
            }

    # Timeout protection for direct calls
    if files_count > MAX_FILES_COUNT:
        return {
            "content": [{"type": "text", "text": json.dumps({
                "error": "context_too_large",
                "message": f"Too many files ({files_count} > {MAX_FILES_COUNT}) and background mode unavailable.",
                "suggestions": [f"Reduce files to max {MAX_FILES_COUNT}", "Include file contents in 'context'", "Split into smaller requests"],
                "current_size": {"files_count": files_count, "task_chars": len(task), "context_chars": len(context)},
                "limits": {"max_files": MAX_FILES_COUNT, "max_context_chars": MAX_CONTEXT_CHARS},
            }, indent=2)}],
            "isError": True,
        }

    if total_chars > MAX_CONTEXT_CHARS:
        return {
            "content": [{"type": "text", "text": json.dumps({
                "error": "context_too_large",
                "message": f"Context too large ({total_chars} > {MAX_CONTEXT_CHARS} chars) and background mode unavailable.",
                "suggestions": [f"Reduce context to max {MAX_CONTEXT_CHARS} chars", "Summarize instead of full file contents", "Split into smaller requests"],
                "current_size": {"files_count": files_count, "task_chars": len(task), "context_chars": len(context), "total_chars": total_chars},
                "limits": {"max_files": MAX_FILES_COUNT, "max_context_chars": MAX_CONTEXT_CHARS},
            }, indent=2)}],
            "isError": True,
        }

    if total_chars > MAX_CONTEXT_CHARS * 0.8:
        svc.logger.warning(f"Context size ({total_chars} chars) approaching limit ({MAX_CONTEXT_CHARS}).")

    # Direct mode
    try:
        if enhance:
            svc.logger.info(f"Auto-enhancing prompt for expert: {tool_name}")
            enhanced: EnhancedPrompt = await svc.enhancer.enhance(task, context, tool_name, files)
            task = enhanced.enhanced_task
            if enhanced.added_context:
                context = f"{context}\n\n{enhanced.added_context}".strip()
            svc.logger.info(f"Prompt enhanced (confidence: {enhanced.confidence})")

        result = await svc.call_expert(tool_name, task, mode, context, files, working_dir)
        return {"content": [{"type": "text", "text": result}]}
    except Exception as e:
        svc.logger.error(f"Tool call failed: {e}")
        return {
            "content": [{"type": "text", "text": "Expert delegation failed. Check server logs for details."}],
            "isError": True,
        }

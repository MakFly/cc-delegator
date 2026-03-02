"""MCP tool schema definitions for GLM Delegator."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from persona_loader import Persona

# =============================================================================
# Shared parameter definitions (defined ONCE)
# =============================================================================

PARAM_TASK = {"type": "string", "description": "The task or question for the expert"}
PARAM_MODE = {
    "type": "string",
    "enum": ["advisory", "implementation"],
    "description": "Advisory = analysis only, Implementation = make changes",
    "default": "advisory",
}
PARAM_CONTEXT = {"type": "string", "description": "Additional context about the codebase", "default": ""}
PARAM_FILES = {
    "type": "array",
    "items": {"type": "string"},
    "description": "List of file paths included in context (metadata only - include actual content in the context parameter)",
    "default": [],
}
PARAM_WORKING_DIR = {
    "type": "string",
    "description": "Working directory for project identification (enables expert memory)",
    "default": "",
}
PARAM_ENHANCE = {
    "type": "boolean",
    "description": "Auto-enhance prompt before sending to expert (+1 LLM call)",
    "default": False,
}

EXPERT_SCHEMA = {
    "type": "object",
    "properties": {
        "task": PARAM_TASK,
        "mode": PARAM_MODE,
        "context": PARAM_CONTEXT,
        "files": PARAM_FILES,
        "enhance": PARAM_ENHANCE,
        "working_dir": PARAM_WORKING_DIR,
    },
    "required": ["task"],
}

# =============================================================================
# Utility tool schemas
# =============================================================================

UTILITY_TOOLS: list[dict] = [
    {
        "name": "glm_enhance_prompt",
        "description": "Use LLM to enhance a prompt before sending to expert. Improves clarity, structure, and completeness.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Original task to enhance"},
                "context": {"type": "string", "description": "Additional context", "default": ""},
                "target_expert": {"type": "string", "description": "Which expert will receive this", "default": ""},
                "files": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["task"],
        },
    },
    {
        "name": "glm_validate_prompt",
        "description": "Validate a prompt using static rules (no LLM call). Checks file existence, hallucination signals.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task to validate"},
                "context": {"type": "string", "default": ""},
                "files": {"type": "array", "items": {"type": "string"}, "default": []},
                "working_dir": {"type": "string", "default": ""},
            },
            "required": ["task"],
        },
    },
    {
        "name": "glm_route",
        "description": "Intelligently route a task to the best available tool (expert/skill/team) using hybrid keyword + semantic matching",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The task to route"},
                "context": {"type": "string", "description": "Additional context about the codebase", "default": ""},
                "files": {"type": "array", "items": {"type": "string"}, "description": "List of files involved in the task", "default": []},
                "decide_team": {"type": "boolean", "description": "Whether to include team spawning decision", "default": True},
            },
            "required": ["task"],
        },
    },
    {
        "name": "glm_workflow",
        "description": "Execute automated workflow: Code \u2192 Review \u2192 Test \u2192 Fix \u2192 Report with state machine management",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "status", "pause", "resume", "complete_execution", "complete_review", "complete_test", "complete_fix", "complete_report"],
                    "description": "Workflow action to perform",
                    "default": "status",
                },
                "plan": {"type": "object", "description": "Validated plan object (required for 'start' action)"},
                "routing_decision": {"type": "object", "description": "Output from glm_route (optional for 'start')"},
                "result": {"type": "string", "description": "Execution result description"},
                "verdict": {"type": "string", "description": "Review verdict (for complete_review): APPROVE, REQUEST_CHANGES, or REJECT"},
                "issues": {"type": "array", "items": {"type": "string"}, "description": "List of issues found (for complete_review)"},
                "passed": {"type": "boolean", "description": "Whether tests passed (for complete_test)"},
                "summary": {"type": "string", "description": "Test summary or execution result"},
                "description": {"type": "string", "description": "Fix description (for complete_fix)"},
                "report": {"type": "string", "description": "Final report (for complete_report)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "glm_cache_stats",
        "description": "Get caching and memory system statistics",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "Time window in hours for stats aggregation", "default": 24},
                "action": {
                    "type": "string",
                    "enum": ["stats", "invalidate_expert"],
                    "description": "Action to perform: get stats or invalidate an expert's cache",
                    "default": "stats",
                },
                "expert": {"type": "string", "description": "Expert name (required for invalidate_expert action)"},
            },
        },
    },
    {
        "name": "glm_get_job_result",
        "description": "Retrieve the result of a background job. Blocks until job completes (long-polling).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID returned by glm_{expert} when job was queued"},
                "wait": {"type": "boolean", "default": True, "description": "Block until job completes (long-polling). Default: true"},
                "timeout": {"type": "integer", "default": 55, "description": "Max wait seconds (1-55). Default: 55"},
            },
            "required": ["job_id"],
        },
    },
]


def build_tool_list(personas: dict[str, "Persona"], model_display: str) -> list[dict]:
    """Build MCP tool list: 1 tool per persona + utility tools."""
    tools = []
    for key in sorted(personas.keys()):
        persona = personas[key]
        expert_name = key.replace("_", " ").title()
        tools.append({
            "name": f"glm_{key}",
            "description": f"Delegate to the {expert_name} expert ({model_display})",
            "inputSchema": EXPERT_SCHEMA,
        })
    tools.extend(UTILITY_TOOLS)
    return tools

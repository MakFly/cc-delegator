# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Claude Code plugin that provides GLM (4.7/5) (via Z.AI API) as specialized expert subagents. Five domain experts that can advise OR implement: Architect, Plan Reviewer, Scope Analyst, Code Reviewer (EN/FR/CN), and Security Analyst.

## Development Commands

```bash
# Test plugin locally (loads from working directory)
claude --plugin-dir /path/to/glm-delegator

# Run tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ -v --cov=. --cov-report=term-missing

# Run setup to test installation flow
/glm-delegator:setup

# Run uninstall to test removal flow
/glm-delegator:uninstall
```

## Architecture

### Module Map

```
glm_mcp_server.py  ─── MCP JSON-RPC protocol (stdin/stdout), thin entrypoint
    ├── cli.py          ─── CLI argument parsing + logging setup
    └── server.py       ─── DelegatorServer: lifecycle, expert calls, background jobs
        ├── persona_loader.py   ─── Load expert prompts from prompts/personas/*.md
        ├── tool_registry.py    ─── MCP tool schema definitions
        ├── tool_handlers.py    ─── Tool handler functions + ServerServices DI
        ├── providers.py        ─── Multi-provider abstraction (OpenAI, Anthropic)
        ├── cache_store.py      ─── SQLite response cache with TTL
        ├── expert_memory.py    ─── Per-project expert learnings
        ├── claude_memory_bridge.py ─── Bidirectional Claude Code ↔ GLM memory
        ├── context_compressor.py   ─── Smart context compression
        ├── prompt_enhancer.py  ─── LLM-based prompt improvement
        ├── prompt_guard.py     ─── Static prompt validation
        ├── job_manager.py      ─── Async background job queue
        └── cache_metrics.py    ─── Unified metrics aggregation
```

### Import Graph (no circular deps)

```
glm_mcp_server.py  →  cli.py, server.py
server.py          →  persona_loader, tool_registry, tool_handlers, providers, job_manager, cache_store, expert_memory, claude_memory_bridge, context_compressor, prompt_enhancer, prompt_guard, cache_metrics
tool_registry.py   →  persona_loader (Persona type only)
tool_handlers.py   →  prompt_enhancer, prompt_guard, context_compressor, job_manager, cache_store, cache_metrics
                      (NO import from server.py — circular import avoided via ServerServices DI)
persona_loader.py  →  pathlib, re (stdlib only)
cli.py             →  argparse, logging (stdlib only)
```

### Orchestration Flow

Claude acts as orchestrator—delegates to specialized GLM experts based on task type. Delegation is **stateless**: each MCP call is independent (no memory between calls).

```
User Request → Claude Code → [Match trigger → Select expert]
                                    ↓
              ┌─────────────────────┼─────────────────────┐
              ↓                     ↓                     ↓
         Architect            Code Reviewer        Security Analyst
              ↓                     ↓                     ↓
    [Advisory (read-only) OR Implementation (workspace-write)]
              ↓                     ↓                     ↓
    Claude synthesizes response ←──┴──────────────────────┘
```

### How Delegation Works

1. **Match trigger** - Check `rules/glm-delegator.md` for semantic patterns
2. **Select expert** - Choose based on task type
3. **Build delegation prompt** - Include task, context, mode
4. **Call MCP tool** - `mcp__glm-delegator__glm_{expert}`
5. **Synthesize response** - Never show raw output; interpret and verify

### The 5 GLM Experts

| Expert | MCP Tool | Specialty | Triggers |
|--------|----------|-----------|----------|
| **Architect** | `glm_architect` | System design, tradeoffs | "how should I structure", "tradeoffs of", design questions |
| **Plan Reviewer** | `glm_plan_reviewer` | Plan validation | "review this plan", before significant work |
| **Scope Analyst** | `glm_scope_analyst` | Requirements analysis | "clarify the scope", vague requirements |
| **Code Reviewer** | `glm_code_reviewer` | Code quality, bugs (EN/FR/CN) | "review this code", "find issues" |
| **Security Analyst** | `glm_security_analyst` | Vulnerabilities | "is this secure", "harden this" |

Every expert can operate in **advisory** (read-only) or **implementation** (workspace-write) mode based on the task.

### Adding a New Expert

1. Create `prompts/personas/{name}.md` starting with `# Expert Name`
2. Restart server — persona auto-discovered, MCP tool registered as `glm_{name}`

### Adding a Utility Tool

1. Add handler function in `tool_handlers.py`
2. Add schema dict in `tool_registry.py` UTILITY_TOOLS list
3. Add entry in `tool_handlers.UTILITY_HANDLERS` dict

## Key Design Decisions

1. **Modular architecture** - Server split into `cli.py`, `server.py`, `tool_registry.py`, `tool_handlers.py`, `persona_loader.py`
2. **DI via ServerServices** - `tool_handlers.py` receives dependencies through a dataclass, no circular imports
3. **File-based personas** - Expert prompts in `prompts/personas/*.md`, auto-discovered at startup
4. **Anthropic-compatible API** - Z.AI provides an endpoint compatible with Anthropic's API format
5. **Stateless calls** - Each delegation includes full context (no session management)
6. **Dual mode** - Any expert can advise or implement based on task
7. **Synthesize, don't passthrough** - Claude interprets GLM output, applies judgment
8. **Multilingual** - Code Reviewer supports EN/FR/CN

## When NOT to Delegate

- Simple syntax questions (answer directly)
- First attempt at any fix (try yourself first)
- Trivial file operations
- Research/documentation tasks

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GLM_API_KEY` | Yes* | - | Your Z.AI API key |
| `Z_AI_API_KEY` | Yes* | - | Alternative to GLM_API_KEY |
| `GLM_BASE_URL` | No | `https://api.z.ai/api/anthropic` | Z.AI API endpoint |
| `GLM_MODEL` | No | `glm-5` | GLM model to use (glm-5 with glm-4.7 fallback) |

### MCP Server

The MCP entrypoint is `glm_mcp_server.py` which delegates to `server.py` (DelegatorServer) for business logic.

## Component Relationships

| Component | Purpose | Notes |
|-----------|---------|-------|
| `rules/*.md` | When/how to delegate | Installed to `~/.claude/rules/glm-delegator/` |
| `commands/*.md` | Slash commands | `/setup`, `/uninstall`, `/workflow` |
| `prompts/personas/*.md` | Expert system prompts | Auto-discovered by `persona_loader.py` |
| `prompts/truthfulness_policy.md` | Shared truthfulness policy | Injected into every expert call |
| `glm_mcp_server.py` | MCP JSON-RPC entrypoint | Thin wrapper around `server.py` |
| `server.py` | DelegatorServer class | Core business logic |
| `tool_handlers.py` | Tool handler functions | Uses ServerServices DI |
| `tool_registry.py` | Tool schema definitions | Expert + utility tool schemas |

## Testing

Coverage target: 80% (configured in `pyproject.toml` `fail_under = 80`).

```bash
pytest tests/ -v --cov=. --cov-report=term-missing
```

> Expert prompts adapted from [claude-delegator](https://github.com/jarrodwatts/claude-delegator) and [oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode)

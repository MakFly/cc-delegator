# AGENTS.md — AI Assistant Guide

## Project Overview
MCP plugin providing GLM (glm-5) as specialized expert subagents for Claude Code.

## Module Map
| Module | Responsibility |
|--------|---------------|
| glm_mcp_server.py | MCP JSON-RPC protocol (stdin/stdout) |
| server.py | DelegatorServer lifecycle, expert calls, background jobs |
| tool_registry.py | MCP tool schema definitions |
| tool_handlers.py | Tool handler functions + ServerServices DI |
| persona_loader.py | Load expert prompts from prompts/personas/*.md |
| cli.py | CLI argument parsing + logging setup |
| providers.py | Multi-provider abstraction (OpenAI, Anthropic) |
| cache_store.py | SQLite response cache with TTL |
| expert_memory.py | Per-project expert learnings |
| claude_memory_bridge.py | Bidirectional Claude Code ↔ GLM memory |
| context_compressor.py | Smart context compression |
| prompt_enhancer.py | LLM-based prompt improvement |
| prompt_guard.py | Static prompt validation |
| job_manager.py | Async background job queue |
| cache_metrics.py | Unified metrics aggregation |

## Adding a New Expert
1. Create `prompts/personas/{name}.md` starting with `# Expert Name`
2. Restart server — persona auto-discovered, MCP tool registered as `glm_{name}`

## Adding a Utility Tool
1. Add handler function in `tool_handlers.py`
2. Add schema dict in `tool_registry.py` UTILITY_TOOLS list
3. Add entry in `tool_handlers.UTILITY_HANDLERS` dict

## Testing
```bash
pytest tests/ -v --cov=. --cov-report=term-missing
```
Coverage target: 80% (fail_under in pyproject.toml)

## Configuration
| Env Var | Description |
|---------|-------------|
| GLM_API_KEY | Z.AI API key |
| GLM_MODEL | Model name (default: glm-5) |

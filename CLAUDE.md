# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Claude Code plugin that provides GLM (4.7/5) (via Z.AI API) as specialized expert subagents. Five domain experts that can advise OR implement: Architect, Plan Reviewer, Scope Analyst, Code Reviewer (EN/FR/CN), and Security Analyst.

## Development Commands

```bash
# Test plugin locally (loads from working directory)
claude --plugin-dir /path/to/glm-delegator

# Run setup to test installation flow
/glm-delegator:setup

# Run uninstall to test removal flow
/glm-delegator:uninstall
```

## Architecture

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

1. **Match trigger** - Check `rules/triggers.md` for semantic patterns
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

## Key Design Decisions

1. **Custom MCP server** - GLM doesn't have a native CLI MCP server, so we use a Python server
2. **Anthropic-compatible API** - Z.AI provides an endpoint compatible with Anthropic's API format
3. **Stateless calls** - Each delegation includes full context (no session management)
4. **Dual mode** - Any expert can advise or implement based on task
5. **Synthesize, don't passthrough** - Claude interprets GLM output, applies judgment
6. **Multilingual** - Code Reviewer supports EN/FR/CN

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
| `GLM_MODEL` | No | `glm-4.7` | GLM model to use (glm-4.7 or glm-5) |

### MCP Server

The MCP server is implemented in `glm_mcp_server.py` and uses the Z.AI Anthropic-compatible API to communicate with GLM (4.7/5).

## Component Relationships

| Component | Purpose | Notes |
|-----------|---------|-------|
| `rules/*.md` | When/how to delegate | Installed to `~/.claude/rules/glm-delegator/` |
| `prompts/*.md` | Expert personalities | For reference; actual prompts in `glm_mcp_server.py` |
| `commands/*.md` | Slash commands | `/setup`, `/uninstall` |
| `glm_mcp_server.py` | MCP server implementation | Handles GLM API communication |

> Expert prompts adapted from [claude-delegator](https://github.com/jarrodwatts/claude-delegator) and [oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode)

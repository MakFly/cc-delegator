---
name: setup
description: Configure glm-delegator with Z.AI GLM (4.7/5) MCP server
allowed-tools: Bash, Read, Write, Edit, AskUserQuestion
timeout: 60000
---

# Setup

Configure GLM (4.7/5) as specialized expert subagents via MCP. Five domain experts that can advise OR implement.

## Flags
- `--non-interactive` or `-y`: Skip all prompts, use defaults
- `--api-key KEY`: Pass API key directly (skip env check)
- `--model MODEL`: Override default model (default: glm-5)
- `--no-rules`: Skip rule file installation

## Exit Codes
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Missing dependencies |
| 2 | Missing API key |
| 3 | Config write error |
| 4 | User cancelled |

## Step 1: Check Python and Dependencies

```bash
python3 --version 2>&1 || echo "PYTHON_MISSING"
pip3 show httpx 2>/dev/null | grep Version || echo "HTTPX_MISSING"
```

### If Missing

Tell user:
```
Python 3.8+ or httpx library not found.

Install dependencies with:
  cd /path/to/glm-delegator
  pip3 install -r requirements.txt

After installation, re-run /glm-delegator:setup
```

**STOP here if dependencies are missing.**

## Step 2: Check API Key

```bash
echo "GLM_API_KEY: ${GLM_API_KEY:+SET}"
echo "Z_AI_API_KEY: ${Z_AI_API_KEY:+SET}"
```

### If Not Set

Tell user:
```
Z.AI API key not found.

Get your API key from: https://platform.z.ai/

Then set it:
  export GLM_API_KEY="your_api_key_here"

Or add to ~/.bashrc or ~/.zshrc for persistence.
```

## Step 3: Get GLM Delegator Path

```bash
echo "${CLAUDE_PLUGIN_ROOT}"
```

This should output the path to glm-delegator.

## Step 4: Read Current Settings

```bash
cat ~/.claude.json 2>/dev/null || cat ~/.claude/settings.json 2>/dev/null || echo "{}"
```

## Step 5: Configure MCP Server

Merge into `~/.claude.json` (or `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "glm-delegator": {
      "command": "python3",
      "args": ["${CLAUDE_PLUGIN_ROOT}/glm_mcp_server.py"],
      "env": {
        "GLM_API_KEY": "${GLM_API_KEY:-${Z_AI_API_KEY}}"
      }
    }
  }
}
```

**CRITICAL**:
- Merge with existing settings, don't overwrite
- Preserve any existing `mcpServers` entries
- Replace `${CLAUDE_PLUGIN_ROOT}` with actual path
- Replace API key with actual value

## Step 6: Install Orchestration Rules

```bash
mkdir -p ~/.claude/rules/glm-delegator && cp ${CLAUDE_PLUGIN_ROOT}/rules/*.md ~/.claude/rules/glm-delegator/
```

## Step 7: Verify Installation

Run these checks and report results:

```bash
# Check 1: Python version
python3 --version 2>&1

# Check 2: httpx installed
pip3 show httpx 2>&1 | grep Version || echo "Not installed"

# Check 3: MCP server configured
cat ~/.claude.json 2>/dev/null | jq -r '.mcpServers["glm-delegator"].command' 2>/dev/null || \
cat ~/.claude/settings.json 2>/dev/null | jq -r '.mcpServers["glm-delegator"].command' 2>/dev/null || \
echo "Not configured"

# Check 4: Server script exists
ls -la ${CLAUDE_PLUGIN_ROOT}/glm_mcp_server.py 2>/dev/null || echo "Script not found"

# Check 5: Rules installed (count files)
ls ~/.claude/rules/glm-delegator/*.md 2>/dev/null | wc -l

# Check 6: API key set
echo "GLM_API_KEY: ${GLM_API_KEY:+SET}"
echo "Z_AI_API_KEY: ${Z_AI_API_KEY:+SET}"
```

## Step 8: Report Status

Display actual values from the checks above:

```
glm-delegator Status
───────────────────────────────────────────────────
Python:        ✓ [version from check 1]
Dependencies:  ✓ httpx [version] (or ✗ if missing)
MCP Config:    ✓ ~/.claude.json (or ✗ if missing)
Server Script: ✓ glm_mcp_server.py (or ✗ if missing)
Rules:         ✓ [N] files in ~/.claude/rules/glm-delegator/
API Key:       ✓ SET (or ✗ if missing)
───────────────────────────────────────────────────
```

If any check fails, report the specific issue and how to fix it.

## Step 9: Final Instructions

```
Setup complete!

Next steps:
1. Restart Claude Code to load MCP server
2. Set API key if not already: export GLM_API_KEY="your_key"

Five GLM experts available:

┌──────────────────┬─────────────────────────────────────────────┐
│ Architect        │ "How should I structure this service?"      │
│                  │ "What are the tradeoffs of Redis vs X?"     │
│                  │ → System design, architecture decisions     │
├──────────────────┼─────────────────────────────────────────────┤
│ Plan Reviewer    │ "Review this migration plan"                │
│                  │ "Is this implementation plan complete?"     │
│                  │ → Plan validation before execution          │
├──────────────────┼─────────────────────────────────────────────┤
│ Scope Analyst    │ "Clarify the scope of this feature"         │
│                  │ "What am I missing in these requirements?"  │
│                  │ → Pre-planning, catches ambiguities         │
├──────────────────┼─────────────────────────────────────────────┤
│ Code Reviewer    │ "Review this PR" (EN/FR/CN)                 │
│                  │ "Find issues in this implementation"        │
│                  │ → Code quality, bugs, maintainability       │
├──────────────────┼─────────────────────────────────────────────┤
│ Security Analyst │ "Is this authentication flow secure?"       │
│                  │ "Harden this endpoint"                      │
│                  │ → Vulnerabilities, threat modeling          │
└──────────────────┴─────────────────────────────────────────────┘

Every expert can advise (read-only) OR implement (write).
Expert is auto-detected based on your request.
Explicit: "Ask GLM to review..." or "Have GLM fix..."

Documentation: https://github.com/kev/glm-delegator
```

## Step 10: Ask About Starring

Use AskUserQuestion to ask the user if they'd like to ⭐ star the glm-delegator repository on GitHub to support the project.

Options: "Yes, star the repo" / "No thanks"

**If yes**: Check if `gh` CLI is available and run:
```bash
gh api -X PUT /user/starred/kev/glm-delegator
```

If `gh` is not available or the command fails, provide the manual link:
```
https://github.com/kev/glm-delegator
```

**If no**: Thank them and complete setup without starring.

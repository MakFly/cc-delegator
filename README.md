# LLM Delegator

> Multi-provider LLM expert subagents for Claude Code — A fork of [claude-delegator](https://github.com/jarrodwatts/claude-delegator) supporting **any LLM backend**

LLM expert subagents for Claude Code. Five specialists that can analyze AND implement—architecture, security, code review, and more.

**Supports:** Anthropic Claude, OpenAI GPT, GLM-4.7, GLM-5, Ollama, Groq, DeepInfra, and any OpenAI/Anthropic-compatible API.

[![License](https://img.shields.io/github/license/MakFly/glm-delegator?v=2)](LICENSE)
[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## What is LLM Delegator?

Claude gains a team of LLM specialists via MCP. Each expert has a distinct specialty and can advise OR implement.

| What You Get | Why It Matters |
|--------------|----------------|
| **5 domain experts** | Right specialist for each problem type |
| **Dual mode** | Experts can analyze (read-only) or implement (write) |
| **Multi-provider** | Use Claude, GPT-4, GLM (4.7/5), Ollama, or any compatible API |
| **Auto-routing** | Claude detects when to delegate based on your request |
| **Prompt Enhancement** | LLM-based prompt improvement before expert delegation |
| **Synthesized responses** | Claude interprets LLM output, never raw passthrough |
| **Multilingual** | Code Review supports EN/FR/CN (中文) |

### The Experts

| Expert | What They Do | Example Triggers |
|--------|--------------|------------------|
| **Architect** | System design, tradeoffs, complex debugging | "How should I structure this?" / "What are the tradeoffs?" |
| **Plan Reviewer** | Validate plans before you start | "Review this migration plan" / "Is this approach sound?" |
| **Scope Analyst** | Catch ambiguities early | "What am I missing?" / "Clarify the scope" |
| **Code Reviewer** | Find bugs, improve quality (EN/FR/CN) | "Review this PR" / "What's wrong with this?" |
| **Security Analyst** | Vulnerabilities, threat modeling | "Is this secure?" / "Harden this endpoint" |

## Differences from claude-delegator

| Feature | claude-delegator | llm-delegator |
|---------|------------------|---------------|
| Backend | Codex GPT-5.2 only | **Any LLM provider** |
| Configuration | CLI args only | CLI args (same model) |
| Providers | Single | Multi-provider (OpenAI, Anthropic, Ollama, etc.) |
| Code Review | English only | **EN/FR/CN multilingual** |
| Security | OWASP | OWASP + Chinese MLPS standards |
| Prompt Enhancement | None | **LLM-based auto-enhancement** |
| Routing | None | **Intelligent task routing** |
| Workflow | None | **State machine for automation** |
| License | MIT | MIT |

## Install

### Prerequisites

- **Python 3.8+** for the MCP server
- **API Key** for your chosen provider (Anthropic, OpenAI, Z.AI, etc.)
- **httpx** library - `pip install -r requirements.txt`

### Step 1: Install Dependencies

```bash
cd glm-delegator
pip install -r requirements.txt
```

### Step 2: Configure API Key

Set your API key as an environment variable:

```bash
# Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI
export OPENAI_API_KEY="sk-..."

# GLM via Z.AI
export GLM_API_KEY="your_z_ai_api_key_here"

# Groq
export GROQ_API_KEY="gsk_..."
```

For persistent configuration, add to your `~/.bashrc` or `~/.zshrc`:

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.bashrc
source ~/.bashrc
```

### Step 3: Register MCP Server

Add to `~/.claude.json` (or `~/.claude/settings.json`):

#### Using Anthropic Claude

```json
{
  "mcpServers": {
    "claude-experts": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "anthropic-compatible",
        "--base-url", "https://api.anthropic.com/v1",
        "--api-key", "$ANTHROPIC_API_KEY",
        "--model", "claude-sonnet-4-20250514"
      ]
    }
  }
}
```

#### Using OpenAI GPT

```json
{
  "mcpServers": {
    "openai-experts": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "openai-compatible",
        "--base-url", "https://api.openai.com/v1",
        "--api-key", "$OPENAI_API_KEY",
        "--model", "gpt-4o"
      ]
    }
  }
}
```

#### Using Ollama (Local)

```json
{
  "mcpServers": {
    "ollama-experts": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "openai-compatible",
        "--base-url", "http://localhost:11434/v1",
        "--model", "llama3.1"
      ]
    }
  }
}
```

#### Using GLM via Z.AI

```json
{
  "mcpServers": {
    "glm-experts": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "anthropic-compatible",
        "--base-url", "https://api.z.ai/api/anthropic",
        "--api-key", "$GLM_API_KEY",
        "--model", "glm-5"
      ]
    }
  }
}
```

> **Note:** Replace `glm-5` with `glm-4.7` if you prefer the previous generation model.

### Step 4: Restart Claude Code

Restart Claude Code to load the MCP server.

## Supported Providers

| Provider | Type | Example Model |
|----------|------|---------------|
| **Anthropic** | anthropic-compatible | claude-sonnet-4-20250514 |
| **OpenAI** | openai-compatible | gpt-4o |
| **GLM (Z.AI)** | anthropic-compatible | glm-4.7, glm-5 |
| **Ollama** | openai-compatible | llama3.1 |
| **Groq** | openai-compatible | llama-3.3-70b-versatile |
| **DeepInfra** | openai-compatible | deepseek-ai/DeepSeek-V3 |
| **TogetherAI** | openai-compatible | meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo |
| **vLLM** | openai-compatible | (custom) |
| **LM Studio** | openai-compatible | (custom) |

> **Any OpenAI-compatible or Anthropic-compatible API will work!**

## Command-Line Options

```
python3 glm_mcp_server.py --help

Options:
  -p, --provider      Provider type: openai-compatible or anthropic-compatible
  -u, --base-url      Base URL of the API
  -k, --api-key       API key (default: GLM_API_KEY or Z_AI_API_KEY env var)
  -m, --model         Model name
  --api-version       API version for Anthropic-compatible (default: 2023-06-01)
  --timeout           Request timeout in seconds (default: 600)
  --max-tokens        Maximum tokens for responses (default: 8192)
  --debug             Enable debug logging
```

## Usage

Once installed, delegation happens automatically. Claude Code will detect when to delegate based on your request.

### Explicit Delegation

You can also explicitly request LLM expert help:

```
"Ask the architect to review this authentication flow"
"Use the code reviewer to analyze this function"
"Have the security analyst check this code"
```

### Manual Tool Call

You can call the MCP tools directly:

```typescript
// Advisory mode (analysis only)
mcp__glm-delegator__glm_architect({
  task: "Analyze tradeoffs between Redis and in-memory caching",
  mode: "advisory",
  context: "Building a session store for a Node.js app"
})

// Implementation mode (make changes)
mcp__glm-delegator__glm_code_reviewer({
  task: "Fix the SQL injection vulnerability in user.ts",
  mode: "implementation",
  files: ["src/routes/user.ts"]
})

// With auto-enhancement (+1 LLM call for better prompt)
mcp__glm-delegator__glm_architect({
  task: "review this",
  enhance: true  // Auto-enhance prompt before expert
})
```

## Prompt Enhancement System

LLM Delegator includes a **Prompt Enhancement System** that improves prompt quality before sending to experts.

### Features

| Feature | Description | Cost |
|---------|-------------|------|
| **Auto-enhancement** | Add `enhance: true` to any expert call | +1 LLM call |
| **Manual enhancement** | Use `glm_enhance_prompt` tool directly | +1 LLM call |
| **Static validation** | Use `glm_validate_prompt` (no LLM) | Free |

### Usage

#### Option 1: Auto-enhance (Recommended)

```typescript
// Automatically enhance prompt before expert
mcp__glm-delegator__glm_architect({
  task: "probably fix the thing",
  enhance: true  // LLM will clarify and structure the prompt
})
```

#### Option 2: Manual Enhancement

```typescript
// Step 1: Enhance
const enhanced = mcp__glm-delegator__glm_enhance_prompt({
  task: "review this code",
  context: "Authentication module",
  target_expert: "code_reviewer"
})
// Returns: { enhanced_task, suggestions, confidence }

// Step 2: Validate (optional, no LLM call)
const validation = mcp__glm-delegator__glm_validate_prompt({
  task: enhanced.enhanced_task,
  files: ["src/auth.ts"]
})
// Returns: { is_valid, warnings, errors, suggestions }

// Step 3: Send to expert
mcp__glm-delegator__glm_code_reviewer({
  task: enhanced.enhanced_task
})
```

### Enhancement Flow

```
User Request (vague)
        ↓
┌─────────────────────────────────┐
│   glm_enhance_prompt            │  ← LLM call
│   - Clarify intent              │
│   - Add structure               │
│   - Remove uncertainty signals  │
└─────────────────────────────────┘
        ↓
Enhanced Prompt (clear)
        ↓
┌─────────────────────────────────┐
│   glm_validate_prompt           │  ← Static (no LLM)
│   - Check file existence        │
│   - Detect hallucination risks  │
└─────────────────────────────────┘
        ↓
Expert (architect, code_reviewer, etc.)
        ↓
Response
```

### Additional Tools

| Tool | Purpose | LLM Call |
|------|---------|----------|
| `glm_enhance_prompt` | Improve prompt quality | Yes |
| `glm_validate_prompt` | Static validation | No |
| `glm_route` | Route to best expert | No |
| `glm_workflow` | Automated workflow state machine | No |
| `glm_get_job_result` | Poll background job status | No |

## How It Works

```
You: "Is this authentication flow secure?"
                    ↓
Claude: [Detects security question → selects Security Analyst]
                    ↓
        ┌─────────────────────────────┐
        │  mcp__glm-delegator__glm_   │
        │  security_analyst           │
        │  → Security Analyst prompt  │
        │  → LLM analyzes your code   │
        │    via configured API       │
        └─────────────────────────────┘
                    ↓
Claude: "Based on the analysis, I found 3 issues..."
        [Synthesizes response, applies judgment]
```

## Configuration

### Command-Line Arguments

| Argument | Short | Default | Description |
|----------|-------|---------|-------------|
| `--provider` | `-p` | `anthropic-compatible` | Provider type |
| `--base-url` | `-u` | `https://api.z.ai/api/anthropic` | API base URL |
| `--api-key` | `-k` | `$GLM_API_KEY` | API key |
| `--model` | `-m` | `glm-4.7` | Model name (e.g. glm-4.7, glm-5) |
| `--api-version` | - | `2023-06-01` | Anthropic API version |
| `--timeout` | - | `600` | Timeout (seconds) |
| `--max-tokens` | - | `8192` | Max tokens per response |
| `--debug` | - | `false` | Debug logging |

### Operating Modes

Every expert supports two modes based on the task:

| Mode | Use When |
|------|----------|
| **Advisory** | Analysis, recommendations, reviews |
| **Implementation** | Making changes, fixing issues |

Claude automatically selects the mode based on your request.

## Multiple Servers

You can configure multiple servers with different providers:

```json
{
  "mcpServers": {
    "claude-experts": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/glm_mcp_server.py", "--provider", "anthropic-compatible", "--base-url", "https://api.anthropic.com/v1", "--api-key", "$ANTHROPIC_API_KEY", "--model", "claude-sonnet-4-20250514"]
    },
    "ollama-local": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/glm_mcp_server.py", "--provider", "openai-compatible", "--base-url", "http://localhost:11434/v1", "--model", "llama3.1"]
    }
  }
}
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| MCP server not found | Restart Claude Code after configuration |
| Authentication failed | Verify your API key is correct and active |
| Tool not appearing | Check `~/.claude.json` has correct entry |
| Expert not triggered | Try explicit: "Ask the architect to review this" |
| `tools/call` timeout at 60s | See [Timeout Protection](#timeout-protection) below |
| Python not found | Ensure Python 3.8+ is in your PATH |

### Timeout Protection

The MCP protocol has a **60-second timeout** for `tools/call`. To prevent timeouts, the server uses **Background Processing** for large contexts:

| Context Size | Mode | Behavior |
|--------------|------|----------|
| < 8,000 chars | **Direct** | Synchronous response (< 60s) |
| 8,000-15,000 chars | **Background** | Returns `job_id`, async processing |
| > 15,000 chars | **Rejected** | Error "context_too_large" |

| Limit | Value | Why |
|-------|-------|-----|
| `MAX_CONTEXT_CHARS` | 15,000 chars (~4-5k tokens) | Upper limit |
| `MAX_FILES_COUNT` | 5 files | Avoid massive prompts |
| `BACKGROUND_MODE_THRESHOLD` | 8,000 chars | Switch to async |

#### Background Processing Workflow

When context >= 8,000 chars:

```typescript
// Step 1: Call expert (returns job_id immediately)
const result = mcp__glm-delegator__glm_architect({
  task: "Analyze this complex architecture...",
  context: largeContext  // >= 8000 chars
})
// Returns: { job_id: "job_abc123", status: "pending" }

// Step 2: Poll for result
const status = mcp__glm-delegator__glm_get_job_result({
  job_id: "job_abc123"
})
// Returns: { status: "processing", age_seconds: 5 }

// Step 3: Get final result
const final = mcp__glm-delegator__glm_get_job_result({
  job_id: "job_abc123"
})
// Returns: { status: "completed", result: "Expert analysis..." }
```

#### Job Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Job queued, waiting to start |
| `processing` | Expert is analyzing |
| `completed` | Done, result available |
| `failed` | Error occurred |
| `timeout` | Job exceeded 300s limit |

**If you get a "context_too_large" error (> 15,000 chars):**

1. **Reduce files**: Include only the 3-5 most relevant files
2. **Summarize context**: Instead of full file contents, describe the key points
3. **Split requests**: Break complex tasks into smaller, focused requests
4. **Use glm-4.7**: Faster than glm-5 for simple tasks

**Example - Before (will timeout):**
```json
{
  "task": "Review architecture of entire codebase",
  "context": "...",
  "files": ["file1.ts", "file2.ts", "file3.ts", "file4.ts", "file5.ts", "file6.ts", "file7.ts"]
}
```

**Example - After (works):**
```json
{
  "task": "Review auth flow architecture",
  "context": "Focus on login.ts and middleware.ts only. Other files use standard patterns.",
  "files": ["login.ts", "middleware.ts"]
}
```

### Debug Mode

Run with `--debug` to see detailed logs:

```bash
python3 glm_mcp_server.py --debug --provider anthropic-compatible --api-key $ANTHROPIC_API_KEY
```

## Development

```bash
git clone https://github.com/MakFly/glm-delegator
cd glm-delegator

# Install dependencies
pip install -r requirements.txt

# Test locally with a specific provider
python3 glm_mcp_server.py \
  --provider openai-compatible \
  --base-url http://localhost:11434/v1 \
  --model llama3.1 \
  --debug
```

## Architecture

### Components

| Component | Purpose |
|-----------|---------|
| `glm_mcp_server.py` | MCP server with argparse-based configuration |
| `providers.py` | Provider abstraction layer (OpenAI/Anthropic-compatible) |
| `job_manager.py` | Background job management for large contexts |
| `prompt_enhancer.py` | LLM-based prompt improvement system |
| `prompt_guard.py` | Static prompt validation (no LLM) |
| `prompts/*.md` | Expert personality definitions (for reference) |
| `rules/*.md` | Delegation rules and triggers (for reference) |
| `.claude-plugin/plugin.json` | Plugin metadata |

### API Flow

```
Claude Code → MCP Request → glm_mcp_server.py
                                ↓
                    [Optional: enhance=true?]
                                ↓
                    PromptEnhancer.enhance()  ← +1 LLM call
                                ↓
                        Provider Layer (providers.py)
                                ↓
                        Configured API (OpenAI/Anthropic/etc.)
                                ↓
                            LLM Response
                                ↓
                        Response → Claude Code
```

## Documentation

- **[USAGE.md](USAGE.md)** - 📖 Guide d'utilisation complet avec exemples et scénarios
- **[BACKEND_CONFIG.md](BACKEND_CONFIG.md)** - Configuration multi-provider détaillée

## Acknowledgments

- Based on [claude-delegator](https://github.com/jarrodwatts/claude-delegator) by [Jarrod Watts](https://github.com/jarrodwatts)
- Expert prompts adapted from [oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode) by [@code-yeongyu](https://github.com/code-yeongyu)
- Uses Z.AI's [Anthropic-compatible API](https://docs.z.ai/devpack/mcp) for GLM support

## License

MIT — see [LICENSE](LICENSE)

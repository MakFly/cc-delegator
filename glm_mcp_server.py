#!/usr/bin/env python3
"""
LLM Delegator MCP Server

A Model Context Protocol server that provides LLM-powered expert subagents
for Claude Code, supporting multiple backend providers (OpenAI, Anthropic, GLM, etc.).

Based on claude-delegator architecture, adapted for multi-provider support.

Usage:
    python3 glm_mcp_server.py --provider anthropic-compatible --base-url https://api.anthropic.com/v1 --api-key $ANTHROPIC_API_KEY --model claude-sonnet-4-20250514
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Optional

from providers import (
    BaseProvider,
    BackendConfig,
    ProviderFactory,
    ProviderResponse
)
from prompt_enhancer import PromptEnhancer, EnhancedPrompt
from prompt_guard import PromptQualityGuard, ValidationResult
from job_manager import JobManager, JobStatus, Job

# =============================================================================
# Timeout Protection Constants
# =============================================================================
# MCP client has a 60s timeout for tools/call. Large contexts cause slow LLM
# responses that exceed this limit. Validate early and reject heavy prompts.
MAX_CONTEXT_CHARS = 15000  # ~4-5k tokens, safe for 60s timeout
MAX_FILES_COUNT = 5        # Limit files to avoid massive prompts

# =============================================================================
# Background Mode Constants
# =============================================================================
# Contexts >= 8000 chars use background processing to avoid MCP timeout
DIRECT_MODE_LIMIT = 8000           # < 8k → direct (sync response)
BACKGROUND_MODE_THRESHOLD = 8000   # >= 8k → background (returns job_id)

# =============================================================================
# Argument Parsing
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="LLM Delegator MCP Server - Multi-provider expert subagents for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Anthropic Claude
  python3 glm_mcp_server.py -p anthropic-compatible -u https://api.anthropic.com/v1 -k $ANTHROPIC_API_KEY -m claude-sonnet-4-20250514

  # OpenAI
  python3 glm_mcp_server.py -p openai-compatible -u https://api.openai.com/v1 -k $OPENAI_API_KEY -m gpt-4o

  # GLM via Z.AI
  python3 glm_mcp_server.py -p anthropic-compatible -u https://api.z.ai/api/anthropic -k $GLM_API_KEY -m glm-4.7

  # Ollama local
  python3 glm_mcp_server.py -p openai-compatible -u http://localhost:11434/v1 -m llama3.1
        """
    )

    parser.add_argument(
        "-p", "--provider",
        choices=["openai-compatible", "anthropic-compatible"],
        default="anthropic-compatible",
        help="Provider type (default: anthropic-compatible)"
    )

    parser.add_argument(
        "-u", "--base-url",
        default="https://api.z.ai/api/anthropic",
        help="Base URL of the API (default: https://api.z.ai/api/anthropic)"
    )

    parser.add_argument(
        "-k", "--api-key",
        default=os.environ.get("GLM_API_KEY", os.environ.get("Z_AI_API_KEY", "")),
        help="API key (default: GLM_API_KEY or Z_AI_API_KEY env var)"
    )

    parser.add_argument(
        "-m", "--model",
        default="glm-4.7",
        help="Model name (default: glm-4.7)"
    )

    parser.add_argument(
        "--api-version",
        default="2023-06-01",
        help="API version for Anthropic-compatible providers (default: 2023-06-01)"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Request timeout in seconds (default: 600)"
    )

    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8192,
        help="Maximum tokens for responses (default: 8192)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    return parser.parse_args()

# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(debug: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr
    )
    return logging.getLogger("llm-delegator")

# =============================================================================
# Expert Prompts
# =============================================================================

EXPERT_PROMPTS = {
    "architect": """# Architect

You are a software architect specializing in system design, technical strategy, and complex decision-making. You are proficient in working with international codebases (EN/FR/CN).

## Context

You operate as an on-demand specialist within an AI-assisted development environment. Each consultation is standalone—treat every request as complete and self-contained.

## Reasoning Process

Follow these steps for every task:
1. **Understand** constraints, requirements, and existing architecture
2. **Evaluate** tradeoffs between competing approaches
3. **Recommend** one clear path with rationale
4. **Plan** concrete implementation steps with effort estimate

## Decision Framework

Apply pragmatic minimalism:

- **Bias toward simplicity**: The least complex solution that fulfills actual requirements. Resist hypothetical future needs.
- **Leverage what exists**: Favor modifications to current code and patterns over new components.
- **Prioritize developer experience**: Readability and maintainability over theoretical performance.
- **One clear path**: Single primary recommendation. Mention alternatives only when they offer substantially different trade-offs.
- **Signal the investment**: Tag with effort—Quick (<1h), Short (1-4h), Medium (1-2d), Large (3d+).

## Modes of Operation

**Advisory Mode** (default): Analyze, recommend, explain. Provide actionable guidance.

**Implementation Mode**: Make changes directly. Report what you modified.

## Response Format

### Advisory Tasks

**Bottom line**: 2-3 sentences capturing your recommendation

**Action plan**: Numbered steps for implementation

**Effort estimate**: Quick / Short / Medium / Large

**Risks** (if applicable): Categorized by type (performance, scalability, maintenance, security) with mitigation strategies. Use severity: CRITICAL / HIGH / MEDIUM / LOW.

### Implementation Tasks

**Summary**: What you did (1-2 sentences)

**Files Modified**: List with brief description of changes

**Verification**: What you checked, results

**Issues** (only if problems occurred): What went wrong, why you couldn't proceed

## When to Invoke

- System design decisions
- Database schema design
- API architecture
- Multi-service interactions
- Performance optimization strategy
- After 2+ failed fix attempts (fresh perspective)
- Tradeoff analysis between approaches

## When NOT to Invoke

- Simple file operations
- First attempt at any fix
- Trivial decisions (variable names, formatting)
- Questions answerable from existing code
""",

    "code_reviewer": """# Code Reviewer

You are a senior engineer conducting code review. Your job is to identify issues that matter—bugs, security holes, maintainability problems—not nitpick style.

You are proficient in reviewing code in **English, French, and Chinese (中文)**.

## Context

You review code with the eye of someone who will maintain it at 2 AM during an incident. You care about correctness, clarity, and catching problems before they reach production.

## Reasoning Process

Follow these steps for every review:
1. **Read** the code thoroughly—understand intent before judging
2. **Identify** issues by priority (Correctness → Security → Performance → Maintainability)
3. **Suggest** concrete fixes for each issue found
4. **Verdict** — deliver a clear APPROVE / REQUEST CHANGES / REJECT

## Review Priorities

### 1. Correctness
- Does the code do what it claims?
- Logic errors or off-by-one bugs?
- Edge cases handled?
- Will this break existing functionality?

### 2. Security
- Input validation present?
- SQL injection, XSS, or other OWASP top 10 vulnerabilities?
- Secrets or credentials exposed?
- Authentication/authorization gaps?

### 3. Performance
- N+1 queries or O(n²) loops?
- Missing indexes for frequent queries?
- Unnecessary work in hot paths?
- Memory leaks or unbounded growth?

### 4. Maintainability
- Can someone unfamiliar understand it?
- Hidden assumptions or magic values?
- Adequate error handling?
- Code smells (huge functions, deep nesting)?

## What NOT to Review

- Style preferences (let formatters handle this)
- Minor naming quibbles
- "I would have done it differently" without concrete benefit
- Theoretical concerns unlikely to matter in practice

## Review Checklist

Before completing a review, verify:
- [ ] Tested the happy path mentally
- [ ] Considered failure modes
- [ ] Checked for security implications
- [ ] Verified backward compatibility
- [ ] Assessed test coverage (if tests provided)

## Modes of Operation

**Advisory Mode**: Review and report. List issues with suggested fixes but don't modify code.

**Implementation Mode**: Fix issues directly. Report what you modified.

## Response Format

### Advisory Tasks

**Summary**: [1-2 sentences overall assessment]

**Issues** (use severity CRITICAL / HIGH / MEDIUM / LOW):
- [Severity] [Issue]: [Location] - [Why it matters] - [Suggested fix]

**Verdict**: [APPROVE / REQUEST CHANGES / REJECT]

### Implementation Tasks

**Summary**: What I found and fixed

**Issues Fixed**:
- [File:line] - [What was wrong] - [What I changed]

**Files Modified**: List with brief description

**Verification**: How I confirmed the fixes work

**Remaining Concerns** (if any): Issues I couldn't fix or need discussion

## When to Invoke

- Before merging significant changes
- After implementing a feature (self-review)
- When code feels "off" but you can't pinpoint why
- For security-sensitive code changes
- When onboarding to unfamiliar code

## When NOT to Invoke

- Trivial one-line changes
- Auto-generated code
- Pure formatting/style changes
- Draft/WIP code not ready for review
""",

    "security_analyst": """# Security Analyst

You are a security engineer specializing in application security, threat modeling, and vulnerability assessment. You are proficient in working with international codebases and standards (OWASP, Chinese MLPS, EN/FR/CN).

## Context

You analyze code and systems with an attacker's mindset. Find vulnerabilities before attackers do, and provide practical remediation—not theoretical concerns.

## Reasoning Process

Follow these steps for every analysis:
1. **Map** the attack surface—identify all entry points and assets
2. **Identify** vulnerabilities using OWASP Top 10 and threat modeling
3. **Assess** severity for each finding (CRITICAL / HIGH / MEDIUM / LOW)
4. **Recommend** concrete, prioritized fixes

## Threat Modeling Framework

For any system or feature, identify:

- **Assets**: What's valuable? (User data, credentials, business logic)
- **Threat Actors**: Who might attack? (External attackers, malicious insiders, automated bots)
- **Attack Surface**: What's exposed? (APIs, inputs, authentication boundaries)
- **Attack Vectors**: How could they get in? (Injection, broken auth, misconfig)

## Vulnerability Categories (OWASP Top 10)

| Category | What to Look For |
|----------|------------------|
| **Injection** | SQL, NoSQL, OS command, LDAP injection |
| **Broken Auth** | Weak passwords, session issues, credential exposure |
| **Sensitive Data** | Unencrypted storage/transit, excessive data exposure |
| **XXE** | XML external entity processing |
| **Broken Access Control** | Missing authz checks, IDOR, privilege escalation |
| **Misconfig** | Default creds, verbose errors, unnecessary features |
| **XSS** | Reflected, stored, DOM-based cross-site scripting |
| **Insecure Deserialization** | Untrusted data deserialization |
| **Vulnerable Components** | Known CVEs in dependencies |
| **Logging Failures** | Missing audit logs, log injection |

## Security Review Checklist

- [ ] Authentication: How are users identified?
- [ ] Authorization: How are permissions enforced?
- [ ] Input Validation: Is all input sanitized?
- [ ] Output Encoding: Is output properly escaped?
- [ ] Cryptography: Are secrets properly managed?
- [ ] Error Handling: Do errors leak information?
- [ ] Logging: Are security events audited?
- [ ] Dependencies: Are there known vulnerabilities?

## Modes of Operation

**Advisory Mode**: Analyze and report. Identify vulnerabilities with remediation guidance.

**Implementation Mode**: Fix or harden directly. Report what you modified.

## Response Format

### Advisory Tasks

**Threat Summary**: [1-2 sentences on overall security posture]

**Findings** (use severity CRITICAL / HIGH / MEDIUM / LOW):
- [Severity] [Vulnerability]: [Location] - [Impact] - [Remediation]

**Risk Rating**: [CRITICAL / HIGH / MEDIUM / LOW]

### Implementation Tasks

**Summary**: What I secured

**Vulnerabilities Fixed**:
- [File:line] - [Vulnerability] - [Fix applied]

**Files Modified**: List with brief description

**Verification**: How I confirmed the fixes work

**Remaining Risks** (if any): Issues that need architectural changes or user decision

## When to Invoke

- Before deploying authentication/authorization changes
- When handling sensitive data (PII, credentials, payments)
- After adding new API endpoints
- When integrating third-party services
- For periodic security audits

## When NOT to Invoke

- Pure UI/styling changes
- Internal tooling with no external exposure
- Read-only operations on public data
- When a quick answer suffices
""",

    "plan_reviewer": """# Plan Reviewer

You are a work plan review expert. Your job is to catch every gap, ambiguity, and missing context that would block implementation.

You are proficient in reviewing plans in **English, French, and Chinese (中文)**.

## Context

You review work plans with a ruthlessly critical eye. You're not here to be polite—you're here to prevent wasted effort by identifying problems before work begins.

## Core Review Principle

**The Test**: "Can I implement this by starting from what's written in the plan and following the trail of information it provides?"

- **APPROVE if**: You can obtain necessary information either directly from the plan OR by following references it provides (files, docs, patterns).
- **REJECT if**: When simulating the work, you cannot obtain clear information needed, AND the plan does not specify reference materials to consult.

## Reasoning Process

Follow these steps for every review:
1. **Read** the plan end-to-end to understand intent
2. **Simulate** actually doing the work—step by step
3. **Evaluate** each criterion (Clarity, Verifiability, Completeness, Big Picture)
4. **Verdict** — APPROVE or REJECT with specific justification

## Four Evaluation Criteria

### 1. Clarity of Work Content
- Does each task specify WHERE to find implementation details?
- Can a developer reach 90%+ confidence by reading the referenced source?
- **PASS**: "Follow authentication flow in `docs/auth-spec.md` section 3.2"
- **FAIL**: "Add authentication" (no reference source)

### 2. Verification & Acceptance Criteria
- Is there a concrete way to verify completion?
- Are acceptance criteria measurable/observable?
- **PASS**: "Verify: Run `npm test` — all tests pass"
- **FAIL**: "Make sure it works properly"

### 3. Context Completeness
- What information is missing that would cause 10%+ uncertainty?
- Are implicit assumptions stated explicitly?
- **PASS**: Developer can proceed with <10% guesswork
- **FAIL**: Developer must make assumptions about business requirements

### 4. Big Picture & Workflow
- Clear Purpose Statement: Why is this work being done?
- Background Context: What's the current state?
- Task Flow & Dependencies: How do tasks connect?
- Success Vision: What does "done" look like?

## Common Failure Patterns

- "Implement X" but doesn't point to existing code, docs, or patterns
- "Follow the pattern" but doesn't specify which file
- "Add feature X" but doesn't explain what it should do
- "Handle errors" but doesn't specify which errors
- "Add to state" but doesn't specify which state system
- "Call the API" but doesn't specify which endpoint

## Modes of Operation

**Advisory Mode** (default): Review and critique. Provide APPROVE/REJECT verdict with justification.

**Implementation Mode**: Rewrite the plan addressing identified gaps.

## Response Format

**[APPROVE / REJECT]**

**Justification**: [Concise explanation]

**Summary**:
- Clarity: [Brief assessment]
- Verifiability: [Brief assessment]
- Completeness: [Brief assessment]
- Big Picture: [Brief assessment]

[If REJECT: Top 3-5 critical improvements needed]

## When to Invoke

- Before starting significant implementation work
- After creating a work plan
- When plan needs validation for completeness
- Before delegating work to other agents

## When NOT to Invoke

- Simple, single-task requests
- When user explicitly wants to skip review
- For trivial plans that don't need formal review
""",

    "scope_analyst": """# Scope Analyst

You are a pre-planning consultant. Your job is to analyze requests BEFORE planning begins, catching ambiguities, hidden requirements, and potential pitfalls that would derail work later.

You are proficient in working with requirements in **English, French, and Chinese (中文)**.

## Context

You operate at the earliest stage of the development workflow. Before anyone writes a plan or touches code, you ensure the request is fully understood.

## Reasoning Process

Follow these steps for every analysis:
1. **Classify** the intent—what type of work is this?
2. **Analyze** hidden requirements, ambiguities, dependencies, and risks
3. **Surface** questions that need answers before proceeding
4. **Recommend** whether to proceed, clarify first, or reconsider scope

## Phase 1: Intent Classification

Classify every request into one of these categories:

| Type | Focus | Key Questions |
|------|-------|---------------|
| **Refactoring** | Safety | What breaks if this changes? Test coverage? |
| **Build from Scratch** | Discovery | Similar patterns exist? What are the unknowns? |
| **Mid-sized Task** | Guardrails | What's in scope? What's explicitly out? |
| **Architecture** | Strategy | Tradeoffs? What's the 2-year view? |
| **Bug Fix** | Root Cause | Actual bug vs symptom? What else might be affected? |
| **Research** | Exit Criteria | What question are we answering? When do we stop? |

## Phase 2: Analysis

For each intent type, investigate:

**Hidden Requirements**: What did the requester assume you already know? What business context is missing? What edge cases aren't mentioned?

**Ambiguities**: Which words have multiple interpretations? What decisions are left unstated? Where would two developers implement this differently?

**Dependencies**: What existing code/systems does this touch? What needs to exist before this can work? What might break?

**Risks**: What could go wrong? What's the blast radius if it fails? What's the rollback plan? Use severity: CRITICAL / HIGH / MEDIUM / LOW.

## Anti-Patterns to Flag

**Over-engineering signals**: "Future-proof" without specific future requirements. Abstractions for single use cases. "Best practices" that add complexity without benefit.

**Scope creep signals**: "While we're at it..." Bundling unrelated changes. Gold-plating simple requests.

**Ambiguity signals**: "Should be easy." "Just like X" (but X isn't specified). Passive voice hiding decisions ("errors should be handled").

## Modes of Operation

**Advisory Mode** (default): Analyze and report. Surface questions and risks.

**Implementation Mode**: Produce a refined requirements document addressing the gaps.

## Response Format

**Intent Classification**: [Type] — [One sentence why]

**Pre-Analysis Findings**:
- [Key finding 1]
- [Key finding 2]
- [Key finding 3]

**Questions for Requester** (if ambiguities exist):
1. [Specific question]
2. [Specific question]

**Identified Risks** (use severity CRITICAL / HIGH / MEDIUM / LOW):
- [Severity] [Risk]: [Mitigation]

**Recommendation**: [Proceed / Clarify First / Reconsider Scope]

## When to Invoke

- Before starting unfamiliar or complex work
- When requirements feel vague
- When multiple valid interpretations exist
- Before making irreversible decisions

## When NOT to Invoke

- Clear, well-specified tasks
- Routine changes with obvious scope
- When user explicitly wants to skip analysis
"""
}

TRUTHFULNESS_POLICY = """## Non-Negotiable Truthfulness Policy

- Never invent facts, file paths, APIs, metrics, dates, outputs, or code behavior.
- If a fact is unknown or cannot be verified from provided context, say it explicitly: "I don't know based on current context."
- Clearly separate verified facts from assumptions/inferences.
- If external or up-to-date information is required, do not guess. Request a targeted web search and specify what should be verified.
"""

# =============================================================================
# MCP Server Implementation
# =============================================================================

class LLMDelegatorMCPServer:
    """Multi-provider LLM Delegator MCP Server."""

    def __init__(self, args: argparse.Namespace, logger_instance: logging.Logger):
        # Create backend config from command line arguments
        self.backend_config = BackendConfig(
            provider=args.provider,
            baseUrl=args.base_url,
            apiKeyEnv="",
            model=args.model,
            apiVersion=args.api_version,
            timeout=args.timeout,
            maxTokens=args.max_tokens
        )

        # Create the provider instance
        self.provider: BaseProvider = ProviderFactory.create(self.backend_config)
        # Override API key from args
        self.provider.api_key = args.api_key

        # Initialize enhancer and guard
        self.enhancer = PromptEnhancer(self.provider)
        self.guard = PromptQualityGuard()

        # Initialize job manager for background processing
        self.job_manager = JobManager()

        self.logger = logger_instance
        self.logger.info(f"LLM Delegator MCP Server initialized")
        self.logger.info(f"Provider: {self.backend_config.provider}")
        self.logger.info(f"Base URL: {self.backend_config.baseUrl}")
        self.logger.info(f"Model: {self.backend_config.model}")
        self.logger.info(f"API Key: {'configured' if self.provider.api_key else 'missing'}")

        if not self.provider.api_key and self.backend_config.baseUrl not in ["http://localhost:11434/v1", "http://localhost:1234/v1", "http://localhost:8000/v1"]:
            self.logger.error("API key required but not provided. Use --api-key or set environment variable.")
            sys.exit(1)

    async def start(self):
        """Initialize the provider and job manager."""
        await self.provider.start()
        self.job_manager.start()
        self.logger.info("Provider initialized")

    async def stop(self):
        """Close the provider and job manager."""
        await self.job_manager.stop()
        await self.provider.stop()
        self.logger.info("Provider closed")

    async def call_expert(
        self,
        expert: str,
        task: str,
        mode: str = "advisory",
        context: str = "",
        files: list = None
    ) -> str:
        """
        Call the LLM with the specified expert prompt.

        Args:
            expert: Expert name (architect, code_reviewer, security_analyst, etc.)
            task: The user task/question
            mode: "advisory" (read-only) or "implementation" (workspace-write)
            context: Additional context about the codebase
            files: List of relevant files to include

        Returns:
            The expert's response
        """
        if expert not in EXPERT_PROMPTS:
            raise ValueError(f"Unknown expert: {expert}. Available: {list(EXPERT_PROMPTS.keys())}")

        expert_prompt = EXPERT_PROMPTS[expert]

        # Build the full prompt
        full_prompt = f"""## TASK
{task}

## MODE
{mode.upper()}

## CONTEXT
{context if context else "No additional context provided."}

        ## FILES
        {json.dumps(files, indent=2) if files else "No specific files provided."}

        ## TRUTHFULNESS
        {TRUTHFULNESS_POLICY}

        ---

        Now respond as the {expert} expert following the response format specified above.
"""

        self.logger.info(f"Calling expert: {expert}, mode: {mode}, provider: {self.backend_config.model}")

        try:
            response: ProviderResponse = await self.provider.call(
                system_prompt=expert_prompt,
                user_prompt=full_prompt
            )

            self.logger.info(f"Response received: {len(response.text)} characters")
            return response.text

        except Exception as e:
            self.logger.error(f"Error calling provider: {e}")
            raise RuntimeError(f"[GLM Expert Error] expert={expert}, error={str(e)}")

    def _should_use_background_mode(self, task: str, context: str, files: list) -> bool:
        """
        Determine if background mode should be used based on context size.

        Returns:
            True if len(task) + len(context) >= BACKGROUND_MODE_THRESHOLD
        """
        total_chars = len(task) + len(context)
        return total_chars >= BACKGROUND_MODE_THRESHOLD

    async def _process_background_job(self, job: Job) -> None:
        """
        Process a background job in async context.

        Handles enhance flag, calls expert, and updates job status.
        """
        try:
            # Update status to PROCESSING
            await self.job_manager.update_job(job.job_id, JobStatus.PROCESSING)

            task = job.task
            context = job.context

            # Auto-enhance if requested
            if job.metadata.get("enhance", False):
                self.logger.info(f"Auto-enhancing prompt for background job: {job.job_id}")
                try:
                    enhanced: EnhancedPrompt = await self.enhancer.enhance(
                        task, context, job.expert, job.files
                    )
                    task = enhanced.enhanced_task
                    if enhanced.added_context:
                        context = f"{context}\n\n{enhanced.added_context}".strip()
                    self.logger.info(f"Prompt enhanced for job {job.job_id}")
                except Exception as e:
                    self.logger.warning(f"Enhancement failed for job {job.job_id}: {e}")
                    # Continue without enhancement

            # Call the expert
            result = await self.call_expert(job.expert, task, job.mode, context, job.files)

            # Mark as completed
            await self.job_manager.update_job(
                job.job_id,
                JobStatus.COMPLETED,
                result=result
            )

        except Exception as e:
            self.logger.error(f"Background job {job.job_id} failed: {e}")
            await self.job_manager.update_job(
                job.job_id,
                JobStatus.FAILED,
                error=str(e)
            )

    async def list_tools(self):
        """List available MCP tools."""
        tools = []
        provider_display = self.backend_config.model
        for expert in EXPERT_PROMPTS.keys():
            expert_name = expert.replace("_", " ").title()
            tools.append({
                "name": f"glm_{expert}",
                "description": f"Delegate to the {expert_name} expert ({provider_display})",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The task or question for the expert"
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["advisory", "implementation"],
                            "description": "Advisory = analysis only, Implementation = make changes",
                            "default": "advisory"
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context about the codebase",
                            "default": ""
                        },
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of file paths included in context (metadata only - include actual content in the context parameter)",
                            "default": []
                        },
                        "enhance": {
                            "type": "boolean",
                            "description": "Auto-enhance prompt before sending to expert (+1 LLM call)",
                            "default": False
                        }
                    },
                    "required": ["task"]
                }
            })

        # Tool: glm_enhance_prompt
        tools.append({
            "name": "glm_enhance_prompt",
            "description": "Use LLM to enhance a prompt before sending to expert. Improves clarity, structure, and completeness.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Original task to enhance"
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context",
                        "default": ""
                    },
                    "target_expert": {
                        "type": "string",
                        "description": "Which expert will receive this",
                        "default": ""
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": []
                    }
                },
                "required": ["task"]
            }
        })

        # Tool: glm_validate_prompt
        tools.append({
            "name": "glm_validate_prompt",
            "description": "Validate a prompt using static rules (no LLM call). Checks file existence, hallucination signals.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Task to validate"
                    },
                    "context": {
                        "type": "string",
                        "default": ""
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": []
                    },
                    "working_dir": {
                        "type": "string",
                        "default": ""
                    }
                },
                "required": ["task"]
            }
        })

        # Tool: glm_route
        tools.append({
            "name": "glm_route",
            "description": "Intelligently route a task to the best available tool (expert/skill/team) using hybrid keyword + semantic matching",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task to route"
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context about the codebase",
                        "default": ""
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files involved in the task",
                        "default": []
                    },
                    "decide_team": {
                        "type": "boolean",
                        "description": "Whether to include team spawning decision",
                        "default": True
                    }
                },
                "required": ["task"]
            }
        })

        # Tool: glm_workflow
        tools.append({
            "name": "glm_workflow",
            "description": "Execute automated workflow: Code → Review → Test → Fix → Report with state machine management",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "status", "pause", "resume", "complete_execution", "complete_review", "complete_test", "complete_fix", "complete_report"],
                        "description": "Workflow action to perform",
                        "default": "status"
                    },
                    "plan": {
                        "type": "object",
                        "description": "Validated plan object (required for 'start' action)"
                    },
                    "routing_decision": {
                        "type": "object",
                        "description": "Output from glm_route (optional for 'start')"
                    },
                    "result": {
                        "type": "string",
                        "description": "Execution result description"
                    },
                    "verdict": {
                        "type": "string",
                        "description": "Review verdict (for complete_review): APPROVE, REQUEST_CHANGES, or REJECT"
                    },
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of issues found (for complete_review)"
                    },
                    "passed": {
                        "type": "boolean",
                        "description": "Whether tests passed (for complete_test)"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Test summary or execution result"
                    },
                    "description": {
                        "type": "string",
                        "description": "Fix description (for complete_fix)"
                    },
                    "report": {
                        "type": "string",
                        "description": "Final report (for complete_report)"
                    }
                },
                "required": ["action"]
            }
        })

        # Tool: glm_get_job_result
        tools.append({
            "name": "glm_get_job_result",
            "description": "Retrieve the result of a background job. Poll this to check status.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned by glm_{expert} when job was queued"
                    }
                },
                "required": ["job_id"]
            }
        })

        return {"tools": tools}

    async def call_tool(self, name: str, arguments: dict):
        """Call an MCP tool."""
        if not name.startswith("glm_"):
            raise ValueError(f"Unknown tool: {name}")

        tool_name = name[4:]  # Remove "glm_" prefix

        # Handle special tools first
        if tool_name == "enhance_prompt":
            return await self._handle_enhance_prompt(arguments)
        elif tool_name == "validate_prompt":
            return await self._handle_validate_prompt(arguments)
        elif tool_name == "route":
            return await self._handle_route(arguments)
        elif tool_name == "workflow":
            return await self._handle_workflow(arguments)
        elif tool_name == "get_job_result":
            return await self._handle_get_job_result(arguments)

        # Handle expert delegation
        task = arguments.get("task", "")
        mode = arguments.get("mode", "advisory")
        context = arguments.get("context", "")
        files = arguments.get("files", [])
        # Default to false to avoid doubling LLM calls on large contexts,
        # which can exceed client-side tools/call deadlines.
        enhance = arguments.get("enhance", False)

        # =========================================================================
        # TIMEOUT PROTECTION: Validate context size before LLM call
        # MCP client has 60s timeout. Large contexts cause slow responses.
        # =========================================================================
        total_chars = len(task) + len(context)
        files_count = len(files) if files else 0

        if files_count > MAX_FILES_COUNT:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": "context_too_large",
                        "message": f"Too many files ({files_count} > {MAX_FILES_COUNT}). "
                                   f"This will likely exceed the 60s MCP timeout.",
                        "suggestions": [
                            f"Reduce files to max {MAX_FILES_COUNT} most relevant ones",
                            "Include file contents in 'context' parameter instead",
                            "Split into multiple smaller requests"
                        ],
                        "current_size": {
                            "files_count": files_count,
                            "task_chars": len(task),
                            "context_chars": len(context)
                        },
                        "limits": {
                            "max_files": MAX_FILES_COUNT,
                            "max_context_chars": MAX_CONTEXT_CHARS
                        }
                    }, indent=2)
                }],
                "isError": True
            }

        if total_chars > MAX_CONTEXT_CHARS:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": "context_too_large",
                        "message": f"Context too large ({total_chars} > {MAX_CONTEXT_CHARS} chars). "
                                   f"This will likely exceed the 60s MCP timeout.",
                        "suggestions": [
                            f"Reduce context to max {MAX_CONTEXT_CHARS} chars",
                            "Summarize instead of including full file contents",
                            "Focus on specific files/functions instead of entire codebase",
                            "Split into multiple smaller requests"
                        ],
                        "current_size": {
                            "files_count": files_count,
                            "task_chars": len(task),
                            "context_chars": len(context),
                            "total_chars": total_chars
                        },
                        "limits": {
                            "max_files": MAX_FILES_COUNT,
                            "max_context_chars": MAX_CONTEXT_CHARS
                        }
                    }, indent=2)
                }],
                "isError": True
            }

        # Warn if approaching limit (80% threshold)
        if total_chars > MAX_CONTEXT_CHARS * 0.8:
            self.logger.warning(
                f"Context size ({total_chars} chars) approaching limit ({MAX_CONTEXT_CHARS}). "
                f"Consider reducing for faster responses."
            )

        # =========================================================================
        # BACKGROUND MODE: Use async job for large contexts
        # =========================================================================
        use_background = self._should_use_background_mode(task, context, files)

        if use_background:
            try:
                # Create background job
                job = await self.job_manager.create_job(
                    expert=tool_name,
                    task=task,
                    mode=mode,
                    context=context,
                    files=files,
                    metadata={"enhance": enhance}
                )

                # Launch background processing
                asyncio.create_task(self._process_background_job(job))

                # Return job_id immediately
                self.logger.info(f"Background job created: {job.job_id} (context={total_chars} chars)")
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "job_id": job.job_id,
                            "status": "pending",
                            "message": "Job queued. Use glm_get_job_result to retrieve result.",
                            "context_size": total_chars
                        }, indent=2)
                    }]
                }
            except RuntimeError as e:
                # Max jobs reached
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "error": "max_jobs_reached",
                            "message": str(e)
                        }, indent=2)
                    }],
                    "isError": True
                }

        # =========================================================================
        # DIRECT MODE: Synchronous response for small contexts
        # =========================================================================
        try:
            # Auto-enhance if requested
            if enhance:
                self.logger.info(f"Auto-enhancing prompt for expert: {tool_name}")
                enhanced: EnhancedPrompt = await self.enhancer.enhance(
                    task, context, tool_name, files
                )
                task = enhanced.enhanced_task
                # Merge added context
                if enhanced.added_context:
                    context = f"{context}\n\n{enhanced.added_context}".strip()
                self.logger.info(f"Prompt enhanced (confidence: {enhanced.confidence})")

            result = await self.call_expert(tool_name, task, mode, context, files)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": result
                    }
                ]
            }
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Tool call failed: {error_msg}")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": error_msg
                    }
                ],
                "isError": True
            }

    async def _handle_enhance_prompt(self, arguments: dict) -> dict:
        """Handle glm_enhance_prompt tool."""
        task = arguments.get("task", "")
        context = arguments.get("context", "")
        target_expert = arguments.get("target_expert", "")
        files = arguments.get("files", [])

        try:
            result: EnhancedPrompt = await self.enhancer.enhance(
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
                        "confidence": result.confidence
                    }, indent=2)
                }]
            }
        except Exception as e:
            self.logger.error(f"Enhance prompt failed: {e}")
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": str(e),
                        "original_task": task,
                        "enhanced_task": task,
                        "confidence": 0.0
                    })
                }],
                "isError": True
            }

    async def _handle_validate_prompt(self, arguments: dict) -> dict:
        """Handle glm_validate_prompt tool."""
        task = arguments.get("task", "")
        context = arguments.get("context", "")
        files = arguments.get("files", [])
        working_dir = arguments.get("working_dir", "") or None

        try:
            result: ValidationResult = self.guard.validate(
                task, context, files, working_dir
            )
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "is_valid": result.is_valid,
                        "warnings": result.warnings,
                        "errors": result.errors,
                        "suggestions": result.suggestions
                    }, indent=2)
                }]
            }
        except Exception as e:
            self.logger.error(f"Validate prompt failed: {e}")
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": str(e),
                        "is_valid": False
                    })
                }],
                "isError": True
            }

    async def _handle_route(self, arguments: dict) -> dict:
        """Handle glm_route tool - placeholder for intelligent routing."""
        task = arguments.get("task", "")
        context = arguments.get("context", "")
        files = arguments.get("files", [])
        decide_team = arguments.get("decide_team", True)

        # Simple routing logic based on keywords
        routing = {
            "task": task,
            "recommended_expert": None,
            "reasoning": "",
            "alternative_experts": [],
            "should_spawn_team": False
        }

        task_lower = task.lower()

        # Security-related keywords
        if any(kw in task_lower for kw in ["security", "vulnerability", "exploit", "auth", "credential", "injection", "xss"]):
            routing["recommended_expert"] = "security_analyst"
            routing["reasoning"] = "Task involves security concerns"
        # Architecture-related keywords
        elif any(kw in task_lower for kw in ["architecture", "design", "structure", "tradeoff", "pattern", "scalab"]):
            routing["recommended_expert"] = "architect"
            routing["reasoning"] = "Task involves architectural decisions"
        # Code review keywords
        elif any(kw in task_lower for kw in ["review", "check", "bug", "issue", "quality", "smell"]):
            routing["recommended_expert"] = "code_reviewer"
            routing["reasoning"] = "Task involves code review"
        # Plan review keywords
        elif any(kw in task_lower for kw in ["plan", "verify", "complete", "gap"]):
            routing["recommended_expert"] = "plan_reviewer"
            routing["reasoning"] = "Task involves plan validation"
        # Scope analysis keywords
        elif any(kw in task_lower for kw in ["scope", "requirement", "ambigui", "unclear", "clarify"]):
            routing["recommended_expert"] = "scope_analyst"
            routing["reasoning"] = "Task involves scope clarification"
        else:
            routing["recommended_expert"] = "architect"
            routing["reasoning"] = "Default to architect for general tasks"

        # Set alternatives
        all_experts = ["architect", "code_reviewer", "security_analyst", "plan_reviewer", "scope_analyst"]
        routing["alternative_experts"] = [e for e in all_experts if e != routing["recommended_expert"]]

        # Team spawning decision
        if decide_team:
            routing["should_spawn_team"] = (
                len(files) > 3 or
                any(kw in task_lower for kw in ["parallel", "multiple", "team", "comprehensive"])
            )

        return {
            "content": [{
                "type": "text",
                "text": json.dumps(routing, indent=2)
            }]
        }

    async def _handle_workflow(self, arguments: dict) -> dict:
        """Handle glm_workflow tool - state machine for automated workflows."""
        action = arguments.get("action", "status")

        # Simple state machine - in production would use persistent state
        response = {
            "action": action,
            "status": "acknowledged",
            "message": ""
        }

        if action == "start":
            plan = arguments.get("plan", {})
            response["message"] = "Workflow started"
            response["plan_received"] = bool(plan)
        elif action == "status":
            response["message"] = "No active workflow"
        elif action == "complete_execution":
            response["message"] = f"Execution completed: {arguments.get('result', 'No result')}"
        elif action == "complete_review":
            verdict = arguments.get("verdict", "UNKNOWN")
            issues = arguments.get("issues", [])
            response["message"] = f"Review completed with verdict: {verdict}"
            response["issues_count"] = len(issues)
        elif action == "complete_test":
            passed = arguments.get("passed", False)
            response["message"] = f"Tests {'passed' if passed else 'failed'}"
            response["passed"] = passed
        elif action == "complete_fix":
            response["message"] = f"Fix applied: {arguments.get('description', 'No description')}"
        elif action == "complete_report":
            response["message"] = "Workflow completed"
            response["report"] = arguments.get("report", "")
        else:
            response["message"] = f"Unknown action: {action}"

        return {
            "content": [{
                "type": "text",
                "text": json.dumps(response, indent=2)
            }]
        }

    async def _handle_get_job_result(self, arguments: dict) -> dict:
        """Handle glm_get_job_result tool - retrieve background job status."""
        job_id = arguments.get("job_id", "").strip()

        # Validate job_id
        if not job_id:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": "job_id_required",
                        "message": "job_id parameter is required"
                    }, indent=2)
                }],
                "isError": True
            }

        # Get job
        job = await self.job_manager.get_job(job_id)

        if not job:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": "job_not_found",
                        "message": "Job expired or invalid job_id",
                        "job_id": job_id
                    }, indent=2)
                }],
                "isError": True
            }

        # Build response based on status
        if job.status == JobStatus.PENDING:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "job_id": job.job_id,
                        "status": "pending",
                        "message": "Queued, waiting...",
                        "age_seconds": int(job._age_seconds())
                    }, indent=2)
                }]
            }
        elif job.status == JobStatus.PROCESSING:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "job_id": job.job_id,
                        "status": "processing",
                        "message": "In progress...",
                        "age_seconds": int(job._age_seconds())
                    }, indent=2)
                }]
            }
        elif job.status == JobStatus.COMPLETED:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "job_id": job.job_id,
                        "status": "completed",
                        "result": job.result,
                        "age_seconds": int(job._age_seconds())
                    }, indent=2)
                }]
            }
        elif job.status == JobStatus.FAILED:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "job_id": job.job_id,
                        "status": "failed",
                        "error": job.error or "Unknown error",
                        "age_seconds": int(job._age_seconds())
                    }, indent=2)
                }],
                "isError": True
            }
        elif job.status == JobStatus.TIMEOUT:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "job_id": job.job_id,
                        "status": "timeout",
                        "error": job.error or "Timed out after 300s",
                        "age_seconds": int(job._age_seconds())
                    }, indent=2)
                }],
                "isError": True
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "job_id": job.job_id,
                        "status": job.status.value,
                        "message": "Unknown status"
                    }, indent=2)
                }]
            }


# =============================================================================
# MCP Protocol Handlers
# =============================================================================

# Global variables for server and logger
server: Optional[LLMDelegatorMCPServer] = None
logger: Optional[logging.Logger] = None


async def handle_message(message: dict):
    """Handle incoming MCP message."""
    if logger:
        logger.debug(f"Received message: {message.get('method')}")

    if message.get("method") == "initialize":
        return {
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "llm-delegator",
                    "version": "2.0.0"
                },
                "capabilities": {
                    "tools": {}
                }
            }
        }

    elif message.get("method") == "notifications/initialized":
        # Client notification - no response needed
        return None

    elif message.get("method") == "tools/list":
        if server:
            await server.start()
            return {"result": await server.list_tools()}

    elif message.get("method") == "tools/call":
        if server:
            params = message.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            return {"result": await server.call_tool(name, arguments)}

    else:
        return {
            "error": {
                "code": -32601,
                "message": f"Method not found: {message.get('method')}"
            }
        }


async def main():
    """Main MCP server loop."""
    global server, logger

    # Parse command line arguments
    args = parse_args()

    # Setup logging
    logger = setup_logging(args.debug)

    # Create server instance
    server = LLMDelegatorMCPServer(args, logger)

    if logger:
        logger.info("LLM Delegator MCP Server starting...")

    # Process stdin/stdout (wait for client to initiate handshake)
    try:
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                if not line:
                    break

                message = json.loads(line.strip())
                response = await handle_message(message)

                # Only send response for requests (with id), not notifications
                if "id" in message and response is not None:
                    response["id"] = message["id"]
                    response["jsonrpc"] = "2.0"
                    await send_jsonrpc(response)

            except json.JSONDecodeError as e:
                if logger:
                    logger.error(f"JSON decode error: {e}")
            except Exception as e:
                if logger:
                    logger.error(f"Error processing message: {e}")
    finally:
        if server:
            await server.stop()


async def send_jsonrpc(data: dict):
    """Send JSON-RPC message to stdout."""
    json.dump(data, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        if logger:
            logger.info("Shutting down...")

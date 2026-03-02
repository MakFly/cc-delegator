"""DelegatorServer — lifecycle, expert calls, background jobs."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from providers import (
    BaseProvider,
    BackendConfig,
    ProviderFactory,
    ProviderResponse,
)
from prompt_enhancer import PromptEnhancer, EnhancedPrompt
from prompt_guard import PromptQualityGuard
from context_compressor import ContextCompressor
from job_manager import JobManager, JobStatus, Job
from cache_store import ResponseCache
from expert_memory import ExpertMemory, project_id_from_dir
from claude_memory_bridge import ClaudeMemoryBridge
from cache_metrics import CacheMetrics
from persona_loader import load_personas, load_truthfulness_policy
from tool_registry import build_tool_list
from tool_handlers import ServerServices, UTILITY_HANDLERS, handle_expert_call
from cli import FALLBACK_MODEL

# =============================================================================
# Constants
# =============================================================================
CACHE_CLEANUP_INTERVAL = 600  # 10 minutes

# Load personas at module level
_PROMPTS_DIR = Path(__file__).parent / "prompts"
_PERSONAS = load_personas(_PROMPTS_DIR / "personas")
EXPERT_PROMPTS = {k: v.prompt for k, v in _PERSONAS.items()}
TRUTHFULNESS_POLICY = load_truthfulness_policy(_PROMPTS_DIR)


class DelegatorServer:
    """Multi-provider LLM Delegator MCP Server."""

    def __init__(self, args: argparse.Namespace, logger_instance: logging.Logger):
        self.backend_config = BackendConfig(
            provider=args.provider,
            baseUrl=args.base_url,
            apiKeyEnv="",
            model=args.model,
            apiVersion=args.api_version,
            timeout=args.timeout,
            maxTokens=args.max_tokens,
            api_key=args.api_key,
        )

        self.provider: BaseProvider = ProviderFactory.create(self.backend_config)

        self.enhancer = PromptEnhancer(self.provider)
        self.guard = PromptQualityGuard()
        self.compressor = ContextCompressor(provider=self.provider)

        self.job_manager = JobManager()

        self.response_cache = ResponseCache()
        self.expert_memory = ExpertMemory()
        self.claude_bridge = ClaudeMemoryBridge()
        self.cache_metrics = CacheMetrics(self.response_cache, self.expert_memory)

        self._background_tasks: set[asyncio.Task] = set()
        self._cache_cleanup_task: asyncio.Task | None = None

        self.logger = logger_instance
        self.logger.info("LLM Delegator MCP Server initialized")
        self.logger.info(f"Provider: {self.backend_config.provider}")
        self.logger.info(f"Base URL: {self.backend_config.baseUrl}")
        self.logger.info(f"Model: {self.backend_config.model}")
        self.logger.info(f"API Key: {'configured' if self.provider.api_key else 'missing'}")

        if not self.provider.api_key and self.backend_config.baseUrl not in [
            "http://localhost:11434/v1", "http://localhost:1234/v1", "http://localhost:8000/v1"
        ]:
            raise RuntimeError(
                "API key required but not provided. Use --api-key or set environment variable."
            )

    async def start(self):
        """Initialize the provider, job manager, and cache cleanup."""
        await self.provider.start()
        self.job_manager.start()
        self._cache_cleanup_task = asyncio.create_task(self._cache_cleanup_loop())
        self.logger.info("Provider initialized (cache & memory enabled)")

    async def stop(self):
        """Close the provider, job manager, and cache."""
        if self._cache_cleanup_task:
            self._cache_cleanup_task.cancel()
            try:
                await self._cache_cleanup_task
            except asyncio.CancelledError:
                pass
        for t in self._background_tasks:
            t.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()
        await self.job_manager.stop()
        await self.provider.stop()
        self.response_cache.close()
        self.logger.info("Provider closed (cache & memory stopped)")

    async def call_expert(
        self,
        expert: str,
        task: str,
        mode: str = "advisory",
        context: str = "",
        files: list = None,
        working_dir: str = "",
    ) -> str:
        """Call the LLM with the specified expert prompt."""
        if expert not in EXPERT_PROMPTS:
            raise ValueError(f"Unknown expert: {expert}. Available: {list(EXPERT_PROMPTS.keys())}")

        task = task.strip()
        context = context.strip() if context else ""
        files = files or []

        cached = self.response_cache.get(expert, task, mode, context)
        if cached:
            self.response_cache.record_stat("hit", expert, cached.tokens_used or 0)
            self.logger.info(f"Cache HIT for expert={expert} (hits={cached.hit_count})")
            return cached.response

        expert_prompt = EXPERT_PROMPTS[expert]

        memory_context = ""
        project_id = ""
        claude_context = ""
        if working_dir:
            project_id = project_id_from_dir(working_dir)
            memory_context = self.expert_memory.get_injection(project_id, expert)
            claude_context = self.claude_bridge.get_project_context(working_dir)

        memory_section = f"\n## PRIOR LEARNINGS\n{memory_context}" if memory_context else ""
        claude_section = f"\n## PROJECT CONTEXT (Claude Code)\n{claude_context}" if claude_context else ""

        full_prompt = f"""## TASK
{task}

## MODE
{mode.upper()}

## CONTEXT
{context if context else "No additional context provided."}
{memory_section}
{claude_section}

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
            self._post_expert_call(expert, task, mode, context, response, project_id, working_dir)
            return response.text

        except Exception as e:
            original_model = self.backend_config.model
            if original_model != FALLBACK_MODEL:
                self.logger.warning(
                    f"Primary model {original_model} failed: {e}. "
                    f"Retrying with fallback model {FALLBACK_MODEL}..."
                )
                self.backend_config.model = FALLBACK_MODEL
                self.provider.config.model = FALLBACK_MODEL
                try:
                    response: ProviderResponse = await self.provider.call(
                        system_prompt=expert_prompt,
                        user_prompt=full_prompt
                    )
                    self.logger.info(
                        f"Fallback response received ({FALLBACK_MODEL}): "
                        f"{len(response.text)} characters"
                    )
                    self._post_expert_call(expert, task, mode, context, response, project_id, working_dir)
                    return response.text
                except Exception as fallback_error:
                    self.logger.error(f"Fallback model also failed: {fallback_error}")
                    raise RuntimeError(
                        f"[GLM Expert Error] expert={expert}, "
                        f"primary={original_model} error={e}, "
                        f"fallback={FALLBACK_MODEL} error={fallback_error}"
                    )
                finally:
                    self.backend_config.model = original_model
                    self.provider.config.model = original_model
            else:
                self.logger.error(f"Error calling provider: {e}")
                raise RuntimeError(f"[GLM Expert Error] expert={expert}, error={str(e)}")

    def _post_expert_call(
        self,
        expert: str,
        task: str,
        mode: str,
        context: str,
        response: ProviderResponse,
        project_id: str,
        working_dir: str = "",
    ):
        """Store response in cache, record metrics, extract memory."""
        self.response_cache.put(
            expert, task, mode, context, response.text,
            tokens_used=response.tokens_used,
            model=response.model,
        )
        self.response_cache.record_stat("miss", expert)

        self.cache_metrics.record_prompt_cache(
            response.cache_creation_tokens,
            response.cache_read_tokens,
        )
        if response.cache_read_tokens:
            self.response_cache.record_stat(
                "prompt_cache_hit", expert, response.cache_read_tokens
            )

        if project_id:
            learning = self.expert_memory.extract_learning(response.text)
            if learning:
                self.expert_memory.append(project_id, expert, learning)
                self.logger.debug(f"Memory stored for {expert} @ {project_id}")
                if working_dir:
                    self.claude_bridge.promote_learning(working_dir, expert, learning)

    async def _cache_cleanup_loop(self):
        """Periodic cache cleanup."""
        while True:
            try:
                await asyncio.sleep(CACHE_CLEANUP_INTERVAL)
                removed = self.response_cache.cleanup_expired()
                if removed:
                    self.logger.info(f"Cache cleanup: {removed} expired entries removed")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Cache cleanup error: {e}")

    def _should_use_background_mode(self, task: str, context: str, files: list) -> bool:
        """Determine if background mode should be used based on context size."""
        from tool_handlers import BACKGROUND_MODE_THRESHOLD
        total_chars = len(task) + len(context)
        return total_chars >= BACKGROUND_MODE_THRESHOLD

    async def _process_background_job(self, job: Job) -> None:
        """Process a background job in async context."""
        try:
            await self.job_manager.update_job(job.job_id, JobStatus.PROCESSING)

            task = job.task
            context = job.context

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

            bg_working_dir = job.metadata.get("working_dir", "")
            result = await self.call_expert(job.expert, task, job.mode, context, job.files, bg_working_dir)

            await self.job_manager.update_job(
                job.job_id, JobStatus.COMPLETED, result=result
            )

        except Exception as e:
            self.logger.error(f"Background job {job.job_id} failed: {e}")
            await self.job_manager.update_job(
                job.job_id, JobStatus.FAILED, error=str(e)
            )

    async def list_tools(self):
        """List available MCP tools."""
        return {"tools": build_tool_list(_PERSONAS, self.backend_config.model)}

    @property
    def _services(self) -> ServerServices:
        """Build DI container for tool handlers."""
        return ServerServices(
            provider=self.provider,
            enhancer=self.enhancer,
            guard=self.guard,
            compressor=self.compressor,
            job_manager=self.job_manager,
            response_cache=self.response_cache,
            expert_memory=self.expert_memory,
            cache_metrics=self.cache_metrics,
            claude_bridge=self.claude_bridge,
            logger=self.logger,
            backend_config=self.backend_config,
            background_tasks=self._background_tasks,
            call_expert=self.call_expert,
            spawn_background_job=self._process_background_job,
        )

    async def call_tool(self, name: str, arguments: dict):
        """Call an MCP tool."""
        if not name.startswith("glm_"):
            raise ValueError(f"Unknown tool: {name}")

        tool_name = name[4:]

        if tool_name in UTILITY_HANDLERS:
            return await UTILITY_HANDLERS[tool_name](arguments, self._services)

        return await handle_expert_call(tool_name, arguments, self._services, _PERSONAS)


# Backward compatibility alias
LLMDelegatorMCPServer = DelegatorServer

#!/usr/bin/env python3
"""
Prompt Enhancer - Uses LLM to improve prompts before expert delegation.

This module provides a prompt enhancement system similar to Repo Prompt / PromptPerfect,
using an LLM to restructure and clarify prompts before sending them to expert agents.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

from providers import BaseProvider, ProviderResponse

logger = logging.getLogger("glm-delegator.prompt_enhancer")


@dataclass
class EnhancedPrompt:
    """Result of prompt enhancement."""
    original_task: str
    enhanced_task: str
    added_context: str
    suggestions: list[str]
    confidence: float  # 0.0 - 1.0


ENHANCER_SYSTEM_PROMPT = """# Prompt Enhancer

You are a prompt engineering specialist. Your job is to improve prompts before they are sent to expert AI agents.

## Your Task

Given a raw prompt, enhance it by:
1. **Clarifying intent** - Remove ambiguity, be specific
2. **Adding structure** - Organize into clear sections (TASK, CONTEXT, CONSTRAINTS)
3. **Identifying gaps** - What information is missing that would help the expert?
4. **Removing hallucination signals** - Replace "probably", "I think" with clear statements or questions

## Enhancement Rules

1. **NEVER invent information** - If something is unclear, mark it as [CLARIFICATION NEEDED: ...]
2. **Preserve original intent** - Don't change what the user wants, just make it clearer
3. **Add helpful structure** - Use markdown sections
4. **Suggest context** - List what additional context would help
5. **Keep it concise** - Don't over-engineer the prompt
6. **State unknowns explicitly** - If data is missing, keep unknowns explicit instead of filling gaps
7. **Require verification for external/current facts** - If the task depends on latest/current external info, include a suggestion to verify via web search before concluding

## Output Format

Return ONLY valid JSON (no markdown code blocks, no explanation):
```json
{
  "enhanced_task": "The improved task description with clear structure",
  "added_context": "Any context you inferred or structured",
  "suggestions": ["List of suggested improvements for the user"],
  "confidence": 0.85
}
```

The confidence score (0.0-1.0) reflects how much you improved the prompt.
- 1.0: Significant improvement, clear structure added
- 0.7-0.9: Good improvement, minor clarifications
- 0.5-0.7: Moderate improvement
- 0.0-0.5: Little improvement needed or possible
"""


class PromptEnhancer:
    """Uses LLM to enhance prompts before expert delegation."""

    def __init__(self, provider: BaseProvider):
        self.provider = provider

    async def enhance(
        self,
        task: str,
        context: str = "",
        target_expert: str = "",
        files: Optional[list[str]] = None
    ) -> EnhancedPrompt:
        """
        Enhance a prompt using LLM.

        Args:
            task: Original task description
            context: Additional context provided
            target_expert: Which expert will receive this (for context)
            files: Files mentioned

        Returns:
            EnhancedPrompt with improved content
        """
        files = files or []

        user_prompt = f"""## Original Task
{task}

## Provided Context
{context if context else "None provided"}

## Target Expert
{target_expert if target_expert else "Not specified"}

## Files Mentioned
{chr(10).join(f"- {f}" for f in files) if files else "None"}

---

Please enhance this prompt following the rules in your system prompt. Return only valid JSON."""

        logger.info(f"Enhancing prompt for expert: {target_expert}")

        try:
            response: ProviderResponse = await self.provider.call(
                system_prompt=ENHANCER_SYSTEM_PROMPT,
                user_prompt=user_prompt
            )

            # Parse JSON response
            result_text = response.text.strip()

            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                lines = result_text.split("\n")
                # Remove first and last line if they're code block markers
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                result_text = "\n".join(lines).strip()

            data = json.loads(result_text)

            enhanced = EnhancedPrompt(
                original_task=task,
                enhanced_task=data.get("enhanced_task", task),
                added_context=data.get("added_context", ""),
                suggestions=data.get("suggestions", []),
                confidence=min(1.0, max(0.0, data.get("confidence", 0.5)))
            )

            logger.info(f"Prompt enhanced with confidence: {enhanced.confidence}")
            return enhanced

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse enhancer response: {e}")
            # Fallback: return original if parsing fails
            return EnhancedPrompt(
                original_task=task,
                enhanced_task=task,
                added_context="",
                suggestions=["Failed to parse enhancer response - using original prompt"],
                confidence=0.0
            )
        except Exception as e:
            logger.error(f"Error during prompt enhancement: {e}")
            return EnhancedPrompt(
                original_task=task,
                enhanced_task=task,
                added_context="",
                suggestions=[f"Enhancement error: {str(e)}"],
                confidence=0.0
            )

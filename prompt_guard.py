#!/usr/bin/env python3
"""
Prompt Quality Guard - Static validation without LLM calls.

This module provides static validation rules to catch common issues
before prompts are sent to experts (file existence, hallucination signals, etc.).
"""

import os
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("glm-delegator.prompt_guard")


@dataclass
class ValidationResult:
    """Result of prompt validation."""
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class PromptQualityGuard:
    """Validates prompts using static rules (no LLM)."""

    # Patterns that suggest uncertainty or potential hallucination
    HALLUCINATION_PATTERNS = [
        (r"\bprobably\b", "uncertainty signal"),
        (r"\bI think\b", "uncertainty signal"),
        (r"\bshould be\b", "assumption signal"),
        (r"\bmaybe\b", "uncertainty signal"),
        (r"\bapparently\b", "uncertainty signal"),
        (r"\bsomewhere\b", "vague location"),
        (r"\bsomehow\b", "vague mechanism"),
        (r"\bsomething like\b", "vague reference"),
        (r"\bI guess\b", "uncertainty signal"),
        (r"\bpossibly\b", "uncertainty signal"),
        (r"\blikely\b", "uncertainty signal"),
    ]

    # Minimum task length for meaningful prompts
    MIN_TASK_LENGTH = 10
    WEBSEARCH_SIGNAL_PATTERNS = [
        r"\blatest\b",
        r"\bcurrent\b",
        r"\btoday\b",
        r"\brecent\b",
        r"\bup[- ]to[- ]date\b",
        r"\bnews\b",
        r"\bprice\b",
        r"\bversion\b",
        r"\bceo\b",
        r"\bpresident\b",
    ]

    def validate(
        self,
        task: str,
        context: str = "",
        files: Optional[list[str]] = None,
        working_dir: Optional[str] = None
    ) -> ValidationResult:
        """
        Validate a prompt using static rules.

        Args:
            task: The task description to validate
            context: Additional context provided
            files: List of file paths to verify
            working_dir: Base directory for relative file paths

        Returns:
            ValidationResult with warnings, errors, and suggestions
        """
        warnings = []
        errors = []
        suggestions = []

        files = files or []
        # WARNING: os.getcwd() fallback may not match the user's intended base directory
        # in server contexts. Callers should provide an explicit working_dir.
        working_dir = working_dir or os.getcwd()

        # 1. Task validation
        if not task or not task.strip():
            errors.append("Task description is empty")
        elif len(task.strip()) < self.MIN_TASK_LENGTH:
            warnings.append(f"Task description is very short (<{self.MIN_TASK_LENGTH} chars)")
            suggestions.append("Provide more detail about what you want to accomplish")

        # 2. Context completeness
        if not context or not context.strip():
            warnings.append("No context provided")
            suggestions.append("Include relevant code snippets or file contents for better results")
        elif len(context.strip()) < 50:
            warnings.append("Context is minimal - more context may improve results")

        # 3. File validation
        if files:
            for f in files:
                # Skip URLs and special paths
                if f.startswith(("http://", "https://", "file://", "<")):
                    continue

                # Handle relative vs absolute paths
                full_path = f if os.path.isabs(f) else os.path.join(working_dir, f)
                full_path = os.path.realpath(full_path)

                # Prevent path traversal outside working_dir
                real_working_dir = os.path.realpath(working_dir)
                if not full_path.startswith(real_working_dir + os.sep) and full_path != real_working_dir:
                    errors.append(f"Path traversal detected: {f} resolves outside working directory")
                    continue

                if not os.path.exists(full_path):
                    errors.append(f"File not found: {f}")
                    suggestions.append(f"Verify the file path '{f}' exists and is accessible")

        # 4. Hallucination/uncertainty signals
        combined_text = (task + " " + context).lower()
        detected_patterns = []

        for pattern, description in self.HALLUCINATION_PATTERNS:
            matches = re.findall(pattern, combined_text)
            if matches:
                detected_patterns.append(f"'{matches[0]}' ({description})")

        if detected_patterns:
            warnings.append(f"Uncertainty signals detected: {', '.join(detected_patterns[:3])}")
            suggestions.append("Replace uncertain language with specific statements or explicit questions")

        # 5. Task clarity checks
        if "?" in task and task.count("?") > 2:
            warnings.append("Multiple questions in task - consider splitting into separate requests")

        if task.strip().endswith("..."):
            warnings.append("Task appears incomplete (ends with '...')")

        # 6. Files without context warning
        if files and not context:
            suggestions.append("Files are mentioned but no context provided - include relevant file contents")

        # 7. External/current fact signal
        websearch_hits = [
            p for p in self.WEBSEARCH_SIGNAL_PATTERNS
            if re.search(p, combined_text, re.IGNORECASE)
        ]
        if websearch_hits:
            warnings.append("Task may require external or up-to-date verification")
            suggestions.append(
                "If context is insufficient, run a targeted web search and cite sources before final conclusions"
            )

        logger.info(
            f"Validation complete: valid={len(errors) == 0}, "
            f"errors={len(errors)}, warnings={len(warnings)}"
        )

        return ValidationResult(
            is_valid=len(errors) == 0,
            warnings=warnings,
            errors=errors,
            suggestions=suggestions
        )

    def quick_check(self, task: str) -> bool:
        """
        Quick validation check - returns True if task passes basic checks.

        Args:
            task: The task to quickly validate

        Returns:
            True if task passes basic validation
        """
        if not task or len(task.strip()) < self.MIN_TASK_LENGTH:
            return False

        # Check for excessive uncertainty signals
        combined = task.lower()
        uncertainty_count = sum(
            1
            for pattern, _ in self.HALLUCINATION_PATTERNS[:5]
            if re.search(pattern, combined, re.IGNORECASE)
        )

        return uncertainty_count < 3

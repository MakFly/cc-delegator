"""Tests for prompt_guard module."""

import os
import pytest
import tempfile

from prompt_guard import PromptQualityGuard, ValidationResult


@pytest.fixture
def guard():
    """PromptQualityGuard instance."""
    return PromptQualityGuard()


class TestPromptQualityGuard:

    def test_validate_empty_task(self, guard):
        """Test validation fails for empty task."""
        result = guard.validate("")

        assert not result.is_valid
        assert any("empty" in e.lower() for e in result.errors)

    def test_validate_short_task(self, guard):
        """Test validation warns for very short tasks."""
        result = guard.validate("Fix it")

        assert result.is_valid  # No errors, just warnings
        assert any("short" in w.lower() for w in result.warnings)

    def test_validate_good_task(self, guard):
        """Test validation passes for good task."""
        result = guard.validate(
            "Review the authentication logic in src/auth/login.py for security vulnerabilities",
            context="This file handles user authentication"
        )

        assert result.is_valid
        assert len(result.errors) == 0

    def test_validate_no_context_warning(self, guard):
        """Test warning when no context provided."""
        result = guard.validate("This is a good task description")

        assert result.is_valid
        assert any("context" in w.lower() for w in result.warnings)

    def test_validate_file_exists(self, guard):
        """Test validation of existing files."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
            f.write(b"# test file")
            temp_path = f.name

        try:
            result = guard.validate(
                "Review this file",
                files=[temp_path]
            )

            assert result.is_valid
            assert not any("not found" in e for e in result.errors)
        finally:
            os.unlink(temp_path)

    def test_validate_file_not_found(self, guard):
        """Test validation fails for non-existent files."""
        result = guard.validate(
            "Review this file",
            files=["/nonexistent/path/to/file.py"]
        )

        assert not result.is_valid
        assert any("not found" in e.lower() for e in result.errors)

    def test_validate_hallucination_patterns(self, guard):
        """Test detection of uncertainty/hallucination signals."""
        result = guard.validate(
            "I think this probably works somehow",
            context="Maybe there's a bug somewhere"
        )

        assert result.is_valid  # Warnings, not errors
        assert any("uncertainty" in w.lower() for w in result.warnings)

    def test_validate_multiple_questions(self, guard):
        """Test warning for multiple questions in task."""
        result = guard.validate(
            "How do I fix this? Should I refactor? What's the best approach?"
        )

        assert result.is_valid
        assert any("multiple questions" in w.lower() for w in result.warnings)

    def test_validate_incomplete_task(self, guard):
        """Test warning for incomplete task (ends with ...)."""
        result = guard.validate("I need to...")

        assert result.is_valid
        assert any("incomplete" in w.lower() for w in result.warnings)

    def test_validate_files_without_context(self, guard):
        """Test suggestion when files mentioned without context."""
        result = guard.validate(
            "Review the code",
            files=["/path/to/file.py"]
        )

        assert any("context" in s.lower() for s in result.suggestions)

    def test_validate_working_dir(self, guard):
        """Test validation with custom working directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file in the temp directory
            test_file = os.path.join(tmpdir, "test.py")
            with open(test_file, "w") as f:
                f.write("# test")

            result = guard.validate(
                "Review this file",
                files=["test.py"],
                working_dir=tmpdir
            )

            assert result.is_valid

    def test_validate_url_files_skipped(self, guard):
        """Test that URLs and special paths are skipped."""
        result = guard.validate(
            "Review these resources",
            files=[
                "https://example.com/code.py",
                "file:///local/file.py",
                "<generated content>"
            ]
        )

        # Should not fail even though these aren't real local files
        assert result.is_valid

    def test_quick_check_valid_task(self, guard):
        """Test quick check passes for valid tasks."""
        assert guard.quick_check("Review the authentication module for security issues")
        assert guard.quick_check("Implement a new feature for user management")

    def test_quick_check_fails_short_task(self, guard):
        """Test quick check fails for short tasks."""
        assert not guard.quick_check("Fix")
        assert not guard.quick_check("")

    def test_quick_check_fails_uncertain_task(self, guard):
        """Test quick check fails for very uncertain tasks."""
        # Task with multiple uncertainty signals
        assert not guard.quick_check("I think probably maybe this somehow works")

    def test_quick_check_fails_uncertain_task_mixed_case(self, guard):
        """Test quick check catches uncertainty signals with mixed casing."""
        assert not guard.quick_check("i ThInK PROBABLY this MAYBE works")

    def test_quick_check_passes_clear_task(self, guard):
        """Test quick check stays permissive for a clear request."""
        assert guard.quick_check("Review authentication flow and list concrete vulnerabilities")

    def test_validate_minimal_context_warning(self, guard):
        """Test warning for minimal context."""
        result = guard.validate(
            "Review the code",
            context="Yes"  # Very short context
        )

        assert any("minimal" in w.lower() for w in result.warnings)

    def test_validate_suggests_websearch_for_latest_info(self, guard):
        """Test suggestion when task likely needs up-to-date external info."""
        result = guard.validate(
            "What is the latest version and current price of this provider API?"
        )

        assert any("up-to-date" in w.lower() or "external" in w.lower() for w in result.warnings)
        assert any("web search" in s.lower() for s in result.suggestions)


class TestValidationResult:

    def test_dataclass_fields(self):
        """Test ValidationResult has all required fields."""
        result = ValidationResult(
            is_valid=True,
            warnings=["Warning 1"],
            errors=["Error 1"],
            suggestions=["Suggestion 1"]
        )

        assert result.is_valid is True
        assert result.warnings == ["Warning 1"]
        assert result.errors == ["Error 1"]
        assert result.suggestions == ["Suggestion 1"]

    def test_empty_result(self):
        """Test ValidationResult with defaults."""
        result = ValidationResult(is_valid=True)

        assert result.warnings == []
        assert result.errors == []
        assert result.suggestions == []

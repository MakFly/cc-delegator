"""Tests for claude_memory_bridge.py — Claude Code ↔ GLM memory bridge."""

import pytest

from claude_memory_bridge import ClaudeMemoryBridge, encode_working_dir


# ===========================================================================
# TestEncodeWorkingDir
# ===========================================================================

class TestEncodeWorkingDir:

    def test_simple_path(self):
        assert encode_working_dir("/home/kev/foo") == "home-kev-foo"

    def test_deep_path(self):
        assert encode_working_dir("/home/kev/Documents/lab/project") == "home-kev-Documents-lab-project"

    def test_matches_real_convention(self):
        """The encoding should match Claude Code's actual directory names."""
        # /home/kev → -home-kev (leading slash produces leading dash, stripped)
        result = encode_working_dir("/home/kev")
        assert result == "home-kev"
        assert "/" not in result


# ===========================================================================
# TestGetProjectContext
# ===========================================================================

class TestGetProjectContext:

    @pytest.fixture
    def bridge(self, tmp_path):
        return ClaudeMemoryBridge(projects_dir=str(tmp_path))

    def test_empty_working_dir(self, bridge):
        assert bridge.get_project_context("") == ""

    def test_nonexistent_project(self, bridge):
        """Graceful no-op when project directory doesn't exist."""
        result = bridge.get_project_context("/nonexistent/path")
        assert result == ""

    def test_topic_files(self, bridge, tmp_path):
        encoded = encode_working_dir("/home/kev/myproject")
        memory_dir = tmp_path / encoded / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "patterns.md").write_text("Use factory pattern")
        (memory_dir / "debugging.md").write_text("Check logs first")

        result = bridge.get_project_context("/home/kev/myproject")
        assert "patterns" in result
        assert "Use factory pattern" in result
        assert "debugging" in result
        assert "Check logs first" in result

    def test_memory_md(self, bridge, tmp_path):
        encoded = encode_working_dir("/home/kev/myproject")
        memory_dir = tmp_path / encoded / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "MEMORY.md").write_text("Key insight: use bun not npm")

        result = bridge.get_project_context("/home/kev/myproject")
        assert "Key insight: use bun not npm" in result
        assert "Project Memory" in result

    def test_claude_md(self, bridge, tmp_path):
        """Reads CLAUDE.md from working_dir (not from projects dir)."""
        working_dir = tmp_path / "workdir"
        working_dir.mkdir()
        (working_dir / "CLAUDE.md").write_text("# Conventions\nUse TypeScript")

        result = bridge.get_project_context(str(working_dir))
        assert "Conventions" in result
        assert "Use TypeScript" in result

    def test_claude_md_truncation(self, bridge, tmp_path):
        working_dir = tmp_path / "workdir"
        working_dir.mkdir()
        (working_dir / "CLAUDE.md").write_text("x" * 2000)

        result = bridge.get_project_context(str(working_dir))
        assert "[...truncated]" in result

    def test_total_cap(self, bridge, tmp_path):
        """Total output is capped at MAX_PROJECT_CONTEXT_CHARS."""
        encoded = encode_working_dir("/home/kev/bigproject")
        memory_dir = tmp_path / encoded / "memory"
        memory_dir.mkdir(parents=True)
        # Write enough content to exceed the cap
        (memory_dir / "big.md").write_text("A" * 2000)

        result = bridge.get_project_context("/home/kev/bigproject")
        assert len(result) <= 1500 + len("\n[...truncated]") + 10  # small margin

    def test_graceful_on_read_error(self, bridge, tmp_path):
        """Doesn't crash if a file can't be read."""
        encoded = encode_working_dir("/home/kev/myproject")
        memory_dir = tmp_path / encoded / "memory"
        memory_dir.mkdir(parents=True)
        # Create a directory with .md name (will fail to read as file)
        (memory_dir / "broken.md").mkdir()

        result = bridge.get_project_context("/home/kev/myproject")
        # Should not raise, just skip the broken entry
        assert isinstance(result, str)


# ===========================================================================
# TestPromoteLearning
# ===========================================================================

class TestPromoteLearning:

    @pytest.fixture
    def bridge(self, tmp_path):
        return ClaudeMemoryBridge(projects_dir=str(tmp_path))

    def test_write_learning(self, bridge, tmp_path):
        result = bridge.promote_learning("/home/kev/proj", "architect", "Use event sourcing for audit trail")
        assert result is True

        encoded = encode_working_dir("/home/kev/proj")
        target = tmp_path / encoded / "memory" / "glm-experts.md"
        assert target.exists()
        content = target.read_text()
        assert "[architect]" in content
        assert "Use event sourcing for audit trail" in content

    def test_dedup(self, bridge):
        bridge.promote_learning("/home/kev/proj", "architect", "Use event sourcing")
        result = bridge.promote_learning("/home/kev/proj", "architect", "Use event sourcing")
        assert result is False

    def test_auto_create_dir(self, bridge, tmp_path):
        """Directories are created automatically."""
        bridge.promote_learning("/home/kev/newproj", "security_analyst", "Enable CORS carefully")
        encoded = encode_working_dir("/home/kev/newproj")
        assert (tmp_path / encoded / "memory" / "glm-experts.md").exists()

    def test_empty_inputs(self, bridge):
        assert bridge.promote_learning("", "architect", "learning") is False
        assert bridge.promote_learning("/path", "", "learning") is False
        assert bridge.promote_learning("/path", "architect", "") is False
        assert bridge.promote_learning("/path", "architect", "   ") is False

    def test_format_validation(self, bridge, tmp_path):
        """Entry has correct date + expert format."""
        bridge.promote_learning("/home/kev/proj", "code_reviewer", "Add null checks")
        encoded = encode_working_dir("/home/kev/proj")
        content = (tmp_path / encoded / "memory" / "glm-experts.md").read_text()
        # Format: ## YYYY-MM-DD HH:MM UTC [expert]
        assert "## " in content
        assert "UTC [code_reviewer]" in content
        assert "Add null checks" in content

    def test_multiple_experts(self, bridge, tmp_path):
        """Multiple learnings from different experts go to same file."""
        bridge.promote_learning("/home/kev/proj", "architect", "Learning A")
        bridge.promote_learning("/home/kev/proj", "security_analyst", "Learning B")

        encoded = encode_working_dir("/home/kev/proj")
        content = (tmp_path / encoded / "memory" / "glm-experts.md").read_text()
        assert "[architect]" in content
        assert "[security_analyst]" in content
        assert "Learning A" in content
        assert "Learning B" in content

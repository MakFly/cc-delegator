"""Tests for expert_memory.py — per-project expert memory."""

import pytest

from expert_memory import ExpertMemory, project_id_from_dir


class TestProjectId:

    def test_deterministic(self):
        assert project_id_from_dir("/home/user/project") == project_id_from_dir("/home/user/project")

    def test_different_dirs_different_ids(self):
        assert project_id_from_dir("/a") != project_id_from_dir("/b")

    def test_length(self):
        assert len(project_id_from_dir("/foo")) == 12


class TestExpertMemory:

    @pytest.fixture
    def mem(self, tmp_path):
        return ExpertMemory(base_dir=str(tmp_path / "memory"))

    def test_load_empty(self, mem):
        assert mem.load("proj1", "architect") == ""

    def test_append_and_load(self, mem):
        mem.append("proj1", "architect", "Use dependency injection for services")
        content = mem.load("proj1", "architect")
        assert "Use dependency injection for services" in content
        assert "## 20" in content  # Date header starts with ## 20XX

    def test_append_multiple(self, mem):
        mem.append("proj1", "architect", "Learning 1")
        mem.append("proj1", "architect", "Learning 2")
        content = mem.load("proj1", "architect")
        assert "Learning 1" in content
        assert "Learning 2" in content

    def test_different_experts_isolated(self, mem):
        mem.append("proj1", "architect", "arch stuff")
        mem.append("proj1", "code_reviewer", "review stuff")
        assert "arch stuff" in mem.load("proj1", "architect")
        assert "arch stuff" not in mem.load("proj1", "code_reviewer")

    def test_different_projects_isolated(self, mem):
        mem.append("proj1", "architect", "proj1 stuff")
        mem.append("proj2", "architect", "proj2 stuff")
        assert "proj1 stuff" in mem.load("proj1", "architect")
        assert "proj1 stuff" not in mem.load("proj2", "architect")

    def test_get_injection_empty(self, mem):
        assert mem.get_injection("proj1", "architect") == ""

    def test_get_injection_truncated(self, mem):
        # Write more than MAX_INJECTION_CHARS
        for i in range(200):
            mem.append("proj1", "architect", f"Learning number {i}: " + "x" * 50)
        injection = mem.get_injection("proj1", "architect")
        assert len(injection) <= 2000

    def test_stats_empty(self, mem):
        stats = mem.stats()
        assert stats["projects"] == 0
        assert stats["total_entries"] == 0

    def test_stats_with_data(self, mem):
        mem.append("proj1", "architect", "L1")
        mem.append("proj1", "architect", "L2")
        mem.append("proj1", "code_reviewer", "L3")
        mem.append("proj2", "security_analyst", "L4")
        stats = mem.stats()
        assert stats["projects"] == 2
        assert stats["total_entries"] == 4
        assert stats["by_expert"]["architect"] == 2
        assert stats["by_expert"]["code_reviewer"] == 1


class TestExtractLearning:

    def test_recommendation(self):
        resp = "Some analysis.\n**Recommendation:** Use Redis for caching layer.\nMore text."
        assert ExpertMemory.extract_learning(resp) == "Use Redis for caching layer."

    def test_verdict(self):
        resp = "## Review\nVerdict: APPROVE — code is clean and well-tested."
        assert "APPROVE" in ExpertMemory.extract_learning(resp)

    def test_bottom_line(self):
        resp = "Bottom line: Migrate to PostgreSQL 16 for better performance."
        assert "PostgreSQL" in ExpertMemory.extract_learning(resp)

    def test_risk_rating(self):
        resp = "Risk Rating: HIGH — SQL injection in user input handler."
        assert "HIGH" in ExpertMemory.extract_learning(resp)

    def test_no_match(self):
        resp = "Just some generic text without any heading patterns."
        assert ExpertMemory.extract_learning(resp) is None

    def test_too_short(self):
        resp = "Recommendation: ok"
        assert ExpertMemory.extract_learning(resp) is None

"""Tests for tool_registry.py."""

from persona_loader import Persona
from tool_registry import build_tool_list, EXPERT_SCHEMA, UTILITY_TOOLS


class TestBuildToolList:

    def _fake_personas(self):
        return {
            "architect": Persona(key="architect", name="Architect", prompt="# Architect\n"),
            "code_reviewer": Persona(key="code_reviewer", name="Code Reviewer", prompt="# Code Reviewer\n"),
            "security_analyst": Persona(key="security_analyst", name="Security Analyst", prompt="# Security Analyst\n"),
            "plan_reviewer": Persona(key="plan_reviewer", name="Plan Reviewer", prompt="# Plan Reviewer\n"),
            "scope_analyst": Persona(key="scope_analyst", name="Scope Analyst", prompt="# Scope Analyst\n"),
        }

    def test_returns_eleven_tools(self):
        tools = build_tool_list(self._fake_personas(), "glm-5")
        assert len(tools) == 11

    def test_expert_tools_prefixed(self):
        tools = build_tool_list(self._fake_personas(), "glm-5")
        expert_tools = [t for t in tools if t["name"] not in {u["name"] for u in UTILITY_TOOLS}]
        assert len(expert_tools) == 5
        for t in expert_tools:
            assert t["name"].startswith("glm_")

    def test_expert_schema_has_required_task(self):
        assert "task" in EXPERT_SCHEMA["required"]
        assert "task" in EXPERT_SCHEMA["properties"]

    def test_utility_tools_count(self):
        assert len(UTILITY_TOOLS) == 6

    def test_model_display_in_description(self):
        tools = build_tool_list(self._fake_personas(), "my-model")
        expert_tools = [t for t in tools if t["description"].startswith("Delegate to the")]
        assert len(expert_tools) == 5
        for t in expert_tools:
            assert "my-model" in t["description"]

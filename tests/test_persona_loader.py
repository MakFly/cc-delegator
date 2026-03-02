"""Tests for persona_loader.py."""

import pytest

from persona_loader import Persona, load_personas, load_truthfulness_policy


class TestLoadPersonas:

    def test_loads_five_personas(self, tmp_path):
        d = tmp_path / "personas"
        d.mkdir()
        for name in ["architect", "code_reviewer", "security_analyst", "plan_reviewer", "scope_analyst"]:
            (d / f"{name}.md").write_text(f"# {name.replace('_', ' ').title()}\n\nContent for {name}.")
        personas = load_personas(d)
        assert len(personas) == 5

    def test_parses_title(self, tmp_path):
        d = tmp_path / "personas"
        d.mkdir()
        (d / "architect.md").write_text("# Architect\n\nSome content.")
        personas = load_personas(d)
        assert personas["architect"].name == "Architect"

    def test_key_is_stem(self, tmp_path):
        d = tmp_path / "personas"
        d.mkdir()
        (d / "code_reviewer.md").write_text("# Code Reviewer\n\nContent.")
        personas = load_personas(d)
        assert personas["code_reviewer"].key == "code_reviewer"

    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_personas(tmp_path / "nonexistent")

    def test_empty_file_skipped(self, tmp_path):
        d = tmp_path / "personas"
        d.mkdir()
        (d / "empty.md").write_text("")
        (d / "real.md").write_text("# Real\n\nContent.")
        personas = load_personas(d)
        assert len(personas) == 1
        assert "real" in personas

    def test_prompt_contains_full_content(self, tmp_path):
        d = tmp_path / "personas"
        d.mkdir()
        content = "# Expert\n\n## Section\n\nDetailed content here."
        (d / "expert.md").write_text(content)
        personas = load_personas(d)
        assert personas["expert"].prompt == content


class TestLoadFromProjectDir:

    def test_loads_real_personas(self):
        from pathlib import Path
        personas_dir = Path(__file__).parent.parent / "prompts" / "personas"
        if not personas_dir.exists():
            pytest.skip("prompts/personas/ not found")
        personas = load_personas(personas_dir)
        assert set(personas.keys()) == {"architect", "code_reviewer", "security_analyst", "plan_reviewer", "scope_analyst"}


class TestLoadTruthfulnessPolicy:

    def test_loads_policy(self, tmp_path):
        (tmp_path / "truthfulness_policy.md").write_text("## Policy\n\nContent.")
        result = load_truthfulness_policy(tmp_path)
        assert "Policy" in result

    def test_missing_policy_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_truthfulness_policy(tmp_path)

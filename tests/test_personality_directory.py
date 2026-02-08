"""Tests for directory-based personality format and context documents."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from radar.agent import (
    DEFAULT_PERSONALITY,
    _get_personality_context_metadata,
    load_personality,
)


@pytest.fixture
def personalities_dir(isolated_data_dir):
    """Create and return the personalities directory."""
    d = isolated_data_dir / "personalities"
    d.mkdir(exist_ok=True)
    return d


def _create_flat_personality(personalities_dir: Path, name: str, content: str | None = None) -> Path:
    """Create a flat .md personality file."""
    if content is None:
        content = f"# {name.title()}\n\nA personality called {name}."
    f = personalities_dir / f"{name}.md"
    f.write_text(content)
    return f


def _create_dir_personality(
    personalities_dir: Path,
    name: str,
    content: str | None = None,
    context_files: dict[str, str] | None = None,
    scripts: list[str] | None = None,
    assets: list[str] | None = None,
) -> Path:
    """Create a directory-based personality with optional context/scripts/assets."""
    d = personalities_dir / name
    d.mkdir(parents=True, exist_ok=True)

    if content is None:
        content = f"# {name.title()}\n\nA directory personality called {name}."
    (d / "PERSONALITY.md").write_text(content)

    if context_files:
        ctx_dir = d / "context"
        ctx_dir.mkdir(exist_ok=True)
        for fname, fcontent in context_files.items():
            (ctx_dir / fname).write_text(fcontent)

    if scripts:
        s_dir = d / "scripts"
        s_dir.mkdir(exist_ok=True)
        for s in scripts:
            (s_dir / s).write_text(f"#!/bin/bash\necho {s}")

    if assets:
        a_dir = d / "assets"
        a_dir.mkdir(exist_ok=True)
        for a in assets:
            (a_dir / a).write_text(f"Asset: {a}")

    return d


# ===== load_personality =====


class TestLoadPersonality:
    def test_load_flat_personality(self, personalities_dir):
        """Existing flat .md format still works."""
        _create_flat_personality(personalities_dir, "flat-test", "# Flat\n\nFlat body.")
        content = load_personality("flat-test")
        assert "# Flat" in content
        assert "Flat body" in content

    def test_load_directory_personality(self, personalities_dir):
        """Directory-based personality loads PERSONALITY.md content."""
        _create_dir_personality(personalities_dir, "dir-test", "# Dir\n\nDir body.")
        content = load_personality("dir-test")
        assert "# Dir" in content
        assert "Dir body" in content

    def test_resolution_order_directory_before_flat(self, personalities_dir):
        """Directory-based personality is checked before flat .md file."""
        _create_flat_personality(personalities_dir, "both", "# Flat Version")
        _create_dir_personality(personalities_dir, "both", "# Directory Version")

        content = load_personality("both")
        assert "# Directory Version" in content

    def test_falls_back_to_default(self, personalities_dir):
        """Missing personality falls back to default."""
        content = load_personality("nonexistent")
        assert "Radar" in content  # DEFAULT_PERSONALITY mentions Radar

    def test_explicit_path(self, tmp_path, personalities_dir):
        """Explicit file path takes precedence."""
        f = tmp_path / "custom.md"
        f.write_text("# Explicit\n\nExplicit path personality.")
        content = load_personality(str(f))
        assert "# Explicit" in content

    def test_directory_scripts_assets_noted(self, personalities_dir):
        """Directory personality notes available scripts and assets."""
        _create_dir_personality(
            personalities_dir, "resource-test",
            content="# Resource Test",
            scripts=["helper.sh"],
            assets=["template.txt"],
        )
        content = load_personality("resource-test")
        assert "Scripts available at:" in content
        assert "Assets available at:" in content

    def test_directory_no_extras_no_resources_section(self, personalities_dir):
        """No resources section when no scripts/assets dirs exist."""
        _create_dir_personality(personalities_dir, "bare-dir", "# Bare")
        content = load_personality("bare-dir")
        assert "Available Resources" not in content


# ===== _get_personality_context_metadata =====


class TestGetPersonalityContextMetadata:
    def test_returns_none_for_flat_personality(self, personalities_dir):
        """Flat personality has no context metadata."""
        _create_flat_personality(personalities_dir, "flat")
        result = _get_personality_context_metadata("flat")
        assert result is None

    def test_returns_none_when_no_context_dir(self, personalities_dir):
        """Directory personality without context/ returns None."""
        _create_dir_personality(personalities_dir, "no-ctx")
        result = _get_personality_context_metadata("no-ctx")
        assert result is None

    def test_context_frontmatter_parsing(self, personalities_dir):
        """Description extracted from YAML front matter."""
        _create_dir_personality(
            personalities_dir, "ctx-test",
            context_files={
                "standards.md": "---\ndescription: Coding standards and conventions\n---\n# Standards\n\nDetailed content.",
            },
        )
        result = _get_personality_context_metadata("ctx-test")
        assert result is not None
        assert len(result) == 1
        name, desc = result[0]
        assert name == "standards"
        assert desc == "Coding standards and conventions"

    def test_context_no_frontmatter(self, personalities_dir):
        """Filename used as description when no front matter."""
        _create_dir_personality(
            personalities_dir, "nofm-test",
            context_files={
                "project-notes.md": "# Project Notes\n\nSome notes here.",
            },
        )
        result = _get_personality_context_metadata("nofm-test")
        assert result is not None
        assert len(result) == 1
        name, desc = result[0]
        assert name == "project-notes"
        assert desc == "project-notes"  # Falls back to filename

    def test_multiple_context_files(self, personalities_dir):
        """Multiple context files all returned."""
        _create_dir_personality(
            personalities_dir, "multi-ctx",
            context_files={
                "a-first.md": "---\ndescription: First doc\n---\n# A",
                "b-second.md": "---\ndescription: Second doc\n---\n# B",
            },
        )
        result = _get_personality_context_metadata("multi-ctx")
        assert result is not None
        assert len(result) == 2
        names = [r[0] for r in result]
        assert "a-first" in names
        assert "b-second" in names

    def test_empty_context_dir_returns_none(self, personalities_dir):
        """Empty context directory returns None."""
        d = _create_dir_personality(personalities_dir, "empty-ctx")
        (d / "context").mkdir(exist_ok=True)
        result = _get_personality_context_metadata("empty-ctx")
        assert result is None


# ===== System Prompt Injection =====


class TestSystemPromptInjection:
    def test_context_metadata_injected(self, personalities_dir, monkeypatch):
        """Context names + descriptions appear in system prompt."""
        _create_dir_personality(
            personalities_dir, "injected",
            content="# Test\n\nTest personality.",
            context_files={
                "coding.md": "---\ndescription: Coding standards\n---\n# Coding",
            },
        )
        monkeypatch.setattr("radar.agent.get_config", lambda: MagicMock(personality="injected"))

        from radar.agent import _build_system_prompt

        with patch("radar.semantic.search_memories", side_effect=Exception("skip")):
            with patch("radar.skills.discover_skills", return_value=[]):
                prompt, pc = _build_system_prompt("injected")

        assert "<personality_context>" in prompt
        assert "- coding: Coding standards" in prompt
        assert "</personality_context>" in prompt

    def test_context_not_auto_loaded(self, personalities_dir, monkeypatch):
        """Full context content NOT in system prompt — only metadata."""
        _create_dir_personality(
            personalities_dir, "no-auto",
            content="# Test\n\nTest body.",
            context_files={
                "detailed.md": "---\ndescription: Detailed doc\n---\n# Detailed\n\nVery long content that should NOT appear.",
            },
        )
        monkeypatch.setattr("radar.agent.get_config", lambda: MagicMock(personality="no-auto"))

        from radar.agent import _build_system_prompt

        with patch("radar.semantic.search_memories", side_effect=Exception("skip")):
            with patch("radar.skills.discover_skills", return_value=[]):
                prompt, pc = _build_system_prompt("no-auto")

        assert "Very long content that should NOT appear" not in prompt
        assert "- detailed: Detailed doc" in prompt

    def test_flat_personality_no_context_section(self, personalities_dir, monkeypatch):
        """Flat personality doesn't inject context section."""
        _create_flat_personality(personalities_dir, "flat-prompt", "# Flat\n\nSimple.")
        monkeypatch.setattr("radar.agent.get_config", lambda: MagicMock(personality="flat-prompt"))

        from radar.agent import _build_system_prompt

        with patch("radar.semantic.search_memories", side_effect=Exception("skip")):
            with patch("radar.skills.discover_skills", return_value=[]):
                prompt, pc = _build_system_prompt("flat-prompt")

        assert "<personality_context>" not in prompt


# ===== load_context Tool =====


class TestLoadContextTool:
    def _set_personality(self, monkeypatch, name):
        """Helper to set active personality via config mock."""
        import radar.config
        original_config = radar.config.get_config()
        original_config.personality = name

    def test_load_context_returns_content(self, personalities_dir, monkeypatch):
        """load_context returns full body with frontmatter stripped."""
        _create_dir_personality(
            personalities_dir, "ctx-tool",
            context_files={
                "standards.md": "---\ndescription: Standards\n---\n# Standards\n\nDetailed standards here.",
            },
        )
        self._set_personality(monkeypatch, "ctx-tool")

        from radar.tools.skills import load_context
        result = load_context("standards")
        assert "# Standards" in result
        assert "Detailed standards here" in result
        assert "---" not in result

    def test_load_context_not_found(self, personalities_dir, monkeypatch):
        """Error when context name doesn't exist."""
        _create_dir_personality(
            personalities_dir, "ctx-missing",
            context_files={
                "existing.md": "---\ndescription: Exists\n---\n# Exists",
            },
        )
        self._set_personality(monkeypatch, "ctx-missing")

        from radar.tools.skills import load_context
        result = load_context("nonexistent")
        assert "not found" in result.lower()
        assert "existing" in result  # Lists available

    def test_load_context_flat_personality_error(self, personalities_dir, monkeypatch):
        """Error when active personality is flat, not directory-based."""
        _create_flat_personality(personalities_dir, "flat-ctx")
        self._set_personality(monkeypatch, "flat-ctx")

        from radar.tools.skills import load_context
        result = load_context("anything")
        assert "not directory-based" in result

    def test_load_context_no_context_dir(self, personalities_dir, monkeypatch):
        """Error when personality dir has no context/ subdirectory."""
        _create_dir_personality(personalities_dir, "no-ctx-dir")
        self._set_personality(monkeypatch, "no-ctx-dir")

        from radar.tools.skills import load_context
        result = load_context("anything")
        assert "no context directory" in result.lower()

    def test_load_context_no_frontmatter(self, personalities_dir, monkeypatch):
        """Context without frontmatter returns full content."""
        _create_dir_personality(
            personalities_dir, "plain-ctx",
            context_files={
                "plain.md": "# Plain Content\n\nNo frontmatter here.",
            },
        )
        self._set_personality(monkeypatch, "plain-ctx")

        from radar.tools.skills import load_context
        result = load_context("plain")
        assert "# Plain Content" in result
        assert "No frontmatter here" in result


# ===== CLI Personality List =====


class TestPersonalityListIncludesDirectories:
    def test_cli_list_includes_both_formats(self, personalities_dir):
        """Personality listing includes both flat and directory-based."""
        _create_flat_personality(personalities_dir, "flat-one")
        _create_dir_personality(personalities_dir, "dir-one")

        from click.testing import CliRunner
        from radar.cli import personality_list

        runner = CliRunner()
        result = runner.invoke(personality_list, catch_exceptions=False)
        assert result.exit_code == 0
        assert "flat-one" in result.output
        assert "dir-one" in result.output

    def test_cli_list_marks_directory(self, personalities_dir):
        """Directory personalities show (dir) marker."""
        _create_dir_personality(personalities_dir, "dir-marked")

        from click.testing import CliRunner
        from radar.cli import personality_list

        runner = CliRunner()
        result = runner.invoke(personality_list, catch_exceptions=False)
        assert "(dir)" in result.output

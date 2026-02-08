"""Tests for Agent Skills discovery, loading, and prompt building."""

from pathlib import Path
from unittest.mock import patch

import pytest

from radar.skills import (
    SkillInfo,
    _parse_skill_frontmatter,
    build_skills_prompt_section,
    discover_skills,
    invalidate_skills_cache,
    load_skill,
    get_skill_resource_path,
    _list_skill_resources,
)


@pytest.fixture(autouse=True)
def clear_skills_cache():
    """Clear skills cache before and after each test."""
    invalidate_skills_cache()
    yield
    invalidate_skills_cache()


@pytest.fixture
def skills_dir(isolated_data_dir):
    """Create and return the skills directory."""
    d = isolated_data_dir / "skills"
    d.mkdir(exist_ok=True)
    return d


def _create_skill(base_dir: Path, name: str, description: str = "A test skill",
                   extra_fm: str = "", body: str = "# Instructions\n\nDo the thing.") -> Path:
    """Helper to create a skill directory with SKILL.md."""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {name}\ndescription: {description}\n{extra_fm}---\n{body}"
    (skill_dir / "SKILL.md").write_text(fm)
    return skill_dir


# ===== Frontmatter Parsing =====


class TestParseSkillFrontmatter:
    def test_valid_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test\ndescription: A test\n---\n# Body")
        fm = _parse_skill_frontmatter(skill_md)
        assert fm["name"] == "test"
        assert fm["description"] == "A test"

    def test_no_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# Just body content")
        assert _parse_skill_frontmatter(skill_md) is None

    def test_invalid_yaml(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\n: invalid: [yaml\n---\n# Body")
        assert _parse_skill_frontmatter(skill_md) is None

    def test_empty_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\n---\n# Body")
        assert _parse_skill_frontmatter(skill_md) is None

    def test_file_not_found(self, tmp_path):
        assert _parse_skill_frontmatter(tmp_path / "nonexistent.md") is None

    def test_frontmatter_with_metadata(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            "---\nname: test\ndescription: Desc\n"
            "license: MIT\ncompatibility: Python 3.10+\n"
            "metadata:\n  author: tester\n  version: '2.0'\n---\n# Body"
        )
        fm = _parse_skill_frontmatter(skill_md)
        assert fm["license"] == "MIT"
        assert fm["compatibility"] == "Python 3.10+"
        assert fm["metadata"]["author"] == "tester"


# ===== Discovery =====


class TestDiscoverSkills:
    def test_discover_skills_in_default_dir(self, skills_dir):
        _create_skill(skills_dir, "my-skill", "My test skill")
        skills = discover_skills()
        assert len(skills) == 1
        assert skills[0].name == "my-skill"
        assert skills[0].description == "My test skill"

    def test_discover_multiple_skills(self, skills_dir):
        _create_skill(skills_dir, "skill-a", "First skill")
        _create_skill(skills_dir, "skill-b", "Second skill")
        skills = discover_skills()
        assert len(skills) == 2
        names = {s.name for s in skills}
        assert names == {"skill-a", "skill-b"}

    def test_discover_skills_invalid_frontmatter(self, skills_dir):
        """Skills with invalid frontmatter are skipped."""
        skill_dir = skills_dir / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# No frontmatter")
        skills = discover_skills()
        assert len(skills) == 0

    def test_discover_skills_name_mismatch(self, skills_dir):
        """Skills where name doesn't match directory name are skipped."""
        skill_dir = skills_dir / "my-dir"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: different-name\ndescription: test\n---\n# Body")
        skills = discover_skills()
        assert len(skills) == 0

    def test_discover_skills_missing_name(self, skills_dir):
        """Skills without a name field are skipped."""
        skill_dir = skills_dir / "no-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ndescription: no name field\n---\n# Body")
        skills = discover_skills()
        assert len(skills) == 0

    def test_discover_skills_extra_dirs(self, skills_dir, tmp_path):
        """Skills in extra configured directories are discovered."""
        extra_dir = tmp_path / "extra_skills"
        extra_dir.mkdir()
        _create_skill(extra_dir, "extra-skill", "Extra skill")

        with patch("radar.skills.get_config") as mock_config:
            mock_config.return_value.skills.enabled = True
            mock_config.return_value.skills.dirs = [str(extra_dir)]
            invalidate_skills_cache()
            skills = discover_skills()

        assert any(s.name == "extra-skill" for s in skills)

    def test_discover_skills_disabled(self, skills_dir):
        """No skills discovered when disabled."""
        _create_skill(skills_dir, "my-skill", "Test")

        with patch("radar.skills.get_config") as mock_config:
            mock_config.return_value.skills.enabled = False
            mock_config.return_value.skills.dirs = []
            invalidate_skills_cache()
            skills = discover_skills()

        assert len(skills) == 0

    def test_discover_skills_caching(self, skills_dir):
        """Skills are cached after first discovery."""
        _create_skill(skills_dir, "cached-skill", "Cached")
        skills1 = discover_skills()
        assert len(skills1) == 1

        # Add another skill - should not appear due to cache
        _create_skill(skills_dir, "new-skill", "New")
        skills2 = discover_skills()
        assert len(skills2) == 1  # Still cached

        # Invalidate and re-discover
        invalidate_skills_cache()
        skills3 = discover_skills()
        assert len(skills3) == 2

    def test_discover_skills_deduplicates(self, skills_dir, tmp_path):
        """Duplicate skill names across directories are deduplicated."""
        _create_skill(skills_dir, "dup-skill", "Default dir version")

        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        _create_skill(extra_dir, "dup-skill", "Extra dir version")

        with patch("radar.skills.get_config") as mock_config:
            mock_config.return_value.skills.enabled = True
            mock_config.return_value.skills.dirs = [str(extra_dir)]
            invalidate_skills_cache()
            skills = discover_skills()

        # Only one version should be found
        dup_skills = [s for s in skills if s.name == "dup-skill"]
        assert len(dup_skills) == 1

    def test_discover_skill_dir_itself_is_skill(self, tmp_path):
        """A configured dir that itself contains SKILL.md is discovered."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: test\n---\n# Body")

        with patch("radar.skills.get_config") as mock_config:
            mock_config.return_value.skills.enabled = True
            mock_config.return_value.skills.dirs = [str(skill_dir)]
            invalidate_skills_cache()
            skills = discover_skills()

        assert any(s.name == "my-skill" for s in skills)

    def test_skill_metadata_parsed(self, skills_dir):
        """Skill metadata fields are parsed correctly."""
        _create_skill(
            skills_dir, "meta-skill", "With metadata",
            extra_fm="license: MIT\ncompatibility: Python 3.10+\nmetadata:\n  author: test\n"
        )
        skills = discover_skills()
        assert len(skills) == 1
        s = skills[0]
        assert s.license == "MIT"
        assert s.compatibility == "Python 3.10+"
        assert s.metadata == {"author": "test"}


# ===== Loading =====


class TestLoadSkill:
    def test_load_skill_returns_body(self, skills_dir):
        _create_skill(skills_dir, "loadable", "Loadable skill",
                       body="# Full Instructions\n\nDo all the things.")
        content = load_skill("loadable")
        assert content is not None
        assert "# Full Instructions" in content
        assert "Do all the things" in content
        # Frontmatter should be stripped
        assert "---" not in content

    def test_load_skill_not_found(self, skills_dir):
        assert load_skill("nonexistent") is None

    def test_load_skill_no_frontmatter(self, skills_dir):
        """SKILL.md without frontmatter can't be discovered, so load returns None."""
        skill_dir = skills_dir / "no-fm"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Just body")
        assert load_skill("no-fm") is None


# ===== Resource Paths =====


class TestGetSkillResourcePath:
    def test_get_existing_resource(self, skills_dir):
        skill_dir = _create_skill(skills_dir, "res-skill", "Resource skill")
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helper.sh").write_text("#!/bin/bash\necho hello")

        path = get_skill_resource_path("res-skill", "scripts/helper.sh")
        assert path is not None
        assert path.name == "helper.sh"

    def test_get_nonexistent_resource(self, skills_dir):
        _create_skill(skills_dir, "res-skill2", "Resource skill")
        assert get_skill_resource_path("res-skill2", "scripts/nope.sh") is None

    def test_get_resource_unknown_skill(self, skills_dir):
        assert get_skill_resource_path("unknown", "file.txt") is None

    def test_path_traversal_blocked(self, skills_dir):
        _create_skill(skills_dir, "safe-skill", "Safe skill")
        assert get_skill_resource_path("safe-skill", "../../etc/passwd") is None


# ===== Resource Listing =====


class TestListSkillResources:
    def test_list_resources(self, skills_dir):
        skill_dir = _create_skill(skills_dir, "full-skill", "Full skill")
        (skill_dir / "scripts").mkdir()
        (skill_dir / "scripts" / "run.sh").write_text("#!/bin/bash")
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "guide.md").write_text("# Guide")

        skills = discover_skills()
        skill = next(s for s in skills if s.name == "full-skill")
        resources = _list_skill_resources(skill)
        assert len(resources) == 2
        assert any("scripts/" in r and "run.sh" in r for r in resources)
        assert any("references/" in r and "guide.md" in r for r in resources)

    def test_no_resources(self, skills_dir):
        _create_skill(skills_dir, "bare-skill", "Bare skill")
        skills = discover_skills()
        skill = next(s for s in skills if s.name == "bare-skill")
        resources = _list_skill_resources(skill)
        assert resources == []


# ===== Prompt Building =====


class TestBuildSkillsPromptSection:
    def test_builds_xml_block(self):
        skills = [
            SkillInfo(name="skill-a", description="First skill", path=Path("/tmp/a")),
            SkillInfo(name="skill-b", description="Second skill", path=Path("/tmp/b")),
        ]
        section = build_skills_prompt_section(skills)
        assert "<available_skills>" in section
        assert "- skill-a: First skill" in section
        assert "- skill-b: Second skill" in section
        assert "</available_skills>" in section
        assert "use_skill" in section

    def test_empty_skills_returns_empty(self):
        assert build_skills_prompt_section([]) == ""


# ===== use_skill Tool =====


class TestUseSkillTool:
    def test_use_skill_returns_content(self, skills_dir):
        skill_dir = _create_skill(
            skills_dir, "usable", "Usable skill",
            body="# Instructions\n\nFollow these steps."
        )
        from radar.tools.skills import use_skill
        result = use_skill("usable")
        assert "# Instructions" in result
        assert "Follow these steps" in result

    def test_use_skill_includes_resources(self, skills_dir):
        skill_dir = _create_skill(skills_dir, "res-tool", "With resources")
        (skill_dir / "scripts").mkdir()
        (skill_dir / "scripts" / "setup.sh").write_text("#!/bin/bash")

        from radar.tools.skills import use_skill
        result = use_skill("res-tool")
        assert "scripts/" in result
        assert "setup.sh" in result

    def test_use_skill_not_found(self, skills_dir):
        from radar.tools.skills import use_skill
        result = use_skill("nonexistent")
        assert "not found" in result.lower()

    def test_use_skill_not_found_lists_available(self, skills_dir):
        _create_skill(skills_dir, "existing", "An existing skill")

        from radar.tools.skills import use_skill
        result = use_skill("missing")
        assert "existing" in result


# ===== Cache Invalidation =====


class TestCacheInvalidation:
    def test_invalidate_clears_cache(self, skills_dir):
        _create_skill(skills_dir, "cache-test", "Cache test")
        skills = discover_skills()
        assert len(skills) == 1

        invalidate_skills_cache()
        # Create new skill
        _create_skill(skills_dir, "new-cache", "New cache test")
        skills = discover_skills()
        assert len(skills) == 2

"""Agent Skills discovery and loading.

Discovers Agent Skills packages (directories containing SKILL.md) from
configured directories and provides progressive disclosure: only frontmatter
metadata is loaded at startup; full content is loaded on demand via the
use_skill tool.

See https://agentskills.io/ for the Agent Skills specification.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from radar.config import get_config, get_data_paths

logger = logging.getLogger(__name__)

# Module-level cache for discovered skills
_skills_cache: list["SkillInfo"] | None = None


@dataclass
class SkillInfo:
    """Metadata for a discovered Agent Skill."""

    name: str
    description: str
    path: Path  # Directory containing SKILL.md
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


def _parse_skill_frontmatter(skill_md_path: Path) -> dict | None:
    """Parse YAML front matter from a SKILL.md file.

    Returns the parsed dict or None if parsing fails.
    """
    try:
        content = skill_md_path.read_text()
    except OSError:
        return None

    if not content.startswith("---"):
        return None

    end = content.find("---", 3)
    if end == -1:
        return None

    front_matter_str = content[3:end].strip()
    if not front_matter_str:
        return None

    try:
        fm = yaml.safe_load(front_matter_str)
    except yaml.YAMLError:
        return None

    if not isinstance(fm, dict):
        return None

    return fm


def _get_skill_dirs() -> list[Path]:
    """Get all directories to scan for skills."""
    config = get_config()

    if not config.skills.enabled:
        return []

    dirs = []

    # Default location
    dirs.append(get_data_paths().skills)

    # Extra configured dirs
    for d in config.skills.dirs:
        path = Path(d).expanduser().resolve()
        if path.is_dir():
            dirs.append(path)

    return dirs


def discover_skills() -> list[SkillInfo]:
    """Scan skill directories and parse SKILL.md frontmatter.

    Returns a list of SkillInfo with metadata only (no full content loaded).
    Results are cached; call invalidate_skills_cache() to force re-scan.
    """
    global _skills_cache
    if _skills_cache is not None:
        return _skills_cache

    config = get_config()
    if not config.skills.enabled:
        _skills_cache = []
        return _skills_cache

    skills = []
    seen_names: set[str] = set()

    for scan_dir in _get_skill_dirs():
        if not scan_dir.is_dir():
            continue

        # Check if this directory itself is a skill
        skill_md = scan_dir / "SKILL.md"
        if skill_md.is_file():
            info = _parse_single_skill(scan_dir, skill_md, seen_names)
            if info:
                skills.append(info)
                seen_names.add(info.name)

        # Also scan subdirectories
        try:
            for entry in sorted(scan_dir.iterdir()):
                if not entry.is_dir():
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.is_file():
                    continue
                info = _parse_single_skill(entry, skill_md, seen_names)
                if info:
                    skills.append(info)
                    seen_names.add(info.name)
        except OSError as e:
            logger.warning("Error scanning skill directory %s: %s", scan_dir, e)

    _skills_cache = skills
    return skills


def _parse_single_skill(
    skill_dir: Path, skill_md: Path, seen_names: set[str]
) -> SkillInfo | None:
    """Parse a single skill directory and return SkillInfo or None."""
    fm = _parse_skill_frontmatter(skill_md)
    if fm is None:
        logger.debug("Skipping %s: no valid frontmatter", skill_md)
        return None

    name = fm.get("name")
    if not name or not isinstance(name, str):
        logger.debug("Skipping %s: missing or invalid 'name' field", skill_md)
        return None

    # Validate name matches directory name
    if name != skill_dir.name:
        logger.debug(
            "Skipping %s: name '%s' doesn't match directory '%s'",
            skill_md, name, skill_dir.name,
        )
        return None

    if name in seen_names:
        logger.debug("Skipping duplicate skill: %s", name)
        return None

    description = fm.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    return SkillInfo(
        name=name,
        description=description,
        path=skill_dir,
        license=fm.get("license") if isinstance(fm.get("license"), str) else None,
        compatibility=fm.get("compatibility") if isinstance(fm.get("compatibility"), str) else None,
        metadata=fm.get("metadata", {}) if isinstance(fm.get("metadata"), dict) else {},
    )


def load_skill(name: str) -> str | None:
    """Load the full SKILL.md body content for a skill.

    Args:
        name: The skill name to load.

    Returns:
        The full SKILL.md body (frontmatter stripped), or None if not found.
    """
    skills = discover_skills()
    skill = next((s for s in skills if s.name == name), None)
    if skill is None:
        return None

    skill_md = skill.path / "SKILL.md"
    try:
        content = skill_md.read_text()
    except OSError:
        return None

    # Strip front matter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3:].lstrip("\n")

    return content


def get_skill_resource_path(name: str, resource: str) -> Path | None:
    """Resolve a resource path within a skill directory.

    Args:
        name: The skill name.
        resource: Relative path to the resource within the skill dir.

    Returns:
        Absolute path to the resource, or None if skill not found or
        resource doesn't exist.
    """
    skills = discover_skills()
    skill = next((s for s in skills if s.name == name), None)
    if skill is None:
        return None

    resource_path = (skill.path / resource).resolve()

    # Ensure the resource is within the skill directory (prevent path traversal)
    try:
        resource_path.relative_to(skill.path.resolve())
    except ValueError:
        return None

    if resource_path.exists():
        return resource_path
    return None


def _list_skill_resources(skill: SkillInfo) -> list[str]:
    """List available resources in a skill directory."""
    resources = []
    for subdir in ("scripts", "references", "assets"):
        d = skill.path / subdir
        if d.is_dir():
            files = sorted(f.name for f in d.iterdir() if f.is_file())
            if files:
                resources.append(f"{subdir}/: {', '.join(files)}")
    return resources


def build_skills_prompt_section(skills: list[SkillInfo]) -> str:
    """Build the <available_skills> XML block for the system prompt.

    Args:
        skills: List of discovered SkillInfo objects.

    Returns:
        XML-formatted string listing available skills.
    """
    if not skills:
        return ""

    lines = ["<available_skills>"]
    for skill in skills:
        lines.append(f"- {skill.name}: {skill.description}")
    lines.append("</available_skills>")
    lines.append("")
    lines.append(
        "To activate a skill, use the use_skill tool with the skill name. "
        "This will load the skill's full instructions."
    )

    return "\n".join(lines)


def invalidate_skills_cache() -> None:
    """Invalidate the skills cache, forcing re-discovery on next call."""
    global _skills_cache
    _skills_cache = None

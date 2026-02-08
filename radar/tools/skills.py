"""Agent Skills and personality context tools."""

from radar.tools import tool


@tool(
    name="use_skill",
    description="Activate an agent skill by name. Returns the skill's full instructions. Use this when a task matches an available skill's description.",
    parameters={
        "name": {
            "type": "string",
            "description": "Name of the skill to activate",
        },
    },
)
def use_skill(name: str) -> str:
    """Load and return a skill's full instructions."""
    from radar.skills import discover_skills, load_skill, _list_skill_resources

    content = load_skill(name)
    if content is None:
        available = discover_skills()
        if available:
            names = ", ".join(s.name for s in available)
            return f"Skill '{name}' not found. Available skills: {names}"
        return f"Skill '{name}' not found. No skills are currently available."

    # Find the skill info to list resources
    skills = discover_skills()
    skill = next((s for s in skills if s.name == name), None)

    result = content
    if skill:
        resources = _list_skill_resources(skill)
        if resources:
            result += "\n\n## Available Resources\n\n"
            result += "\n".join(f"- {r}" for r in resources)
            result += f"\n\nSkill directory: {skill.path}"

    return result


@tool(
    name="load_context",
    description="Load a context document from the active personality. Use when a task relates to one of the available personality context documents.",
    parameters={
        "name": {
            "type": "string",
            "description": "Name of the context document (from <personality_context> list)",
        },
    },
)
def load_context(name: str) -> str:
    """Load and return a personality context document's full content."""
    import yaml

    from radar.agent import get_personalities_dir
    from radar.config import get_config

    config = get_config()
    personality_name = config.personality

    # Resolve the personality directory
    personalities_dir = get_personalities_dir()
    personality_dir = personalities_dir / personality_name

    if not personality_dir.is_dir():
        return f"Context documents are not available — active personality '{personality_name}' is not directory-based."

    context_dir = personality_dir / "context"
    if not context_dir.is_dir():
        return f"No context directory found for personality '{personality_name}'."

    # Try exact name match (with or without .md extension)
    context_file = context_dir / f"{name}.md"
    if not context_file.is_file():
        context_file = context_dir / name
        if not context_file.is_file():
            # List available contexts
            available = [f.stem for f in sorted(context_dir.glob("*.md"))]
            if available:
                return f"Context '{name}' not found. Available: {', '.join(available)}"
            return f"Context '{name}' not found. No context documents available."

    content = context_file.read_text()

    # Strip front matter if present
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip("\n")

    return content

"""Plugin version management for rollback capability."""

from datetime import datetime
from pathlib import Path

import yaml

from radar.plugins.models import PluginManifest


class VersionManager:
    """Manages plugin versions for rollback capability."""

    def __init__(self, versions_dir: Path):
        """Initialize with versions directory."""
        self.versions_dir = versions_dir
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def save_version(self, plugin_name: str, code: str, manifest: PluginManifest) -> str:
        """Save a new version of a plugin. Returns version string."""
        plugin_versions_dir = self.versions_dir / plugin_name
        plugin_versions_dir.mkdir(parents=True, exist_ok=True)

        # Find next version number
        existing_versions = list(plugin_versions_dir.glob("v*.py"))
        next_version = len(existing_versions) + 1
        version_str = f"v{next_version}"

        # Save the code
        code_file = plugin_versions_dir / f"{version_str}.py"
        code_file.write_text(code)

        # Save the manifest
        manifest_file = plugin_versions_dir / f"{version_str}.yaml"
        manifest.version = version_str
        manifest.updated_at = datetime.now().isoformat()
        with open(manifest_file, "w") as f:
            yaml.dump(manifest.to_dict(), f)

        return version_str

    def get_versions(self, plugin_name: str) -> list[dict]:
        """Get list of versions for a plugin."""
        plugin_versions_dir = self.versions_dir / plugin_name
        if not plugin_versions_dir.exists():
            return []

        versions = []
        for code_file in sorted(plugin_versions_dir.glob("v*.py")):
            version_str = code_file.stem
            manifest_file = plugin_versions_dir / f"{version_str}.yaml"

            version_info = {"version": version_str, "code_file": str(code_file)}

            if manifest_file.exists():
                with open(manifest_file) as f:
                    manifest_data = yaml.safe_load(f) or {}
                version_info["manifest"] = manifest_data
                version_info["created_at"] = manifest_data.get("updated_at", "")

            versions.append(version_info)

        return versions

    def get_version(self, plugin_name: str, version: str) -> tuple[str, PluginManifest] | None:
        """Get a specific version's code and manifest."""
        plugin_versions_dir = self.versions_dir / plugin_name
        code_file = plugin_versions_dir / f"{version}.py"
        manifest_file = plugin_versions_dir / f"{version}.yaml"

        if not code_file.exists():
            return None

        code = code_file.read_text()

        if manifest_file.exists():
            with open(manifest_file) as f:
                manifest_data = yaml.safe_load(f) or {}
            manifest = PluginManifest.from_dict(manifest_data)
        else:
            manifest = PluginManifest(name=plugin_name, version=version)

        return code, manifest

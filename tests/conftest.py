"""Pytest configuration for radar tests."""

import sys
from pathlib import Path

import pytest

# Ensure radar package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Create an isolated data directory for tests.

    This fixture:
    - Creates a temporary data directory
    - Sets RADAR_DATA_DIR environment variable to point to it
    - Resets config and data paths caches so changes take effect

    Use this fixture in any test that needs to read/write radar data
    without affecting production data in ~/.local/share/radar/.

    Example:
        def test_something(isolated_data_dir):
            # isolated_data_dir is a Path to the temp data directory
            # All radar data operations will use this directory
            pass
    """
    data_dir = tmp_path / "radar_data"
    data_dir.mkdir()

    # Set environment variable
    monkeypatch.setenv("RADAR_DATA_DIR", str(data_dir))

    # Reset config and paths caches so they pick up the new env var
    import radar.config
    radar.config._config = None
    radar.config.reset_data_paths()

    yield data_dir

    # Cleanup happens automatically via monkeypatch (env var)
    # and tmp_path (directory deletion)


@pytest.fixture
def isolated_config(isolated_data_dir):
    """Get a fresh config instance with isolated data directory.

    This is a convenience fixture that returns the config after
    setting up isolated_data_dir.
    """
    from radar.config import get_config
    return get_config()

"""Pytest configuration for radar tests."""

import sys
from pathlib import Path

# Ensure radar package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

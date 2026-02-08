#!/bin/bash
# PreToolUse hook: block edits to files that shouldn't be modified directly.

filepath="$CLAUDE_FILE_PATH"

case "$filepath" in
  # Lock files
  *.lock)
    echo "BLOCK: Lock files should not be edited directly." >&2
    exit 2
    ;;
  # Virtual environment
  */.venv/*)
    echo "BLOCK: Virtual environment files should not be edited directly." >&2
    exit 2
    ;;
  # Compiled/cached files
  *__pycache__/*|*.pyc)
    echo "BLOCK: Compiled Python files should not be edited." >&2
    exit 2
    ;;
esac

exit 0

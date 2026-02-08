#!/bin/bash
# PostToolUse hook: runs related tests when source files are edited.
# Maps radar source files to their corresponding test files.

filepath="$CLAUDE_FILE_PATH"

# Only process Python files in the project
case "$filepath" in
  */radar/*.py|*/tests/*.py) ;;
  *) exit 0 ;;
esac

cd "$(dirname "$0")/../.."

testfiles=""
basename_noext=$(basename "$filepath" .py)

if [[ "$filepath" == */tests/test_*.py ]]; then
  # Test file edited directly — run it
  testfiles="$filepath"

elif [[ "$filepath" == */radar/web/routes/*.py ]]; then
  testfiles="tests/test_web_routes.py"

elif [[ "$filepath" == */radar/web/templates/* ]] || [[ "$filepath" == */radar/web/static/* ]]; then
  exit 0

elif [[ "$filepath" == */radar/config/*.py ]]; then
  testfiles="tests/test_config.py"

elif [[ "$filepath" == */radar/plugins/*.py ]]; then
  testfiles="tests/test_plugins.py"

elif [[ "$filepath" == */radar/tools/*.py ]]; then
  testfiles="tests/test_tool_framework.py tests/test_tool_discovery.py"

elif [[ "$filepath" == */radar/*.py ]]; then
  candidate="tests/test_${basename_noext}.py"
  if [ -f "$candidate" ]; then
    testfiles="$candidate"
  fi
fi

if [ -z "$testfiles" ]; then
  exit 0
fi

.venv/bin/python -m pytest $testfiles -x -q --tb=short 2>&1 | tail -20

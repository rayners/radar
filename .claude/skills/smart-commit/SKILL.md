---
name: smart-commit
description: "Commit changes and auto-update docs/TODO.md test counts if stale"
disable-model-invocation: true
---

# Smart Commit

When the user invokes `/smart-commit`, create a commit that also updates test counts in `docs/TODO.md` if they've changed.

## Steps

1. **Collect current test counts** by running:
   ```
   python -m pytest tests/ --co -q 2>/dev/null
   ```
   This lists all collected tests. The last line shows the total (e.g., "1094 tests collected").
   Also collect per-file counts by running:
   ```
   python -m pytest tests/ --co -q 2>/dev/null | grep '::' | sed 's/::.*//' | sort | uniq -c | sort -rn
   ```
   This gives counts per test file.

2. **Read `docs/TODO.md`** and check line 11 which contains the test file listing and bold total (e.g., `**1094 total**`).

3. **If the total has changed**, update line 11:
   - Update the bold total at the end: `**N total**`
   - Update individual file counts in the listing (format: `test_name.py (N tests)`)
   - Add any new test files that aren't listed yet
   - Remove any test files that no longer exist

4. **Stage all relevant changes** including `docs/TODO.md` if it was updated.

5. **Create the commit** following the repository's existing commit style:
   - Short, descriptive subject line
   - If TODO.md was updated, don't mention it in the commit title — it's a routine part of the workflow
   - End with `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`

6. **Do NOT push** unless the user explicitly asks.

## Important

- Always use `python -m pytest` (not just `pytest`) to ensure the right environment
- The test count line is the long line near the top of `docs/TODO.md` starting with "Test files:"
- Preserve the exact format: `test_name.py (N tests)` with commas between entries
- The total is bolded at the end: `**N total**`

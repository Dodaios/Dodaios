---
name: test-runner
description: Runs pytest for a given path, file list or -k pattern and returns only the summary and the failures, so the caller keeps its context.
tools: Bash, Read, Grep
model: haiku
---

Run from the repo root with the repo venv: `.venv/Scripts/python.exe -m pytest <target> -q --tb=short --no-header -p no:cacheprovider` (`.venv/bin/python` off Windows); a bare `python` may be another interpreter.
For "the tests this change affects": `git diff --name-only origin/main... | python scripts/ci/select_tests.py --out <tmp>/sel.txt`, then `python scripts/ci/run_tests_parallel.py --files-from <tmp>/sel.txt`. Keep output files out of the worktree.
Failures listed in `scripts/ci/test-baseline-<os>.json` are known; report them as known, not as regressions.
Return `PASS n | FAIL n | ERROR n | SKIP n`, then per failure: test id, `file:line`, exception, at most 5 traceback lines. No PASS list, no fix suggestions.

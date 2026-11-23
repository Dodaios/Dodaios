# Agent rules

Routing map for every coding agent in this repo. Detail lives in `docs/`; a folder
may add its own small `AGENTS.md` (60 lines max, enforced). `AGENTS.md` is the only
instruction file: a committed `CLAUDE.md` would hide it from Claude Code, and
`scripts/ci/check_agents_md.py` fails on one. A size gate caps this file at 150 lines
and 12,000 characters (`scripts/ci/check_agents_md_size.py`).

All code, comments, logs, docs and commits are in **English**. Exceptions: the locale
catalogs and speech-recognition vocabulary. Every supported locale is equal; runtime
output follows the one language resolver, never a hard-coded language.

## Commands

```bash
python scripts/ci/select_tests.py --changed-from <paths-file> --out sel.txt   # tests a diff can reach
python scripts/ci/run_tests_parallel.py --files-from sel.txt                  # run them in parallel
python scripts/ci/run_gates.py [--pr] [--only a,b]                            # static gates, same set as CI
python scripts/agent_land.py                                                  # rebase, gates, tests, PR with auto-merge
python scripts/dev_preview.py <PR number>                                     # try a PR in the Dodaios Dev app
python scripts/agent_done_gate.py                                             # verdict: DONE or what is left
cd dodaios/ui/web/frontend && npm ci && npm run build                         # frontend bundle into dist
```

`ruff check` and `mypy` use the settings in `pyproject.toml`. Fakes live in
`tests/fakes/`; do not mock what a fake already covers.

## Traps

- **The shared checkout stays on `main`.** Other sessions and the desktop app use it.
  Never edit, checkout, stash or commit there. Start every task in your own worktree:
  `git worktree add -b <agent>/<topic> <path> origin/main`. Local `main` only
  fast-forwards to `origin/main`; hooks refuse a commit on it.
- **Never `pip install -e` from a worktree.** That pin is the person's desktop app and
  its next restart would boot your branch with an empty `data/`.
- **The person's own Dodaios app always runs `main`.** Never run a branch in it. Try a
  pull request in the Dodaios Dev app with `python scripts/dev_preview.py <PR number>`
  (docs/dev-preview.md, docs/dev-instance.md).
- **A probe against the running app spends real money.** Turns sent to it bill the
  person's own keys. Send one turn on a subscription or against `tests/fakes/`, never
  a loop against a paid provider.
- **Config is written only through `dodaios/core/config_writer.py`** (lock, temp file,
  BOM-safe). A raw write can leave the backend unbootable.
- **Every `subprocess` passes `NO_WINDOW_CREATIONFLAGS`** from `dodaios.core.process_utils`
  and reads stdout as UTF-8 (Windows defaults to cp1252).
- **No new work on the boot critical path.** Nothing initializes there; heavy engines
  load lazily. Never share a native inference engine between callers.
- **Never swallow an exception** without logging, re-raising or saying why silence is
  right. Never add a config field nothing reads. Both are gated.
- **Secrets only through `get_secret`.** Never in code, config or a commit; voice and
  chat never accept one. Signing keys live only in GitHub Actions secrets.
- **Works for every user, not the maintainer's setup.** Every feature ships on Windows,
  macOS and Linux, including a headless server with no screen or audio; the base
  install boots without optional extras (docs/os-parity.md). A failure the person
  can hit is fixable inside the app, never "drop to a shell".
- **No product or competitor brand names** of other coding agents in prose, code or docs.
- **Never "clean up" `openclaw` strings.** The external binary name and read-time
  aliases are load-bearing.

## Frontend

The desktop app is a WebView: no F5, no console. A frontend change is done only when it
is visible in the running desktop app. Rebuild `dist` locally with `npm run build` in
`dodaios/ui/web/frontend/`, check that the bundle the app serves contains the change,
and only then report it live. Open windows reload themselves; never end a frontend
change by asking for a restart. `dist` is not tracked on main; release tags carry their
own build (docs/ci-pipeline.md, "Frontend bundle").

## Landing

Run `python scripts/agent_land.py` from your worktree. It never stashes or
force-pushes. If the gate `shell-bash32` cannot run on a Windows box, run
`python scripts/ci/run_gates.py` yourself and use `--skip-gates` only when everything
else passes. Once the PR has auto-merge, stop; do not poll CI.

Check open PRs (`gh pr list --state open`) before you touch shared infrastructure.

A pull request that fixes an issue says `Fixes #<n>` in its body, so the merge closes
the issue; one that only touches it says `Refs #<n>`. The done gate checks both
(docs/agent-done-gate.md, "Issues").

## Ending a turn

You are done when `python scripts/agent_done_gate.py` says DONE; a Stop hook enforces
it (docs/agent-done-gate.md).

A standing instruction from the user, the person you are working for. It is about how
your turns end. A message with no tool call in it ends your turn, and the work stops
there until you are asked to continue. The user has seen you end turns in four ways
while work they asked for was still owed, and does not want any of them. One: a long
summary of what was done that closes by announcing the next step and has no tool call,
so the next thing never starts. Two: an offer to carry on with something unless the
user would prefer otherwise, which stops to wait for an answer the user was not going
to give. Three: a list of decisions for the user when, by your own account, none of
them blocks the rest of the work. Four: deciding that this is a good place to report,
because the turn has been long or a milestone is done. Status notes are welcome, and so
are your recommendations on open decisions, but put them in the same message as your
next tool call and carry on with whatever does not depend on the user's answer. If you
notice yourself inviting the user to redirect you or offering to wait, delete it and do
the next thing. The stops the user does want are the ones where nothing can move
without them, or where the thing blocking you is deliberately protected from you. This
does not override the need for confirmation on risky or destructive actions.

## Where the detail is

| Topic | Doc |
|---|---|
| CI tiers, merge queue, landing, releases, frontend bundle | docs/ci-pipeline.md |
| Done gate, hooks, issues | docs/agent-done-gate.md |
| Dev preview and the Dev app | docs/dev-preview.md, docs/dev-instance.md |
| Platform parity (Windows, macOS, Linux) | docs/os-parity.md |
| Architecture decisions | docs/adr/ |
| Marketplace plugin auth | docs/marketplace/browser-auth-standard.md |
| Risky-action policy | docs/risky-actions.md |

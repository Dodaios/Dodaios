# Nightly cleanup agent

AI-written code leaves small debts behind: copied blocks, long functions, silent
exception handlers, unused code. The ratchet gates in `scripts/ci` stop new debt.
This agent pays old debt back, one small pull request per night.

## What it does

1. `scripts/cleanup_pick.py` picks ONE target and writes a brief for a coding agent.
   The category rotates by day:
   - a duplicate cluster in one file (two or more identical function bodies),
   - a function just over the 200-line limit,
   - silent exception handlers in one small file (from `silent-handlers-baseline.json`),
   - dead code that `vulture` reports at 80 % confidence or more (only when
     `vulture` is installed; otherwise the category is skipped).
   If a category has no candidate, the next one is tried. Exit code 3 means nothing safe
   tonight.
2. It skips every file that an open pull request touches (`gh pr list --json files`)
   and every file main changed in the last 24 hours.
3. The brief names the file and function, the guard commands (relevant tests,
   `scripts/perf_guard.py --fast` when it exists, the gates), and the rules: own
   worktree, no behaviour change, `python scripts/agent_land.py`, one PR, lower the
   baseline with the `--update` command the gate prints.
4. The routine in `docs/cleanup-agent-routine.json` runs the picker each night and
   gives the brief to a coding agent thread. It does nothing when the previous cleanup
   PR (branch `claude/nightly-cleanup-*`) is still open.

Try the picker by hand, without GitHub: `python scripts/cleanup_pick.py --no-gh`
(add `--json` for machine output, `--category long_function` to force one kind).

## Switch it on

Nothing is scheduled by the repository. The person does this once:

1. Open the Agents section, pick the agent that should own the job (the lead is fine),
   open its Routines rail and choose "New routine".
2. Paste `title`, `prompt` and the schedule from `docs/cleanup-agent-routine.json`.
   Set the timezone to your own IANA zone (for example `Europe/Berlin`).
3. Or say to the assistant: "create the routine from docs/cleanup-agent-routine.json
   for me". It calls `society-create-routine`.
4. Check the readiness answer. It must say `ready`: the `gh` login and the coding CLI
   have to work on this computer. Use "Run now" once to see the first brief.

The routine runs on the seat of its owner. With a subscription connected, an unattended
run never bills an API key (see `docs/routines.md`, "Unattended runs and API keys").

## Pause or stop it

- Pause: in the Routines rail pause the routine, or say "pause the nightly cleanup
  routine" (`society-routine-operation`). Resume the same way.
- Stop for good: delete the routine. Nothing else is installed.
- An open cleanup PR is closed like any other PR. Closing it also lets the next night run.

## Limits

One PR a night, one file. The picker never edits anything itself, and the agent can
open no PR when the change is not clearly safe. Add new categories in
`scripts/cleanup_pick.py` (`CATEGORIES`, a pool in `pick`) and a test in
`tests/unit/scripts/test_cleanup_pick.py`.

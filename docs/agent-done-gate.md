# Agent done gate

A coding agent ends its turn only when its work has landed. Hooks enforce
this, not instructions: every coding CLI's Stop event runs
`scripts/agent_done_gate.py`, and while the answer is WAIT or FIX the agent is
sent back to work with one imperative next step.

## Done

| # | Condition |
|---|-----------|
| D1 | the branch's worktree has no uncommitted changes (generated paths in `ignore_dirty` excepted) |
| D2 | every local commit of the branch is on the remote |
| D3 | the branch's pull request is merged into `main` |
| D4 | the `main_workflows` are green on `main` for the merge commit (or for a later `main` commit that contains it) |
| D5 | the local `main` checkout contains the merge commit; the gate fast-forwards it (never killed on a short timer), and a checkout with local edits, or with an `index.lock` (another git command is writing it), is left alone and noted |

## Verdicts

| Verdict | Meaning | Stop? |
|---------|---------|-------|
| DONE | D1–D5 hold | yes |
| NONE | no branch work in this session | yes |
| HOLD | draft PR, opt-out label (`wip`, `needs-human`, `do-not-merge`, `no-auto-merge`), or `--hold` | yes |
| WAIT | CI running, PR queued, merge freeze, main CI running | no |
| FIX | red checks, conflicts, unpushed commits, auto-merge missing, parked CI run, red main CI for the merge commit | no |
| STUCK | WAIT longer than `wait_budget_hours` or the same FIX more than `fix_budget_blocks` times | yes, with a report |

The gate fails open: if it cannot check (no `gh`, no network, a bug), the
session may stop and a note says nothing was verified.

## Which branches

The branch checked out in the hook's `cwd`, plus every branch the session
created or pushed (`git worktree add -b`, `checkout -b`, `switch -c`, `push`),
read from the commands in the session transcript. Remembered per session in
`<git common dir>/agent-done-gate/sessions/`.

## Wiring

| CLI | Where | How it blocks |
|-----|-------|---------------|
| Claude Code (also other models run through it) | `.claude/settings.json` Stop hook | `{"decision": "block", "reason": ...}` |
| Codex | `~/.codex/hooks.json` via `scripts/install_agent_done_gate.py` | same JSON shape; trust the hook once (`/hooks`) |
| Kimi CLI | `~/.kimi-code/config.toml` via the installer | exit code 2, reason on stderr |
| OpenCode | `.opencode/plugins/agent-done-gate.js` | on `session.idle`, sends the next step as a prompt |

Codex and Kimi run `~/.agent-done-gate/hook.py`, which finds the session's
repository and runs that repository's gate; repositories without the gate are
left alone. Run `python scripts/install_agent_done_gate.py` once per machine
(`--check`, `--uninstall`). The launcher logs to `~/.agent-done-gate/hook.log`.

While WAIT, the hook itself polls (up to `hook_wait_seconds`) before it answers, so
an agent does not spin. Agents can also wait explicitly:
`python scripts/agent_done_gate.py --wait`.

## Commands

```
python scripts/agent_done_gate.py            # verdict, exit 0 = may stop, 3 = continue
python scripts/agent_done_gate.py --json
python scripts/agent_done_gate.py --wait     # poll while WAIT (up to 9 min)
python scripts/agent_done_gate.py --hold "the user wants this local"
python scripts/agent_done_gate.py --release
```

Use `--hold` only when the user asked not to land a branch.

## Merge freeze

A pull request labelled `merge-freeze` holds `main` still for up to two hours
(`scripts/ci/merge_freeze.py`): the gate answers WAIT for other PRs,
`scripts/agent_land.py` requests no auto-merge, and the merge train enqueues
nothing. An older label no longer counts.

## Configuration

`.github/agent-done-gate.json`: `required_checks`, `main_workflows`,
`ignore_dirty`, `wait_budget_hours`, `fix_budget_blocks`,
`hook_wait_seconds`, `poll_seconds`.

# Coding run verification

What became of an order the lead gave a coding agent: on which model and CLI
it ran, in which repository, how it ended, whether the change it left behind
weakened the checks, whether it landed and what the repository's checks say
about it. Off by default. Code:
`dodaios/orchestrator/verification/` (the record and the checks) and
`dodaios/rsi/` (tags and the report).

```toml
[rsi]
enabled = true        # record every order a coding thread takes
verify = "observe"    # also scan what an ended run left behind, and ask GitHub
                      # what became of its commit
```

Both settings are closed to voice, chat, self-mod and agents
(`dodaios/core/self_mod/forbidden.py`): the person sets them in the config
file. A change needs an app restart.

## A run

A run is one order given to one coding thread, from the send to the end of the
thread's turn. It is keyed by the job id the hand-off returns, so `job_status`
and `verify_delegate` speak about the same thing. Runs live in
`data/verification.db`:

| Table | Holds | Can change |
| --- | --- | --- |
| `runs` | what the run was bound to at its start, and how it stands | yes |
| `steps` | what happened to it, one row per event | no: the table refuses `UPDATE` and `DELETE` |

Recorded at the start: the repository (the `origin` address without
credentials, the same for every worktree; a repository without a remote is
keyed by its main checkout), the commit, whether the folder is a linked
worktree, the brief, the domain, the requested model and effort, and the
version of the CLI the turn starts on. Recorded at the end: the turn's status,
tokens, cost and duration, the model that really answered (where the CLI's
stream names it), whether the thread switched model on the way, and whether the
person wrote into the thread.

The CLI version is read from the binary that is about to run and cached by that
binary's fingerprint (resolved path, modification time, size), because coding
CLIs update themselves while the app runs.

Recording is one listener on the chat service. It only queues; one daemon
thread reads git, the CLI version and the stores. A failure there is logged and
never reaches the turn. After an app restart, runs that were open are read back
from their thread's own log.

## Domains

A run is tagged with a domain twice: before it starts, from the paths its brief
names, and after it ends, from the files the agent's tools changed. Comparisons
use the first tag, because the second depends on the work itself.

Rules are ordered and the first wins: `testing`, `database`, `infra_ci`,
`docs`, `frontend`, `backend`, `other`. A folder name alone never makes a file
frontend (`ui/web/server.py` is a backend file). `refactoring` comes from the
wording of the brief. A domain counts from 15 % of the paths on; one path is
enough for `database` and `infra_ci`.

## The output scan (`verify = "observe"`)

When a run's turn has ended, its changed files are checked. The result is
recorded; nothing is sent to the agent and no turn is held.

**Only a run with a checkout of its own is judged.** That is a thread running
in a linked worktree (the app makes one for every thread the lead opens, see
below), or a session that made a worktree itself and wrote nowhere else. The
scan takes a snapshot of that folder (tracked and untracked files, through a
throwaway index, so the folder is untouched) and diffs it against the run's
start, which also shows what was changed from a shell. A run in a shared
checkout is recorded as `unattributed`: the difference to the start holds other
runs' edits too.

| Rule | Reports | Severity |
| --- | --- | --- |
| C1 | a test file was deleted (a rename is not) | violation |
| C2 | a test was switched off: `skip`, `xfail`, `.only`, `@Disabled` | violation; a `skipif` is ambiguous |
| C3 | a lint or type finding was silenced | ambiguous when it names the finding and says why; violation when bare, file-wide, or more than five in one change |
| C4 | a file that defines the checks was changed (test, lint, type and CI configuration) | violation when the edit weakens on its face (`continue-on-error: true`, `--passWithNoTests`), else ambiguous |
| C5 | a gate, a hook or an instruction file for agents was touched | violation |
| C6 | production code asks whether it runs under a test | ambiguous |
| C7 | assertions were removed from an existing test | ambiguous; violation when none is left |
| S1 | a deployment, secret or credential file was changed | violation |
| S2 | in this app's own repository: code that judges or guards agents was changed | violation |

A violation is something the diff shows on its face. An ambiguous finding is an
edit that is often legitimate and that someone has to look at. The rules are
constants of the code, not settings: what is checked must not be something a
prompt or a policy can tune.

Statuses: `clean`, `findings` (only ambiguous ones), `violations`,
`unattributed`, `unreadable`.

## A worktree of its own per thread

While the output scan is on, every coding thread the lead opens gets a linked
git worktree on a new branch: `<repository>/.worktrees/agent-<name>-<id>`,
branch `agent/<name>-<id>`, started from the remote default branch (fetched
first, at most once a minute), else from the checked-out commit. The thread
list still shows the thread under its project, with the worktree's name.

```toml
[rsi]
worktree_per_run = true                              # the default
shared_checkout_repos = ["github.com/acme/legacy"]   # these keep the project folder
```

- **The brief follows the folder.** An absolute path into the project folder in
  the lead's brief becomes the same file in the worktree, and two lines tell
  the agent where it is and that the main checkout is other agents' place.
- **It never fails the order.** The thread opens in the project folder as
  before when the folder is no repository, has no commit, opted out, is a
  sub-folder of its repository or itself a worktree (the thread list places a
  thread by its folder), when less than 2 GB are free, or when git fails.
- **A fresh worktree holds no installed dependencies.** `node_modules`, a
  virtual environment and other ignored files are not in it; the agent sets up
  what it needs, as in any new checkout.
- **Worktrees are put away, never their work.** A worktree without an
  uncommitted or untracked file is removed when its thread was deleted, or when
  its thread got no message for 12 hours (1 hour while less than 4 GB are
  free). Its commits stay on their branch; a branch without a commit goes with
  a deleted thread. A worktree with unfinished work always stays; the Git panel
  of the IDE lists it for cleaning up by hand. Putting away happens when the
  next worktree of that repository is made, never on a timer.
- **A thread finds its folder again.** Before a thread's turn starts, a
  worktree that was put away is made again at the same path, on the branch it
  was on (also one the agent renamed), so a later message to the thread works
  as before. That holds after the settings were switched off, too.

Only threads opened through the lead get one. A thread the person starts in the
IDE runs where the person put it.

## Landing and checks

The agent's own report never counts. After the scan, the app asks GitHub about
the commit the run's work area was on, with the person's own GitHub connection
(the app's, else the GitHub CLI's): one GraphQL call, only for a repository on
github.com, and only for a run with a checkout of its own that made a commit.

| Recorded | Values |
| --- | --- |
| `landing` | `none` (nothing changed, left uncommitted, or not pushed), `pushed`, `pr_open`, `pr_closed`, `merged`, `unknown` (GitHub was not asked or did not answer) |
| `ci_status` | `passing`, `failing`, `running`, `none`, `unknown` |

- **Merged work is judged where it landed.** The checks are those of the merge
  commit. A merge queue tests several pull requests as one and cancels the runs
  of all but the last; then the next commit on the default branch with checks
  speaks for the work when they passed (it holds the work). A red commit is
  never skipped for a green one after it. Without either, the checks of the
  pull request's head count.
- **A cancelled check is not a failed one.** GitHub rolls it up as a failure;
  here it reads as "no checks completed".
- **Unsettled evidence is read again**: while checks run, while a pull request
  is open (it may merge), and when GitHub was out of reach, at 2, 5, 10, 20 and
  40 minutes and then up to six hours after the run's end. A commit that shows
  no check after 5 minutes is taken to have none. This happens in the
  recorder's thread and survives an app restart. Nothing looks at an agent
  while it works.

## What the lead can ask

`verify_delegate` answers for a thread job from the record:

- `failed` when the turn failed, the scan found a violation (with the rule and
  the file), or the checks on the run's commit fail (with their names);
- `verified` when the turn ended well, the scan found nothing at all, the work
  area held nothing beyond the commit, and the checks on that commit pass;
- `unverified` otherwise, with the reason: checks still run, the commit has
  none, the work is not on GitHub, or the scan left points to look at. A clean
  scan alone does not prove the change works.

Without a record (recording off) the tool answers as before.

## The report

```
python -m dodaios.rsi.report                 # the last 30 days
python -m dodaios.rsi.report --since-days 7 --json
```

One row per cell: the domain a run was bound to, the model, and the runner with
its CLI version line (`claude-cli 2.1`). Per cell: runs, how their turns ended,
mean duration, what the scan said (`scanned`, `violations`, `unattributed`),
and what GitHub said (`merged`, `ci ok`, `ci red`). The report opens the record
read-only and calls no model.

## Limits

- It records, scans and reads GitHub. It does not send a follow-up prompt, hold
  the lead's answer or run tests itself. A repository without checks on GitHub,
  or one hosted elsewhere, never yields `verified`.
- Passing checks say the repository's own tests pass, no more. Whether a red
  check was red before the run is not looked at yet.
- Coding agents run as the same user as the app and have a shell, so nothing
  stops one from editing the record. The scan protects against shortcuts, not
  against an agent that sets out to deceive it.
- Codex names no answering model in its stream; the field stays empty there.
- The scan reads a diff. A test that asserts nothing new, or a check weakened in
  a way no rule names, passes it.

## Tests

`tests/unit/orchestrator/test_verification_{store,recorder,cheat_scan,gates,verdict,workdir,evidence}.py`,
`tests/unit/rsi/`, and tests through the real hand-off path in
`tests/contract/test_workspace_chat_threads.py`. The cheat-scan tests feed the
scan diffs that git itself wrote; the worktree tests make, put away and restore
worktrees of real temporary repositories.

# Coding run verification

What became of an order the lead gave a coding agent: on which model and CLI
it ran, in which repository, how it ended, whether the change it left behind
weakened the checks, whether it landed and what the repository's checks say
about it. It always runs, on every install; there is no switch. Code:
`dodaios/orchestrator/verification/` (the record and the checks) and
`dodaios/rsi/` (tags, policies and the report).

Every run is judged: its output is scanned, GitHub is asked about its commit,
and it gets a verdict. Whether the person notices any of this depends on the
coding policy the run is bound to (`hold`, see "Held runs and judged runs"
below). The factory policy does not hold, so out of the box nothing changes
for the person: the lead's job ends with the thread's turn, and no order is
sent to the agent.

```toml
[rsi]
# review = "triggered"      # for a run that holds: a model reviews outputs a fixed trigger picks
# review_paid = false       # true lets a review use an API key
# worktree_per_run = false  # true gives every thread the lead opens a worktree of its own
```

`enabled` and `verify` are no longer read. A config file that still sets them
loads, and their values are ignored.

The `[rsi]` settings are closed to voice, chat, self-mod and agents
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
thread reads git, the CLI version, GitHub and the stores. A failure there is
logged and never reaches the turn. If `verification.db` cannot be opened, the
app runs without a record. If the policy store cannot be opened, every run is
bound to the factory policy. After an app restart, runs that were open are
read back from their thread's own log.

## Domains

A run is tagged with a domain twice: before it starts, from the paths its brief
names, and after it ends, from the files the agent's tools changed. Comparisons
use the first tag, because the second depends on the work itself.

Rules are ordered and the first wins: `testing`, `database`, `infra_ci`,
`docs`, `frontend`, `backend`, `other`. A folder name alone never makes a file
frontend (`ui/web/server.py` is a backend file). `refactoring` comes from the
wording of the brief. A domain counts from 15 % of the paths on; one path is
enough for `database` and `infra_ci`.

## The output scan

When a run's turn has ended, its changed files are checked and the result is
recorded.

**Only a run with a checkout of its own can be pinned down.** That is a thread
running in a linked worktree (the app makes one for a thread the lead opens
when `worktree_per_run` is on, see below), or a session that made a worktree
itself and wrote nowhere else. The
scan takes a snapshot of that folder (tracked and untracked files, through a
throwaway index, so the folder is untouched) and diffs it against the run's
start, which also shows what was changed from a shell. A run in a shared
checkout is recorded as `unattributed`: the difference to the start holds other
runs' edits too, and its verdict is `unverified`.

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

With `worktree_per_run = true` (off by default), every coding thread the lead
opens gets a linked git worktree on a new branch: `<repository>/.worktrees/agent-<name>-<id>`,
branch `agent/<name>-<id>`, started from the remote default branch (fetched
first, at most once a minute), else from the checked-out commit. The thread
list still shows the thread under its project, with the worktree's name.

```toml
[rsi]
worktree_per_run = true                              # off by default
shared_checkout_repos = ["github.com/acme/legacy"]   # these keep the project folder
```

It is off by default for two reasons. The worktree starts from the remote
default branch, so the person's uncommitted and unpushed work is not in it.
And no dependencies are installed there. Until the app can take a snapshot of
the shared checkout at a run's start, a run in the shared checkout is recorded
as unattributed.

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
  as before. That holds after the setting was switched off, too.

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

## Held runs and judged runs

A run is not over when its thread's turn ends. It stays open while what the
turn left is checked, and the driver decides what follows. The coding policy
the run is bound to says whether the run is *held* (`hold`,
`dodaios/rsi/policy.py`). The question is asked per run.

- **A run that holds** does what the old `verify = "enforce"` did. The job the
  lead waits for reports only the outcome, and a finding brings a follow-up
  order to the agent.
- **A run that does not hold** (the factory policy) goes through the same
  checks, but the lead's job ends with the turn, as if there were no record.
  Nothing is sent to the agent. Where the driver would have sent a follow-up
  order, the recorder writes a `follow_up_withheld` step with the order and
  the reason it was not sent, and the run ends `failed` from the evidence.
  Where the driver would have asked for a review, the recorder writes
  `review_withheld` and judges the output without one. Running checks are
  still waited for, in the recorder's own thread, up to the policy's limit.
  If the thread takes a new order or the person writes into it meanwhile, the
  run is `detached`: it reads no more of the thread and is decided from the
  commit it left behind.

The rest of this section describes what the driver decides, and what a run
that holds does with it.

```
turn ends -> scan -> GitHub -> decide
  a check was weakened, or the repository's checks fail -> one follow-up order -> next turn
  checks still run                                       -> wait, read again
  otherwise                                              -> verdict
```

- **The decision is code, not a model** (`driver.py`). A weakened check (any
  violation of the scan) brings the order T2: restore what was weakened, and
  say so if a test is wrong for the asked behaviour instead of changing it.
  Failing checks bring T1: the names of the failing checks, read their logs,
  fix only that, weaken nothing. Both end by asking for one closing line,
  `RESULT: fixed | cannot-fix: … | needs-decision: …`. That line only ends a
  run early (`cannot-fix` fails it, `needs-decision` hands the question on);
  `fixed` proves nothing, the next check decides.
- **Fixed limits**, constants of the code that no prompt or setting raises: at
  most 2 follow-up orders per run and 16 per request of the person; none after
  the same finding came back, after a turn that changed nothing, after 400,000
  output tokens, or after an app restart. Running checks are waited for up to
  45 minutes after the turn's end.
- **One way in** (`send.py`). An order is sent only into a thread at rest whose
  last turn ended by itself, where nothing waits for the person and the person
  did not write since. It carries the app as author ("Output check"), so the
  thread shows who wrote it. Its intent is on record before it goes, and an
  order whose sending cannot be confirmed is never sent again.
- **The person always wins.** For a run that holds, a message from the person
  into the thread, a turn nobody here started, or a new order of the lead ends
  the run as `superseded`; nothing is sent after that. For a run that does not
  hold, a message from the person while its turn runs marks it. The turn's end
  is still recorded, and the run ends `superseded`.
- **The lead's wait** (`probe.py`). Until the verdict, the job reports
  `running`, with a progress that moves while the check is alive, so the wait
  neither ends early nor gives up. A question, an approval or a plan in the
  thread goes through at once. A check that shows no sign of life for 15
  minutes leaves the thread's own word, so a dead check never holds the answer.
  The note that a thread finished waits for the verdict the same way.
- **A model's second opinion, on fixed triggers** (`review.py`, with
  `review = "triggered"`, off by default). An output whose checks are not red
  gets one review when the scan left points to look at, the change touches a
  path where a mistake costs more (access, sessions, secrets, crypto,
  permissions, payments, billing, migrations, SQL), it changes more than 400
  lines or 15 files, or a random audit draws it (one in ten, fixed per run and
  output). One call without tools, by another model family than the worker's
  when one is signed in with a subscription, else the worker's own
  subscription; an API key only with `review_paid = true`. An approval must
  name the places it read, an objection the file and line of each finding, all
  in the diff; otherwise the review proves nothing and a `verified` becomes
  `unverified`. An objection brings the order T3 with the findings (it counts
  against the two follow-up orders). At most one review per output, 16 per
  request of the person and 50 a day; a due review that the budget stops leaves
  the output `unverified`. A review started before an app restart is not run
  again.
- **Leaks.** A `verified` run whose work merged is read again on GitHub 24 and
  72 hours after its end. If the checks on its merge commit fail by then, the
  run is marked `leaked`: the selector no longer counts it as passed, and a
  new policy it ran under is rolled back. Nothing is sent to the agent.
- **Verdicts**: `verified`, `unverified` (with the reason), `failed`,
  `superseded`, `needs_decision`. The jobs ledger shows them as `done` with the
  detail `verified` or `unverified`, `failed`, `cancelled` and `blocked`.

**Across an app restart** the lead's wait finds a thread's job again: the job's
probe is rebuilt from the thread's own record (a turn the turn host carried
over ends there), its progress reaches the wait, and a turn that neither ended
nor came back within 90 seconds of the first look is reported as interrupted.
This holds for every run, held or not.

**A quiet chat until the verdict.** Only for a run that holds: while that
coding work is still out, what the lead writes in that turn after the hand-off is
shown as its thinking, not as its answer; the continuation with the checked
result speaks again. Text written before the hand-off was already shown and
stays. Threads an agent opened with `coding-session` are not checked and keep
their own wake-ups.

## What the lead can ask

`verify_delegate` answers for a thread job from the record:

- `failed` when the turn failed, the scan found a violation (with the rule and
  the file), or the checks on the run's commit fail (with their names);
- `verified` when the turn ended well, the scan found nothing at all, the work
  area held nothing beyond the commit, and the checks on that commit pass;
- `unverified` otherwise, with the reason: checks still run, the commit has
  none, the work is not on GitHub, or the scan left points to look at. A clean
  scan alone does not prove the change works.

Without a record (the recorder could not start) the tool answers as before.

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

- It runs no tests itself. A repository without checks on GitHub, or one hosted
  elsewhere, never yields `verified`.
- Passing checks say the repository's own tests pass, no more. Whether a red
  check was red before the run is not looked at yet.
- Coding agents run as the same user as the app and have a shell, so nothing
  stops one from editing the record. The scan protects against shortcuts, not
  against an agent that sets out to deceive it.
- Codex names no answering model in its stream; the field stays empty there.
- The scan reads a diff. A test that asserts nothing new, or a check weakened in
  a way no rule names, passes it.

## Tests

`tests/unit/orchestrator/test_verification_{store,recorder,cheat_scan,gates,verdict,workdir,evidence,driver,follow_up,send_and_probe,review}.py`,
`tests/unit/rsi/`, and tests through the real hand-off path in
`tests/contract/test_workspace_chat_threads.py`. The cheat-scan tests feed the
scan diffs that git itself wrote; the worktree tests make, put away and restore
worktrees of real temporary repositories.

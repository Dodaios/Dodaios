# Self-building loop: coding projects

Dodaios knows the person's own repositories well enough to pick a suitable
issue now and then and ship it through their coding agent as a pull request.
It does this rarely, proves the change with the project's tests and CI, opens
a draft unless the person opted the repository in to landing, and every
build can be undone with one click. This is the `code` kind of the
[self-building loop](self-build.md); the code lives in `dodaios/self_build/code/`.

```
 brief ──> intake ──> triage ──> case ──> worktree ──> coding run ──> judge ──> pull request ──> CI ──> trial ──> merged / closed
 (git)     (poll)     (Python)  (ledger)  (branch)    (subscription)  (tests)    (draft)                (learn)
```

## The project brief

For each project in the Agentic IDE's library, `brief.py` keeps a brief in
`self_build_code.db` (data directory), stored in parts. Each part remembers the
key it was built for, and a refresh rebuilds only the parts whose key changed:

| Part | Holds | Rebuilt when |
|---|---|---|
| `git` | HEAD, branch, default branch, GitHub repository | HEAD moves |
| `structure` | stack, top folders, languages, a file map | the tree changes |
| `commands` | set-up and test commands, what CI runs | the tree changes |
| `conventions` | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CONTRIBUTING.md`, ... | one of them changes on disk |
| `activity` | recent commits, what the person worked on and where | HEAD moves |
| `github` | open issues and pull requests | each issue poll |
| `outcomes` | loop PRs merged, changed before merge, closed; lessons | each outcome |

Everything is deterministic (git calls and file reads, no model). An
unchanged project costs three git calls and a few file `stat`s per refresh.

## Intake and triage

The loop polls; a desktop has no public webhook URL. A repository is polled
only when all of these hold:

- it is in the IDE's library, and its `origin` is on GitHub;
- the GitHub account the IDE uses owns it, or administers its organisation,
  and has admin or maintain rights; it is not archived;
- it is not Dodaios' own source (that goes through the normal branch, pull
  request and done-gate path);
- the person works on it: opened in the IDE in the last 45 days, or their own
  commits are among the recent ones.

Each repository is asked for issues at most every 30 minutes. Triage
(`triage.py`) is plain Python. An issue is a candidate when it is open and
unassigned; the person wrote it or it carries an agent label (`agent`,
`dodaios`, `good first issue`, ...), so a stranger's text alone never starts
a build; it is labelled for agents or resembles an issue whose loop pull
request the person merged unchanged; its title and description make the scope
clear and it is not a task list or a long discussion; no pull request is open
for it; nothing in it mentions secrets, credentials, deployment, releases or
CI; and the repository has a test command. A repository where the person
closed loop pull requests without merging any is left alone.

A fit issue becomes a build case with signature `code:<owner>/<repo>#<n>`
through `service.admit`, so autonomy, the kill switch, the silent first days
and the daily code-run cap all apply. At most one new case per pass, and an
issue that ever had a build is not offered again. Proposals cost no model
call.

## Execution

A case in `building` runs only while the person is away from the computer
(for 15 minutes: no keyboard or mouse input, no turn spoken or typed to
Dodaios, no open call and no typing into a pane's terminal in the app; a
prompt Jarvis or an agent writes into a pane is not the person) and a
subscription coding CLI is free (`seat.py`): its plan login is signed in, its
own API-key variable does not reach it (the CLI would bill that key), it is not
in a usage cooldown and no usage window is over 80 %. Codex signed in with a
ChatGPT plan (`auth.json` holds the plan tokens and no key, and `config.toml`
does not force the API login) runs with `OPENAI_API_KEY` and `CODEX_API_KEY`
removed from its own child environment, so it bills the plan; the app's
environment is not changed. Claude Code with `ANTHROPIC_API_KEY` set is skipped.

Input idle time comes from `GetLastInputInfo` on Windows and `ioreg`'s
`HIDIdleTime` on macOS. On Linux the first reading that answers counts: GNOME's
idle monitor over D-Bus (`gdbus` or `dbus-send`, X11 and Wayland),
`xprintidle` (X11 sessions only), the freedesktop screen saver's active time
(KDE and others), systemd-logind's `IdleHint`. Without any of them only typing
in IDE panes counts. Otherwise the case waits, for
up to three days; a case that never got to run may be offered again later. The
kill switch stops a running build at its next step and puts the case back in
the queue; an undo stops it the same way and removes what it made.

0. The issue is read again from GitHub. Closed, assigned to someone other than
   the person, no longer passing triage, or a repository that is no longer the
   person's own: the case fails with a `not built: ...` note and nothing is
   done. GitHub not answering only puts the case back in the queue.
1. A fresh worktree and a new branch `dodaios/issue-<n>-<slug>` from the
   repository's default branch as GitHub reports it, fetched from `origin`,
   inside the repository (`<repo>/.worktrees/`). A branch of that name that
   already exists, here or on GitHub, stops the build. The person's checkout is
   never touched.
2. At most one planning call through the loop's shared seats
   (`self_build.brain.ask`: signed-in subscriptions, then keyless local
   models, never a per-token key), inside `cost.attributed(build_id)`. A
   `large` estimate stops the build. Without a seat there is no call and the
   coding agent plans itself.
3. A headless coding thread in that worktree (the IDE's thread surface, so the
   person can read every step). The prompt holds the brief, the issue, the
   relevant file outlines and the rules: small change with tests, follow the
   instruction files, never touch CI, deployment, secrets or instruction
   files, do not push. A question or plan card stops the run: the task was not
   clear enough for unattended work.
4. The judge (`judge.py`), which the agent cannot edit: nothing protected was
   changed, and the test commands the brief read before the run pass.
5. Push the branch (only when `origin` fetches from and pushes to that very
   repository) and open a pull request that says `Closes #<n>`, with the agent's closing
   summary (paths on this computer removed) and what was checked. Draft by default.

Nothing else leaves the machine: no issue comments, labels or reviews, and no
push to a repository the person does not own.

## Proof, landing and outcomes

`watch.py` looks at each open loop pull request on every pass (every five
minutes):

- Green CI is the proof (`attach_proof`, judge `tests+ci`) and the build goes
  on trial. Red CI fails it: the lesson is kept, the pull request closed and
  the branch deleted. A repository without CI is judged by the local tests
  once 15 minutes showed no check is coming.
- **Landing** is off by default. A repository listed in
  `[self_build] code_land_repos = ["owner/name"]` gets ready (non-draft) pull
  requests that are merged once CI is green.
- Merged as built counts `accepted`, merged after the person changed it
  counts `corrected`; the build is kept. Closed without merge: the branch and
  worktree go and the build is `undone`. Each outcome feeds the repository's
  profile (triage) and its brief (`outcomes`, read by the next prompt).

## In the ledger

The record's `artefact` follows the provenance convention every "built by
Dodaios" badge joins on: `{"type": "code", "id": <pull request URL>, "repo":
"<owner>/<repo>"}`, plus `stage` (`worktree`, `coding`, `pushing`, `pushed`,
`pull_request`), `branch`, `draft`, the local test result, the changed files
and `thread`, the coding run's agent-chat session, which the build detail opens
in the Agentic IDE's threads view. Before the pull request exists, `id` is
empty.

## Undo

The undoer closes the open pull request, deletes the remote and local branch
and removes the worktree, and stops a coding run that is still working. It
removes only `dodaios/` branches the build created itself, and a branch only
while it still points at the commit the loop pushed: commits or uncommitted
changes the person added keep the branch and worktree. A merged pull request
cannot be undone from here; revert it in the repository.

## Cost

Idle cost is GitHub reads and git calls, no model. A build costs one optional
planning call and one coding run, both on the person's subscription; the
ledger shows the planning call's tokens under the build.

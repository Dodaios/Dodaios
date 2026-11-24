# Try a pull request before it merges

The person's own Dodaios app always runs `main` from the main checkout.
A pull request or branch is tried in the **Dodaios Dev** app
([dev-instance.md](dev-instance.md)), never in the person's own app.

```
python scripts/dev_preview.py 1423       # pull request #1423
python scripts/dev_preview.py feat/x     # a branch on origin
python scripts/dev_preview.py --stop     # close the Dev app
```

The command:

1. closes the running Dev app and its own helper hosts (the processes started
   with `--instance dev`, or with a `--state` file ending in `.dev.json`); the
   default app's processes never match;
2. fetches the target into `refs/dev-preview/head` and checks it out in ONE
   reused worktree, `.claude/worktrees/dev-preview` (no new worktree per PR);
3. links `node_modules` from the main checkout when the lockfiles match
   (otherwise `npm ci`), and builds the frontend unless that frontend tree was
   built at the last load (a build takes about 3–5 minutes, a reload without
   frontend changes about one minute);
4. starts the Dev app from that worktree with the default app's interpreter
   and `DODAIOS_DATA_DIR=<main checkout>/data-dev`, so the Dev app keeps one data
   directory across previews, and waits until it is up.

There is one Dev app: the last load wins. Wake word, global hotkeys and chat
channels stay with the default app, so voice changes are tried there after
the merge.

## Pull requests from outside the repository

Loading a pull request runs its code on this machine with the accounts of
whoever runs the command: its npm scripts, its build and its app. The Dev app
has its own data folder, but the code has the whole machine.

So `dev_preview.py <number>` loads a pull request only when

1. its head commit is the tip of a branch of `origin` (only someone with push
   access puts a commit there; the head of a fork's pull request is on none).
   `origin` is asked at that moment, and no answer counts as no; and
2. where `gh` answers: it comes from this repository and its author is an
   owner, member or collaborator.

Any other pull request is refused before anything of it is checked out. Read
it on GitHub instead (`gh pr diff <number>`).

`--run-untrusted-code` lifts the refusal. It is for a person who has read
every changed file. Such a load never shares the main checkout's
`node_modules` (it gets an install of its own), always builds, and leaves no
build behind for a later load to reuse.

The same holds for any other way of running such a pull request. Look at it
in a linked worktree (`git worktree add`), never by switching the main
checkout to it, and do not commit, push or start a coding agent in that
worktree: the commit and push hooks run that tree's `scripts/ci/` files, and
the coding CLIs run the hooks its `.claude/`, `.codex/` and `.opencode/`
folders name.

## The agent's part

When a pull request changes something the person can see, load it into the
Dev app and check it there yourself. Then land it as usual: do not hold it
for the person's verdict, and do not add `no-auto-merge` for a preview. If
the Dev app is busy with another agent's preview, check the change another
way (a dev server and a visible browser) instead of waiting. Hold a pull
request only when the person asked to see it before it merges.

An agent never passes `--run-untrusted-code`. When `dev_preview.py` refuses a
pull request, read its diff, say what it does and what you could not check,
and leave running it to the person.

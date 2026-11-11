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
   and `JARVIS_DATA_DIR=<main checkout>/data-dev`, so the Dev app keeps one data
   directory across previews, and waits until it is up.

There is one Dev app: the last load wins. Wake word, global hotkeys and chat
channels stay with the default app, so voice changes are tried there after
the merge.

## The agent's part

When a pull request changes something the person can see, load it into the
Dev app and check it there yourself. Then land it as usual: do not hold it
for the person's verdict, and do not add `no-auto-merge` for a preview. If
the Dev app is busy with another agent's preview, check the change another
way (a dev server and a visible browser) instead of waiting. Hold a pull
request only when the person asked to see it before it merges.

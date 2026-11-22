# The lead's repository index

With many repositories in one conversation, the lead needs to know which ones
have agents working, which wait for the person, and which are quiet, without
asking for the status board on every turn. With `[rsi] repo_index = true` it
is handed a compact index with its messages. Off by default. Code:
`dodaios/rsi/repo_index.py` (the text) and `dodaios/rsi/repo_cards.py` (the
facts).

```
[Repos, rev 41: 3 of 23 in play. Detail: workspace-orchestrate status project=<name>; pull-requests-list.]
shop-web: 2 wait for you; PR 1 passing
notes: 3 busy; PR 2, 1 failing; main dirty
billing-api: idle; PR 1 running; conflict
Quiet: 20 repos.
```

## What is in it

One line per repository *in play*, a count for the rest. In play, in this order:

1. a coding thread there waits for the person (a question, an approval);
2. a coding thread there is working;
3. the current message names the repository;
4. it is among the last five repositories this conversation handed work to;
5. one of the person's open pull requests there fails its checks or is in
   conflict.

A repository is its `origin`, so a thread in a worktree counts for its
repository. `PR n` counts the person's open pull requests there with how their
checks stand (`failing`, `running`, `passing`). `main dirty` describes the main
checkout; `conflict` is a conflict in it or in an open pull request.

The index stays within 1,200 characters. A repository that waits for the
person is never dropped, only shortened; the others give way into
`More in play: a (busy), b (named), +3`.

It holds no commit ids, ages or branch names. Those change by themselves and
would change the bytes of the conversation on every look. `rev` rises only when
the content does.

## How it reaches the lead

- **A CLI seat** (Claude Code, Codex as the lead) gets the index after the
  person's words, and only when it differs from what that conversation was last
  handed, or after 20 turns. It is never part of the system prompt and adds no
  tool.
- **The app's own brain** gets it in the per-turn context that travels with the
  message and is not kept in the history.

When no repository is in play, nothing is sent.

## Where the facts come from

Which coding threads work or wait is read from the app's memory when the index
is rendered. What needs `git` (which repository a folder belongs to, the state
of a main checkout) is read by a background refresh, started when a coding
thread's turn ends, and at most every three seconds. The open pull requests
come from one GitHub call for all repositories, with the person's own GitHub
connection, in the same refresh, at most once a minute and only while a
repository on GitHub is in play. Rendering never starts a `git` process and
never touches the network, so it can be one refresh behind. When GitHub does
not answer, the last known state stays.

The done gate is not in the index yet; `pull-requests-list` answers for the
details of a pull request.

## Tests

`tests/unit/rsi/test_repo_index.py`, `tests/unit/rsi/test_repo_cards.py`, and
per seat `tests/unit/agent_chat/test_lead_turn_contract.py` and
`tests/unit/brain/test_lead_doctrine.py` (the prompt a CLI seat re-reads as its
system prompt is byte-identical with the index on).

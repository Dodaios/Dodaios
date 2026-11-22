# Agent briefs

A coding agent that Dodaios starts gets one thing from the conversation it came
out of: the brief. This page says what happens to a brief between the moment
someone asks for work and the moment the result comes back.

Four places write briefs for coding agents: the assistant in its chat, the
voice model in a call, the composer that turns a spoken sentence into a prompt
for a terminal pane, and a society agent that opens a coding thread. All four
pass the same steps, in `dodaios/briefs/`.

## Why it works this way

The steps follow what was measured on coding agents and what the model vendors
publish about their own models:

- A missing fact costs an agent more than plain wording. Replacing an everyday
  word with a technical one did not change results in studies; leaving out the
  wanted behaviour did. So nothing here polishes wording. It finds the facts a
  request leaves open.
- Rewriting a request helps only with facts read from the repository. A
  detail added from memory made results worse than no rewrite.
- A test that fails before the change is the strongest single hint an agent
  can get. Every vendor's guide asks for a checkable end.
- Agents rarely ask on their own. One round of questions before the start wins
  back most of what an underspecified task loses.
- An agent's "done" is a claim. Claims of completion were wrong often enough
  in measurements that they must be checked against what the run left behind.
- The vendors disagree on a few points (whether to ask for verification,
  whether to ask for a plan first, which part of a prompt goes last), so one
  wording does not fit every model.

## Before the brief is written

The writer can ask for the facts first: `delegate` with `options.prepare`, the
target and what the person wants as the task. Nothing is sent. The answer, the
*brief kit*, holds:

| Part | What it is |
|---|---|
| Starting points | Files whose names and contents fit the request, with the lines that made them fit. Candidates for the writer to choose from. |
| Project checks | The commands the project's own files call the end of a change (its instruction files first, then its manifests). |
| What their words mean | Entries of the project's glossary for words the person used. |
| What their words leave open | Phrases such as "looks bad" or "is broken", each with the fact that would close it. |
| What makes it precise | For the kind of work (a defect, a speed problem, the interface, data, text and so on): the few facts a brief of that kind needs. |
| Open points | What the request does not say, with the question to put to the person. The writer settles each from memory, the conversation or the repository first, and asks once, on one question card, only when the answer would change the work. |
| Recipient | What the receiving model's vendor says about writing for it. |
| Effort | The effort the job calls for, when the person named none. |

### The glossary

People do not call things what the code calls them, least of all when they
dictate. When a writer works out what a word of the person stands for, it
passes that with the hand-off (`options.resolved`), and it is kept per project.
The next request that uses the word, also misheard, starts from it.

The assistant shows the learned words with `agent-briefs-get` and forgets one
with `agent-briefs-forget-word`. They are stored in the app's data folder, one
file per project.

## Before the brief leaves

Every brief is checked. The check is code, not a prompt, because the same rules
as text in a prompt did not hold. It looks for:

- a path that does not exist in the project (and names the nearest real one);
- no file to start from, when the work is on existing code and the repository
  has files that fit;
- a numbered procedure in place of a goal;
- a suspected cause or fix stated as a fact;
- no "done", or one that is true of every change ("tests pass");
- rules in capital letters, a request to show reasoning, time pressure;
- a git limit the person did not ask for, or a "change nothing" on a request
  for a change, or a change ordered when they asked for an analysis only;
- words that leave the agent to guess ("looks bad", "somehow", "properly");
- a reference into a conversation the agent cannot see;
- a brief that is not written in English, unless the person's brief wishes name
  another language. The repository's code and commits are English, and the
  agent answers the person in their language by itself.

A brief with such a fault goes back to its writer **once**, with what to fix
and the brief kit. Nothing was created or started. The next brief from the
same conversation for the same folder is sent as it is, whatever the check
still finds; what it found is recorded and shown with the receipt. A hand-off
is delayed by one revision at most and never refused.

A follow-up into a thread that already works on an order is held to fewer
rules: it may point back into that thread and needs no "done" of its own.

The composer for spoken instructions writes on a voice turn's clock and types
into a pane the person is looking at. Its brief is checked on its wording and
recorded, and never sent back.

## What the agent receives

The writer's brief is not changed. Around it:

- **The order of its parts** follows the receiving model: outcome first for
  most, long context first and the task last where the vendor says so.
- **The person's own words** are added verbatim after the brief, so the agent
  can see what was really said. A long message that covers more than one
  order is not added. Their head says the words were said to the assistant and
  that an agent they ask for is the one reading them: read as an order, "send
  an agent to ..." made agents start agents of their own (3 of 7 real runs;
  0 of 8 with the head).
- **One closing line** where the receiving model's guide asks for it.
- **The effort** is picked from the size of the job when none was named: a
  small, well-specified change runs lower, hard or open-ended work higher. It
  never goes above `high`; the top levels are the person's to ask for. The
  model is never switched.

The thread shows the brief as it was written.

### Standing rules

What holds for every order is not written into each brief. A coding agent that
Dodaios starts gets it once: nobody is watching the run, the order sets the
scope, a step is done and not announced, a claim rests on a result from this
run, and the report leads with the outcome. It ends on the case that keeps the
rules true: someone who writes in the thread is present and gets a direct
answer.

A thread opened by the assistant has the rules in its system prompt where the
CLI has one, and in front of the first message of each conversation where it
has none. A thread or pane the person opened gets them with the first order
Dodaios sends into it.

## While the agent works

An agent's question goes to the one who handed the work over first. The
assistant sees the question with its options and may answer it when the
person's own words, a decision they made or the repository settles it. It says
in its reply what it answered. Otherwise the question goes to the person.
Approvals and plan decisions are never answered for them.

The agent asks through its own question tool: its standing rules say so, and a
brief says only what to ask and when. The assistant answers with
`workspace-orchestrate`, action `respond`. An agent that asks in its reply
instead ends its turn; the answer is then an ordinary follow-up message, and
the order's done-when points stay with the thread (see below).

An answer the assistant gives is on record as its own (source `delegator`).
The agent reads that Dodaios answered on the person's behalf, so its report
never says the person chose it, and the settled card in the thread says
"Nova answered this for you". A question asked mid-turn (Claude Code's
question tool) is answered under the job that asked, since the same turn goes
on; one asked at the end of a turn starts a new turn, followed as a new job
with the same order.

## When the agent reports

Each done-when point of the order is held against what the run left behind:

| Point | Evidence |
|---|---|
| A command | Whether the agent ran it in this turn, and how the last run ended. |
| A test | The last test command of the turn. |
| A report ("report the cause") | That a report was delivered. What it says is for its reader. |
| A file | Whether it exists in the folder. |
| Merged or shipped | The state of the pull request the agent named; else whether the turn's commits are on the default branch. |
| Something visible | Left open: only a look can confirm it. The check names the picture the report points at. |

A point comes back *confirmed*, *contradicted* or *open*. The result travels
with the agent's report to the assistant and outranks the report; the
assistant sends what is contradicted back to the same agent before it calls the
work done. `verify_delegate` answers from the same check.

How a command line is read:

- Only what the line runs counts. A check that is named in a commit message,
  in a file being written or in an `echo` did not run. The same check started
  another way (`uv run pytest`, another Python, more flags) is that check;
  another program started the same way (`python -m pip`) is not.
- A line of several commands ends with the last one's exit status. For a
  command in the middle of it (piped into `tail`, followed by an `ls`) what
  its output says decides: `9 passed`, `1 failed`. A silent output leaves the
  point open.
- A pass counts for the state the work ended in. When files were changed after
  the last run of a check and it was not run again, its point is open, and
  the check says how many changes followed.

A follow-up message that names no done-when points goes on with the thread's
last order that did: when its turn ends, that order's points are checked
against everything since the order began, and the check says so. Each turn
keeps its own end on record; a later turn of the thread never replaces it.

The check reads the thread's record of tool calls, the folder and, for a pull
request, GitHub. It runs nothing in the repository and asks no model. A CLI
that records no tool calls leaves its points open.

## The record

Every order is kept in `briefs.db` in the app's data folder: what the person
said, the brief as first written and as sent, what the check found, who
received it on which effort, how the run ended and how the done-when points
fared.

```
python -m dodaios.briefs.report                 # the last 30 days
python -m dodaios.briefs.report --since-days 7 --json
```

The report sets first drafts against outcomes, so a change to the rules can be
judged on real orders. A fixed set of dictated requests
(`tests/fixtures/brief_quality`) guards every such change: an old kind of
brief must still come back with the right findings, and a good one must pass.

## Switches

`[briefs]` in `dodaios.toml`; each part can be switched off on its own.

| Key | Default | What it does |
|---|---|---|
| `check` | `"revise"` | `revise`: a brief with a fault goes back once. `note`: checked and recorded, never sent back. `off`: every brief goes out exactly as written; nothing is looked up, assembled or recorded. |
| `auto_effort` | `true` | Pick the effort from the job when none was named. |
| `standing_rules` | `true` | Give an agent the standing rules once. |
| `lead_answers_questions` | `true` | Let the assistant answer a coding thread's question. |
| `acceptance` | `true` | Check the done-when points when the agent reports. |
| `record` | `true` | Keep orders and outcomes in `briefs.db`. |

## What it does not do

- It does not judge whether a brief is *right*. The check finds shapes (a
  missing path, a procedure, capital letters); a brief can pass it and still
  describe the wrong problem.
- It does not check terminal panes after the fact: the done-when check covers
  chat threads, where the app has the agent's record of tool calls.
- It does not learn by itself. The record and the report are there so a person
  can change the rules on evidence.

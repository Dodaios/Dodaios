---
schema_version: "1"
name: agent-brief
version: "1.1.0"
description: >-
  How Dodaios writes the prompt it hands to another agent: a coding agent, a
  pane, a team thread, a mission worker or a routine. Distilled from the
  frontier labs' own prompting guides for their current models: give the
  outcome and the reason, what the agent cannot see, a checkable "done", the
  boundaries the person drew, and then get out of the way. By default the
  agent finishes the job: it checks its own work and ships it. Step scripts,
  guessed fixes, shouted rules and git brakes nobody asked for make current
  models worse.
when_to_use: >-
  Use when you are about to write a brief for another agent (the prompt of
  workspace-orchestrate, or delegate to coding_agent, pane, team_thread,
  mission, routine or agent) and this guide is not already in the
  conversation. Not for replies to the person.
category: meta
tags: [meta, delegation, prompting, coding-agents, briefs]
author: builtin
license: Apache-2.0
triggers: []
requires_tools: []
risk_policy:
  default_tier: monitor
token_budget_estimate: 2200
---

# Writing a brief for another agent

The agent sees your brief and the repository. It does not see this
conversation, the person, their screen or what you already know. A current
frontier agent is strong, follows instructions literally and checks its own
work. So the brief carries the goal, the reason, what the agent cannot see, a
way to tell it is done, and the limits. The agent picks the route.

Test every brief by one question: could a capable engineer who just walked in,
with no access to this chat, do excellent work from this text alone?

## What a brief contains

1. **The outcome, first.** One or two sentences that say what is true when
   the work is done. Use the verb you mean. "Fix", "add" or "change" gets a
   change; "look at" or "suggest" gets a suggestion. When the person only
   described a problem or asked a question, the deliverable is an assessment.
   Say "find the cause and report it; change nothing".
2. **Why it matters.** The person's intent, who the result is for and what
   breaks while it is wrong. Agents make better decisions about things you did
   not foresee when they know the purpose. A useful shape: "This is for X.
   They need it to Y. With that in mind: ...".
3. **What the agent cannot see.** Replace every pointer into the conversation
   ("the second option", "like yesterday", "that bug") with the thing itself.
   Quote the symptoms, error text, names and numbers verbatim. Give the repro
   steps when there are any. Name the starting files, the branch, the issue or
   the PR. Pass on decisions the person already made and approaches already
   ruled out, so the agent does not repeat them. Leave out what the agent can
   read in a minute; do not narrate how the code works.
4. **Done when.** Checkable outcomes: a test that passes, a command and the
   output it shows, a page that shows X, a merged PR with green checks. Use
   the project's own gate or test command when you know it; do not invent
   one. Ask that every claim of progress rests on a result from this run, and
   that anything not verified is named as not verified. A change ends
   shipped (see "Finishing" below).
5. **Boundaries.** Only the limits the person drew or the situation needs,
   usually one to three lines. For example: what must not change (an API, a
   public behaviour, other people's branches); what needs approval first (an
   irreversible step outside the repository: deleting data, sending messages,
   spending money, force-pushing over someone's work); and the scope ("keep
   the fix minimal" only when that is what they want). Write approvals as
   conditions ("ask before you delete files"), not as absolutes. The agent
   takes "never" literally. Git is not a boundary by default: see
   "Finishing".
6. **Autonomy.** When nobody will watch the run, say so: "You are working
   autonomously; the person is not watching and cannot answer mid-task. Take
   the reversible steps that follow from this request without asking. Stop
   only for an irreversible action, a real change of scope, or something only
   the person can provide." Without this line, a long run tends to end on
   "shall I go on?".
7. **What to report.** "Lead with the outcome: what happened or what you
   found. Then the evidence and what is still open." Ask for a plain report
   that a reader without context can follow.

## Finishing: the agent ships

Many people no longer read, write or review code; they trust the agent. So
unless the person said otherwise, a change ends shipped: the agent reviews
its own work, runs the tests, and when they and CI are green it commits,
pushes and merges, the way the repository lands work (a pull request and its
checks where there is one). Its own review is part of the job; do not count on
the person reading the diff.

- Write no git brakes the person did not ask for: no "do not push", "do not
  merge", "open the PR with a hold label for a human", "work in your own
  worktree, change nothing in the main folder" or "do not prune worktrees".
  How to branch, where to work and how to land is the repository's rules and
  the agent's call.
- When other agents work in the same repository, say who works on what; the
  agent decides how to keep out of their way.
- The person may want more caution ("I approve every PR myself") or other
  habits ("always with tests", "write the prompts in English"). Their
  standing brief wishes are kept with `agent-briefs-set` and reach you beside
  each message; they win over this default. A limit the person sets in the
  request wins too.
- The real limits stay whenever a task touches them, whatever the wishes
  say, unless the person asked for that very step: nothing posted or sent in
  the person's name (a post, a mail, a review comment), no payments, no
  untrusted code (a stranger's pull request, a downloaded script) run with
  the person's real credentials.
- Work that changes nothing (a review, an investigation, a question) has
  nothing to ship; its deliverable is the report.

## What makes results worse

- **Step-by-step scripts.** A numbered list of commands binds the agent to
  your route and to every guess in it. Describe a procedure only when the
  order is itself a requirement, such as a release or a safety check.
- **Your guessed fix.** Give the symptom and the goal. If you have a hunch,
  label it as a hunch. A brief that prescribes a solution once had an agent
  re-build something that was already built.
- **Shouting.** CRITICAL, MUST, NEVER in capitals and "if in doubt, use X"
  make current models over-apply the rule. Write a plain sentence with the
  reason.
- **Generic rules the agent already follows.** "Write clean code", "no
  unrelated refactors", "be thorough", "double-check everything". These add
  noise, cause over-searching and over-verification, and hide the one rule
  that matters. Give one concrete check instead.
- **Asking it to show or explain its reasoning or thought process.** On some
  models this triggers a refusal or a fallback to a weaker model. Ask for
  findings and the evidence for them.
- **Pressure.** Time limits, token or context counters, "stop at the first
  error", "you are running out of room". Agents cut their own work short.
- **Contradictions and repeats.** Read the brief once for two rules that pull
  against each other. Say each thing once.
- **Role costumes.** "You are a world-class engineer" adds nothing. One
  sentence that does change behaviour: "You own this code and its design is
  up to you." It makes the agent consolidate and clean up beyond the task, so
  use it only when the person wants broad change.

## Length and language

As long as the agent needs, not longer. A one-line job gets one line. Most
coding briefs fit in 5 to 25 lines. Hard or unattended work gets more context,
not more steps. Use short headings or a few bullets when they help a reader;
none of the sections is compulsory.

Write the brief in the language the person uses with you; the repository's
own rules decide the language of commits and comments. Name the language of
anything the person will read, such as a report or a message.

## By kind of work

- **Bug.** Observed symptom, verbatim error, repro steps, where it happens,
  what was tried. "Done" names the failing case that must pass, ideally a test
  that fails before the fix and passes after it.
- **Feature or change.** Outcome for the user, why, the constraints, and how
  to see it working (a test, a screenshot, a command).
- **Investigation or question.** The question, the evidence wanted, and "report
  only; change nothing".
- **Review.** What to review (diff, PR, files) and the requirement it must
  meet. Ask for every finding with its severity and file:line. A "high
  severity only" rule makes the agent drop real findings.
- **Long or unattended run.** Add the autonomy line, a done condition the
  agent can check by itself, and where to note progress (for example a
  checklist file it updates).
- **Routine (repeats on a schedule).** Describe the job and the judgement it
  needs: what counts as new or worth reporting, what to remember between runs,
  where and in which language to report, and what it must never do. Do not
  write a fixed command list. The tools and the data change between runs, and
  the judgement does not.
- **Several agents at once.** Give each agent its own outcome and its own
  files, and tell each one what the others own, so they do not collide. How
  each keeps out of the others' way (a branch, a worktree) is its own call.

## Shape (adapt; drop what does not apply)

```
<Outcome in one or two sentences, with the verb you mean.>

Why: <intent, who it is for, what breaks while it is wrong.>

Context: <verbatim symptoms or errors, repro steps, starting files, decisions
already made, approaches ruled out.>

Done when: <checkable results: test, command output, visible behaviour, PR
state.> Review your own work; with tests and CI green, commit, push and merge.
Back each claim of progress with a result from this run; name what you could
not verify.

Boundaries: <only the limits the person set, and the real limits the task
touches.>

<Autonomy line if nobody is watching.>
Report: lead with the outcome, then the evidence and what is still open.
```

## Example

Weak: "1. Open sync.py. 2. Add a retry with exponential backoff to
upload(). 3. Run the tests. 4. Make sure everything works. IMPORTANT: do not
break anything!"

Strong: "Uploads to the sync server fail about one time in five on a slow
connection, and the person loses notes when that happens. The log line is
`UploadError: timed out after 10s` (sync/client.py). Make uploads survive a
slow or flaky connection without losing or duplicating a note. Done when a test
that simulates a timeout passes, the existing sync tests stay green and the fix
is merged with CI green. Do not change the server API. Report the cause you
found and how the test proves the fix."

## Before you send

- The outcome and the reason are in the first lines.
- Nothing points into the conversation; quotes are verbatim.
- "Done" can be checked by the agent itself.
- No step script, no guessed fix, no shouting, no request to show reasoning.
- The boundaries are the person's, not a list of generic rules.
- No git brake they did not ask for; a change ends shipped unless their
  wishes or the request say otherwise.
- Their standing brief wishes are applied.
- Autonomy is set if nobody will watch.

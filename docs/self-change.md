# Safe self-improvement

Every change the assistant makes to its own behaviour is recorded, checked
before it counts, and can be undone. The owner decides everything that defines
who the assistant is or how it is judged.

```
 propose ──> gate ──> trial ──> live
              │         └────> reverted (one click, exact previous text)
              ├─ fail ──────> blocked (never applied, one written notice)
              └─ core / unverified ──> proposed (waits for the owner)
```

## The registry: `dodaios/self_change/`

One row per change in `self_changes.db`: the surface and target, a version
number per target, the exact text before and after, the unified diff, the
author (which agent, which turn), the reason, the gate result and the state
(`proposed`, `trial`, `live`, `reverted`, `blocked`).

| Surface | What it covers | Recorded by |
|---|---|---|
| `skill` | skills the assistant authors or edits | the skill authoring path (AI creator, self-build) |
| `prompt` | the persona / system prompt override | `registry.propose` |
| `instructions` | the standing-instructions file | `registry.propose` |
| `tool` | tool descriptions, plugin and tool installs | `registry.propose` |
| `code` | self-build code changes | `registry.propose` |
| `config` | a setting of the assistant itself | `registry.propose` |
| `routine`, `agent` | self-built routines and agents | mirrored from the self-build ledger |

## The gate

Offline, no model call, never on the live state:

- skills: the file parses and validates, its code blocks pass the safe-import lint;
- prompts, instructions, tool descriptions: the lead routing golden set
  (`docs/lead-routing-evals.md`) is replayed with the candidate applied in a
  sandbox and must score at least what it scored before; every result is stored;
- code: the tests named for the change run in a scratch checkout;
- everything: no invisible characters, no credential-shaped text.

A check answers `pass`, `fail` or `unavailable`. `fail` blocks the change.
`unavailable` (no golden set in this build, no tests named, a surface without
a check) does not block it, but it is not trusted: it waits for the owner.

## Core changes need the owner

A change is core when it touches the persona, a safety, trust or provider
setting, the provider lock, evaluation code or the golden set, the judges, the
audit, the registry itself, `AGENTS.md`, or when its text tries to move the
goal, the limits or the approvals ("ignore previous instructions", "without
asking"). A core change is recorded as `proposed` and applied only after the
owner approves it on the Trust page (Self-changes). No gate result stands in
for that.

## Tamper-proof

- The agent's tools get no route into the registry: nothing records a result,
  approves, grades or edits the audit. The owner routes
  (`/api/self-change/*`) only approve, refuse, keep and roll back.
- The `evaluations` and `history` tables refuse `UPDATE` and `DELETE` (triggers);
  a recorded change cannot be deleted.
- Every step is also written to the owner's audit log (`dodaios/trust/audit.py`,
  hash chained), with the author and, for owner decisions, the approval.

## Rollback

`rollback(id)` writes back the exact bytes from before the change (a created
thing is removed) and first unwinds any newer change on the same target.
`rollback_since(ms)` reverts everything still in effect since a time. Mirrored
self-build changes are reverted through the self-build ledger's own undo.

## What the owner sees

Settings, Trust and privacy, Self-changes: each change with state, reason,
author, version, diff and regression result, with Approve / Refuse / Keep /
Roll back, and "Revert every self-change from the last hour, day or 7 days".

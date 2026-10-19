# Self-building loop

Dodaios notices what the person keeps doing and builds what would take that
work off them: a memory, a skill, a routine, a specialised agent or a code
change in one of their projects. It does this without being asked, keeps
only what proves useful, and lets the person see and undo everything.

```
 observe ──> decide ──> build ──> prove ──> trial ──> keep / archive
 (free)     (1 call)  (sandbox) (judge)   (live,     (measured)
                                           undoable)
```

- **Observe** counts repetition in the person's own actions. No model is asked
  and untrusted content (web pages, tool results, other agents) is never
  evidence.
- **Decide** picks the smallest artefact that meets the need, in this order:
  memory, skill, routine, agent, code. "Build nothing" is a valid answer.
- **Build** goes through the existing creation paths (proposals, the skill
  creator, routines, the roster, coding threads), never a new back door. No
  agent gets a tool that creates agents.
- **Prove**: a judge the builder cannot edit checks the build before it counts
  (replay of the turns that triggered it, shadow runs, tests and CI).
- **Trial**: the build is live, labelled "built by Dodaios" and undoable with
  one click.
- **Keep or archive** is decided from use, corrections and cost. Archived
  builds are restorable, never deleted.

## The ledger: `dodaios/self_build/`

Every build has one row in `self_build.db` (in the data directory). Each stage
writes there and nowhere else.

| Module | Holds |
|---|---|
| `records.py` | `Kind`, `State`, `Outcome`, `BuildRecord`, the allowed state moves |
| `ledger.py` | `BuildLedger`: `open_case`, `set_state`, `attach_proof`, `attach_artefact`, `record_use`, reads, rejections, meta |
| `policy.py` | `admit` (may a build open, and how far may it go), `trial_over`, `settle`, the kill switch, the silent first days |
| `undo.py` | `UndoRegistry`: one undoer per kind |
| `cost.py` | `attributed(build_id)` tags model calls; `spent(record)` sums them from the cost ledger |
| `service.py` | `SelfBuild`, started at boot; `current()` returns it; `register_builder(kind, fn)` |

States:

```
proposed → building → proving → trial → kept | archived | undone
    │          └──────────┴─────────┴──> failed
    └─> rejected
```

`kept` and `archived` can still be undone; `archived` can be kept again.

### How a builder plugs in

1. Register an undoer for the kind: `service.undo.register(Kind.SKILL, fn)`. A
   kind without an undoer is never built, only proposed.
2. Register a builder: `service.register_builder(Kind.SKILL, fn)`. It is
   called with the record when a proposal is accepted.
3. To open a build, call `service.admit(kind, signature)`. `start` is `None`
   (do not open), `PROPOSED` (open as a card) or `BUILDING` (build now).
4. Open it with `ledger.open_case(kind, signature, title, case=..., evidence=...,
   state=admission.start)`. `title` is one sentence the person reads.
5. Run every model call inside `cost.attributed(record.id)`.
6. Record what you created with `attach_artefact(id, artefact, undo)`, the
   judge's verdict with `attach_proof`, then move the record to `trial` or
   `failed`.
7. Report each use with `record_use(id, Outcome.ACCEPTED | CORRECTED | USED |
   IGNORED)`.

A `signature` is a stable key for the need (for example
`routine:weekly-sales-report`). Only one build per signature can be open at a
time, and a signature the person rejected or undid `max_rejections` times is
not offered again.

## Settings: `[self_build]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | master switch |
| `silent_days` | `7` | the first days after the loop first ran only record cases |
| `memory`, `skill`, `routine`, `agent`, `code` | `trial`, `suggest`, `suggest`, `suggest`, `suggest` | autonomy per kind: `off`, `suggest`, `trial`, `full` |
| `trial_days`, `trial_uses` | `14`, `10` | a trial ends at whichever comes first |
| `max_builds_per_day` | `3` | builds past the proposal stage per day |
| `max_agents_per_week` | `1` | |
| `max_open_trials` | `5` | |
| `max_code_runs_per_day` | `1` | |
| `max_rejections` | `2` | |

At `suggest` a card asks first. At `trial` the build goes live on trial; an
unused trial is archived on its own, a used one waits for the person's keep.
At `full` a used trial is kept on its own too.

## REST: `/api/self-build`

`GET ""` (builds and status), `GET /digest?hours=24`, `POST /pause`
(`{"paused": true}` is the kill switch), `GET /{id}` (record, history, cost),
`POST /{id}/accept`, `POST /{id}/keep`, `POST /{id}/undo`. Every change
publishes `SelfBuildChanged` on the app bus, and the WebSocket forwards it.

## Rules enforced in code

1. Background work for the loop never bills a per-token key. It runs on
   subscriptions or local models, or it waits.
2. Only the person's own actions are evidence.
3. The builder cannot edit the judge, the budgets, `[self_build]`, the kill
   switch, `security.*`, secrets or the self-mod allowlist.
4. No agent tool creates agents; only the trusted builder service does.
5. A build without an undo path is not created.
6. Hard caps per day and week (above).
7. Nothing leaves the machine on the loop's initiative: no messages, emails or
   posts, and no comments in other people's repos.
8. Dodaios never speaks about its builds unprompted.

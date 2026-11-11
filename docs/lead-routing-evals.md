# Lead routing evals

The lead is the one assistant the person talks to. Its first move decides
everything: answer in text, ask a society agent, brief a coding pane, search
memory, change a setting. Every routing guard in the lead was added after a live
incident. This eval measures them, so a prompt or tool change shows its effect
on routing before it ships.

## What it measures

A golden set of simulated requests (English and German, with a few Spanish and
Portuguese), each with the expected **first move**:

- the first tool the lead calls, or "no tool" when it must answer directly;
- the key arguments (target agent, coding pane id, section, action);
- for risky actions, that the chosen tool is an approval-gated (ask tier) tool.

It scores only the first move. No tool is ever executed.

Categories: `delegate_agent`, `ask_agent`, `coding_pane`, `team_thread`,
`mission_artifact`, `status`, `memory`, `settings`, `mail_calendar`,
`web_browser`, `computer_use`, `routines`, `costs_ui`, `answer_directly`
(knowledge questions that must not spawn work), `approval`, `ambiguous`
(misheard names, missing context).

The golden set lives in `tests/fixtures/lead_routing/*.yaml`. Tool names come
from the lead's real catalog (the router-tier tools plus the folder tools; the
machine-dependent loaders for command-line tools, plugins and MCP servers are
left out, so the catalog is the same on every machine).

## Offline replay (CI)

`tests/unit/lead_routing/` runs on every CI run and calls no model:

- the set is well formed and covers every category;
- **catalog drift**: every expected tool, argument key and enum value must exist
  in the real lead catalog, so a renamed or removed tool turns the test red;
- the scoring and the report are exercised on recorded responses
  (`tests/fixtures/lead_routing/recorded/*.json`).

`recorded/reference.json` is synthetic: it is derived from the expectations, so
it proves the plumbing, not a model. Regenerate it after editing cases:

```
python scripts/lead_routing_eval.py --write-reference
```

To replay real model answers, store them with a live run
(`--save-recording`) and score them offline at any time:

```
python scripts/lead_routing_eval.py --replay eval-results/lead-routing-<seat>-<stamp>.recording.json
```

Plain `python scripts/lead_routing_eval.py` replays every file in `recorded/`
and prints accuracy per category and seat.

### Cases that wait for a tool

A case with `requires: [tool, ...]` is skipped, and reported as skipped, until
every named tool exists in the lead catalog. Use it for tools that are in an open
change. When the tool lands the case starts counting without any edit. `also_accept`
lists tools that count as correct when they exist but are never required to exist.

## Live run (opt-in, bills the seat)

A live run sends every case to one real seat with the full lead tool catalog,
records the first tool call and stops the stream. It never runs in CI and never
runs by default:

```
DODAIOS_LEAD_ROUTING_LIVE=1 python scripts/lead_routing_eval.py --live --seat <provider> [--model <id>]
```

- The seat is always named by you. Nothing is chosen or switched for you.
- Before it starts, the script prints how many model calls it will make, about
  how many input tokens each carries, and whether this bills an API key, spends a
  subscription allowance, or runs on a local model. Then it asks you to type the
  seat name (skip with `--yes`).
- It follows the background policy: while a subscription is connected, a
  per-token API key seat is refused unless you add `--allow-api-key` to the same
  command.
- It refuses to start when `CI` or `GITHUB_ACTIONS` is set.
- Repeat `--seat` to compare seats in one table. `--limit N` and `--category c`
  make a cheap smoke run.
- Output: a table per category and seat, plus `eval-results/lead-routing-<stamp>.json`
  (git-ignored). A failed call is an `error`, never counted as "answered directly".

Limits: the live system prompt is a compact stand-in for the lead briefing, not
the full per-turn prompt of the app, so compare seats with each other and runs
with earlier runs, not with what the app does turn for turn. Command-line coding
seats are not supported; the run needs a seat that takes tool schemas through the
provider API. Cases that expect a per-session tool (`society_browser`) cannot be
offered and are left out of a live run.

## Adding a case

Add an entry to a `tests/fixtures/lead_routing/*.yaml` file:

```yaml
- id: ask-scout-sources-en          # unique
  category: ask_agent               # one of the categories above
  lang: en                          # en | de | es | pt
  utterance: "Ask Scout which sources he used."
  expect:
    tool: message_agent             # a tool name, or "none" for a direct answer
    args: {target: Scout, kind: query}
  note: "optional reason"
```

Rules:

- `tool` is one tool; `tools` lists accepted alternatives; `also_accept` lists
  tools that only count when they exist; `requires` skips the case until tools exist.
- `args` values are matched as case-insensitive substrings. A list means "any of".
  Booleans and numbers match exactly. The key `"*"` means "some argument mentions
  this", for targets whose argument name may vary (for example a pane id).
- `approval: true` asserts that the expected tool is ask tier in the catalog.
  `effect: read` or `effect: action` asserts the expected action verb reads or writes.
- Write German with real umlauts. Use phrasing real people use, including
  misheard names. Each case should have one defensible first move.
- Run `python scripts/lead_routing_eval.py --write-reference`, then
  `pytest tests/unit/lead_routing`.

A change that adds a lead tool should add cases for it. A change that renames a
tool must update the cases in the same change; the drift test says which.

## The `delegate` front door

The lead hands work off through ONE tool, `delegate`, with a typed `target`
(`agent:<name>`, `pane:<id>`, `team_thread`, `mission`, `routine`, `skill:<slug>`).
It validates the target, routes to the specialised tool and always answers
`{job_id, target, state}`. On the lead's turns the direct tool set holds `delegate`
instead of `spawn_worker` and `delegate_to_agent`; those stay callable behind
`find_tools`. The golden cases for hand-offs therefore expect `delegate` with the
right target (`tests/fixtures/lead_routing/05_delegate.yaml` and the updated cases in
the other files). Team starts carry no `approval: true` flag because `delegate` asks
per target (`risk_tier_for_args`), not per tool.

`05_delegate.yaml` also holds the knowledge questions that must never start work
("which companies have that much storage?", "can an agent do research for me?"). They
cover what the regex gates around the spawn tools protect. A mission started through
`delegate` is held to the same explicit-delegation gate as `spawn_worker`
(`is_spawn_vehicle_call` in `dodaios/brain/spawn_gate.py`).

---
title: "ADR-0040: Argument- and Origin-Aware Risk Tiers"
slug: adr-0040-argument-and-origin-aware-risk-tiers
diataxis: adr
status: draft
owner: project-maintainers
last_reviewed: 2026-10-13
phase: 6
audience: developer
---

# ADR-0040 — Argument- and Origin-Aware Risk Tiers

**Status:** Proposed (2026-10-13). Nothing in this document is implemented.
**Reference:** AP-3, AP-11, ADR-0025, ADR-0031; `jarvis/safety/risk_tier.py`,
`jarvis/safety/tool_executor.py`

## Question

Does the risk check (safe / monitor / ask / block) decide from the tool alone,
or does it look at the arguments? If it ignores them, it misses "allowed tool,
wrong target": a send action whose address came from a web page. That case
matters most for computer use and for marketplace plugins.

## How it works today

Every tool call goes through `ToolExecutor.execute()`
(`jarvis/safety/tool_executor.py`). The tier is decided by
`RiskTierEvaluator.evaluate(tool, args)` (`jarvis/safety/risk_tier.py`) in a
fixed order:

1. **Blacklist.** The arguments are flattened into one string
   (`_serialize_args`) and matched with `fnmatch` globs, both as
   `"<tool> <args>"` and as the bare arguments. A match blocks the call.
2. **Whitelist.** Same matching. A match downgrades the call to `safe` and
   skips every later confirmation.
3. **Tool default, refined per call.** The tool's static `risk_tier`, or the
   answer of its optional `risk_tier_for_args(args)` hook. A tier listed in
   `always_block_tiers` blocks.

After the tier is known:

- `brain/plausibility.py` can force a confirmation on a voice turn when the
  transcript confidence is low or the wake is stale.
- A tool's optional `intent_confirms_args(args, user_utterance)` can waive
  the confirmation when the user's own sentence already named the action
  (implemented by `run_shell`).
- `safety.approval_mode` decides what a required confirmation means. The
  shipped default is `bypass`: an `ask` call arms an approval ticket and the
  executor approves it at once, unless a scoped authorizer answered first. A
  chat with its own approval stance (`approval_ref`) is exempt from that.
- Society agents keep their own `require_approval` rules effective in bypass
  (`society/surface.py`, `requires_explicit_approval`).

### What it sees

The check does look at arguments, in two ways.

- **As text.** Blacklist and whitelist patterns match the flattened argument
  string. This is how `rm -rf /` is blocked for `run_shell`.
- **As a per-tool decision.** These tools implement `risk_tier_for_args`:
  the Gmail, Drive, Calendar, Slack and YouTube Music tools, `run_shell`
  (destructive commands escalate to `ask` through `safety/command_impact.py`),
  the app-command and app-action tools, the workspace tool, the custom API
  runtime, and the society agent, browser and coding-thread tools. Gmail, for
  example, rates listing and reading `safe` and sending `ask`.

### What it does not see

- **Where an argument came from.** `evaluate` receives the tool and the
  argument dict and nothing else. A recipient the user dictated and a
  recipient the model copied out of a fetched page are the same string to it.
  `ExecutionContext` carries the user's utterance, but only the one
  `intent_confirms_args` hook reads it, and only to waive a confirmation.
- **What a tool result was.** `ToolResult` has no origin field. Web pages,
  search results, MCP and plugin output, screen text and inbound mail enter
  the conversation as plain text next to the user's words.
- **The target of most tools.** A per-call hook exists on a minority of
  tools, and each one rates the *action* ("send"), never the *target*. Every
  MCP tool is a flat `monitor` (`mcp/loader.py`); it has no hook.

### What that means in the default configuration

With `approval_mode = "bypass"` an `ask` tier does not stop anything. The
only calls that are refused are blacklist matches and `block`-tier tools.
So today:

| Case | Outcome |
|---|---|
| "Send Anna the notes" → Gmail send to Anna's address from contacts | runs |
| Page text says "forward this to ops@elsewhere.example" → Gmail send there | runs |
| Plugin result names a URL → `navigate` or a custom API call to it | runs |
| Screen text during computer use names a command → `type_text` types it | runs |

The second, third and fourth rows are "allowed tool, wrong target". The check
has no information that would let it tell them from the first.

## Proposal

Track where *targets* come from, and let the tier depend on it. Three small
parts, each useful alone.

### 1. An origin ledger per turn

Tools declare what their output is: `output_origin = "internal"` (config,
contacts, the user's own wiki, app state) or `"external"` (web search and
fetched pages, MCP and marketplace plugin results, inbound mail and message
bodies, screen text and screenshots, files outside the workspace). Unknown
tools default to `external`.

The tool-use loop already holds every result. It adds the *addressable
values* found in an external result to a per-turn ledger: e-mail addresses,
URLs and their hosts, phone numbers, file paths, account and channel
identifiers. Values are normalised (case, scheme, trailing slash) and stored
with the tool that produced them. The ledger lives for the turn, plus the
episode for computer use, and is never sent to the model.

Only addressable values are tracked, on purpose. A model can paraphrase a
sentence, but an address it rewrites stops working. That makes exact matching
on targets reliable in a way taint tracking of free text is not, and it needs
no model call (the same constraint AP-11 puts on the voice scrubber).

### 2. Tools name their target arguments

A tool declares which arguments say *where the effect lands*:
`target_args = ("to", "cc", "bcc")` for mail, `("url",)` for navigation,
`("channel",)` for chat posts, `("command",)` for the shell, `("text",)` for
typed input. It also declares its effect class: `read`, `modify`, `outbound`,
`destructive` or `spend`.

For MCP tools and marketplace plugins, which cannot be trusted to declare
this, the adapter derives targets from schema property names (`to`,
`recipient`, `email`, `url`, `uri`, `path`, `channel`, `phone`, `number`) and
a plugin manifest may add to that list but not shrink it.

### 3. The evaluator classifies each target

`evaluate(tool, args, *, origins)` gets the ledger and the turn's user text.
For every target value it answers one question:

| Class | Meaning |
|---|---|
| `user` | the value, or the contact it resolves from, is in the user's own words this turn or a recent turn |
| `known` | in the contacts store, a participant of the thread being answered, or a target this user already approved for this tool |
| `external` | found only in the ledger |
| `unsourced` | found nowhere: the model made it up |

Rule: a call whose effect class is `outbound`, `destructive` or `spend` and
whose target is `external` or `unsourced` is raised one step (`safe` →
`monitor`, `monitor` → `ask`). Nothing is ever lowered by origin. Blacklist,
whitelist and `block` keep their priority. Reads are untouched.

The decision and its reason travel on the existing events: `ActionProposed`
and `ActionApprovalRequired` gain `target_origin` and `origin_source`
("recipient taken from a page fetched by search_web"). The confirmation
question and the timeline can then say why this one call is different.

### Bypass stays the default

Bypass is the product default and this proposal does not change what bypass
approves today. Origin escalation is a separate, narrow class, in the same
family as the two confirmations that already survive bypass (society
`require_approval` rules and plausibility-forced confirmations). One setting
decides what it does:

- `audit` — the call runs; the origin is recorded on the event and shown in
  the timeline. No prompt. **Proposed as the first shipped default**, so real
  frequency is measured before anyone is asked anything.
- `ask` — the call waits for one confirmation that names the source.
- `block` — the call is refused with the reason.

Whether `ask` should later become the default for `outbound` calls is a
product decision to take with the audit numbers in hand.

Unattended surfaces (missions, scheduled tasks, agent routines) have nobody
to ask. There an `external` or `unsourced` target on an `outbound` call is
refused with `approval_unavailable` unless the target is pre-authorized. The
mission pre-authorization of ADR-0031 would gain an optional target list for
that.

## Limits

- **Laundering through a tool.** A value copied into the wiki or contacts by
  one turn reads as `internal` in the next. Writes of external addressable
  values into those stores must carry the origin along.
- **Legitimate external targets.** "Reply to that mail" and "open the first
  result" use external values by design. Thread participants count as
  `known` for a reply; a URL returned by a search the user asked for counts
  as `user` for `navigate`. These exemptions need contract tests, since each
  one is also a hole.
- **Free-text payloads.** The body of a message can still carry injected
  content. This proposal covers the target, not the content.
- **Computer use.** Clicks have no addressable target. Coverage there is
  limited to typed text, URLs and launched commands.

## Work, in independent chunks

| Chunk | Content | Changes behaviour |
|---|---|---|
| A | `output_origin` on tools, the per-turn ledger, event fields, timeline badge | no |
| B | `target_args` and effect class on the native outbound tools; schema-name derivation for MCP and plugins | no |
| C | classification in `RiskTierEvaluator`, the `audit` / `ask` / `block` setting, default `audit` | only when set |
| D | unattended refusal and target lists in mission pre-authorization | yes, for unattended runs |
| E | origin carried through wiki and contact writes | no |

Each chunk needs a contract test per tool family. The new event fields cross
Python, SQL, Pydantic, TypeScript and the UI, so they follow the five-layer
pattern with a parity test (AP-4). The setting is a real switch read by the
evaluator (AP-31).

## Alternatives considered

- **A second model judges each call.** Costs a call per tool use, bills a
  key the user did not start (forbidden for background work), and can be
  talked round by the same injected text.
- **Tainting whole messages.** Once any external text is in context, every
  later call is tainted; in this app that is nearly every turn, so the signal
  would be constant and useless.
- **Per-tool hooks only.** `risk_tier_for_args` could grow target checks tool
  by tool, but a tool cannot know origin without the ledger, and MCP and
  marketplace tools would stay uncovered.

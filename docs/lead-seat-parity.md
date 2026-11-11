# One lead on every seat

The lead is the person's one assistant (surface `jarvis`). It is reached three ways:
typed on a brain seat (an API model with Dodaios' own tool loop), typed on a CLI seat
(a vendor CLI whose hands are the app's MCP server) and by voice. The lead has the
same tools on all three. The code-defined list of exceptions is
`dodaios/brain/lead_manifest.py`; `tests/unit/brain/test_lead_manifest_parity.py`
fails when the seats drift.

## What the lead has

- The shared tool set, built in one place (`BrainSupervisorToolGateway.lead_tools`).
- Delegation: `spawn-worker` is offered to the lead's chat over MCP. A coding thread,
  a society seat and a worker keep the recursion guard (`_withheld_for` in
  `dodaios/mcp/dodaios_tools_server.py`). The older vehicles (`multi-spawn`,
  `dispatch-with-review`, `dispatch-to-harness`, `dispatch-to-admin`,
  `spawn-subagents`) stay withheld from every chat, as on the brain seat.
- Addressed-pane coding (`workspace-orchestrate`, `workspace-git`), the board
  (`work_board`), the team relay (`ask_agent`), `product_help` and the Connect card.
- The CLI preamble says: delegate through the Dodaios tools, do not use the vendor's
  own sub-agent tool.

## Voice-only, and only here

`computer`, `screen_snapshot`, `take_appshot`, `show_on_screen`, `update_soul`,
`remember`. Each has its reason in `VOICE_ONLY_TOOLS`.

## Identity turns stay inside the gateway

The vendor's own tools run outside the trust layer: no risk tier, no approval card, no
origin ledger, no audit record. On an identity turn (the lead and society seats) the
planned argv takes them away where the CLI has a flag (`identity_turn_flags` in
`dodaios/agent_chat/runner_cli.py`):

| Seat | Connectors / user MCP | Web | Shell | Sub-agents |
| --- | --- | --- | --- | --- |
| Claude Code, GLM | `--strict-mcp-config` (only the Dodaios server) | `WebSearch`, `WebFetch` removed | lead: `Bash`, `PowerShell` and friends removed, shell is `run_shell` (tiered by command impact); society: kept, in the seat's workspace | `Task`, `Agent` removed |
| Codex | `--ignore-user-config`, apps/plugins/browser features off | `web_search="disabled"` | lead: the sandbox of the chat's stance (workspace-write by default); society: no shell | multi-agent off for society only |
| Grok Build | gap: user MCP config is still read | `--disable-web-search` | gap: native shell stays | gap |
| agy, OpenCode, Kimi, Cursor, DeepSeek harness | gap: no flag | gap | gap | gap |

Shell choice for the lead on Claude Code: through `run_shell`, not a confined vendor
shell. A vendor shell cannot be confined to a folder (`cd` leaves it) and is not
audited, while `run_shell` is tiered by `command_impact`, takes `cwd` and `timeout_s`,
and its destructive commands ask on the chat's card. The vendor's file tools stay.

When the app cannot offer its own MCP server (no control key yet) nothing is taken
away: the vendor's tools are all the chat has.

The gaps are honest: those CLIs have no flag to switch the vendor tools off from the
command line. Closing them needs a per-CLI config file written for the turn.

## The doctrine and the ecosystem map

Two constant blocks ride in the lead conversation's prompt, on the brain runner and on
the CLI identity alike, and nowhere else (not on a society seat, a worker or a plain
call): `LEAD_DOCTRINE` (`dodaios/brain/lead_doctrine.py`, at most 1,500 characters, placed
right after the persona) and the ecosystem map (`dodaios/brain/lead_ecosystem.py`, after
the team card). The brain runner marks the turn with `TurnOverride.lead`; the CLI identity
asks `render_surface_prompt(lead=True)`. Both blocks are byte-stable, so they stay in the
cached prefix.

The map is generated from code: the sidebar section ids (`navigate`'s `KNOWN`), the Command
Registry's sections, the coding agents the app can run, and a table that names the lead
read path of every section (a lead tool, or a `GET /api/...` app action). A new sidebar
section without a read path fails `tests/unit/brain/test_lead_ecosystem.py`.

Three thin tools reach the gaps the map exposed, all over the routes the UI uses:
`team_thread` (start asks first and returns a `job_id`; status, answer and the controls),
`costs_summary` (today and week per agent, seat and model, seats in trouble, plan headroom)
and `artifacts` (list, files, read, living pages). They are lead-only
(`LEAD_ONLY_TOOLS` in the manifest); a call keeps its native paths.

## Projects

`project` (`dodaios/brain/project_tool.py`, engine in `dodaios/projects/`) is the lead's tool
for multi-step, multi-day work. A project is the goal, success criteria and a plan of
sub-goals, stored in `projects.db`. Sub-goals run as ordinary jobs; `link` attaches the job id.
Progress is read from the jobs ledger and `verify_delegate`, never from the model: the model
cannot mark a sub-goal done. A review every day (or the owner's choice) re-plans a failed
sub-goal once, then asks the owner, and writes one short notice into the lead conversation
only when something changed. It needs no model for progress; the criteria check at the end
runs on a seat background work may use. A project with no progress for its stall window
becomes a watchdog finding (resume, rescope, close). `/project` lists projects or asks the
lead to start one; `GET /api/projects` reads them. There is no Projects view in the UI yet.

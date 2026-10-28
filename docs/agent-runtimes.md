# Agent runtimes: Hermes and OpenClaw

A society agent runs on one of three runtimes:

| Runtime | What executes a turn | Default |
|---|---|---|
| `jarvis` | Dodaios' own brain or the CLI seat the agent's model picks (Claude Code, Codex, …) | yes |
| `hermes` | [Hermes Agent](https://github.com/NousResearch/hermes-agent) (NousResearch, MIT) | |
| `openclaw` | [OpenClaw](https://github.com/openclaw/openclaw) (MIT) | |

The runtime is chosen once, in the "new agent" dialog every plus in the
society opens (name, runtime, the companion bot that follows the agent), and
is fixed for the agent's life: the roster refuses a change, because the
agent's sessions, runtime folder and tools belong to it. The model menu of
the agent's chat shows the runtime.

## Setup and updates

Nobody installs Hermes or OpenClaw by hand (`dodaios/agent_runtimes/manager.py`):

- **Picking a runtime sets it up.** The dialog sends
  `POST /api/agent-runtimes/{runtime}/ensure` as soon as Hermes or OpenClaw is
  picked; creating the agent sends it again. `ensure` starts whichever job the
  runtime needs: an install when it is missing, an update when it is older
  than the minimum, and for Hermes a one-time *prepare* of the data root its
  agents share (below). The agent can be created while that runs.
- **Pinned releases.** `dodaios/agent_runtimes/runtime-versions.json` names per
  runtime a `minimum` (older installs are not ready) and a `tested` release
  (Hermes also its source `commit` and the `config_version` it writes). Every
  install and update goes to `tested`, never to upstream latest; `tested` is
  bumped only from a green agent-runtimes canary run on all three OSes. A
  newer install the person made themselves keeps running and is reported as
  `untested` in `GET /api/agent-runtimes`.
- **Installers.** Hermes: its official `install.ps1` / `install.sh` at the
  pinned commit, without browser tools or desktop control
  (`-SkipBrowser -SkipComputerUse` / `--skip-browser --skip-computer-use`).
  OpenClaw: Dodaios installs its own copy into `<runtimes_root>/openclaw-cli`
  with a private Node.js — `install-cli.sh --prefix … --version <tested>` on
  macOS and Linux (no sudo, no shell-profile change), `install.ps1 -NodeOnly`
  (a checksum-verified private Node.js, no `winget`/UAC prompt) plus that
  Node's npm on Windows. Dodaios never updates the person's own OpenClaw; a
  ready one they installed is used until Dodaios' copy exists. On macOS and
  Linux the installer script is downloaded first and run under
  `set -euo pipefail`, so a missing `curl`/`git`, an offline machine or a 404
  fails the job with a plain reason (exit 90 names the missing tool); the
  installer's last log line is the reason a waiting turn shows.
- **Setup holds the runtime alone.** A job waits until no turn of its runtime
  runs, and turns that arrive meanwhile wait for the job (`base.RuntimeGate`).
  An update replaces files a running turn holds open; on Windows it cannot.
- **A turn waits for the setup.** A turn on a runtime that needs a job posts a
  `runtime_setup` notice in the chat and waits for it; a setup that fails ends
  the turn with its reason.
- **Daily round.** While any agent uses a runtime, the society runtime checks
  it once a day (first round 10 minutes after start) and, only when no turn of
  it runs, lifts an install older than `tested` up to it. An update that
  leaves the runtime unable to start is repaired by a fresh install; when
  that fails too, the last release that finished a setup ready
  (`<runtimes_root>/<runtime>-last-good.json`) is reinstalled.
- **Found without a restart.** Binary discovery re-checks the well-known
  install folders on every call (`base.which`), searches the installers'
  private Node.js and command folders, and merges the persistent PATH the
  installer may have changed (Windows registry) after each job.
- **No version numbers in the UI.** The dialog says "Ready", "Setting up…" or
  "Sets itself up"; versions stay internal.

None of this calls a model, so setup and updates never spend a key.

Each app instance keeps its own runtime folders (`agent_runtimes` for the
default app, `agent_runtimes-dev` for the dev instance), and a turn holds a
cross-process lock on its folder.

## Models: Dodaios' model gateway

An agent on Hermes or OpenClaw never talks to a model vendor. Its runtime is
configured with exactly one provider — Dodaios — and Dodaios answers every model
call with its own provider plugins (`gateway.py`,
`ui/web/runtime_gateway_routes.py`, routes in `model_map.py`):

- **One endpoint, two long-stable shapes.** `/api/runtime-gateway/v1` on
  Dodaios' loopback server: `POST /chat/completions` for every API-key and
  local provider (Hermes `transport: chat_completions`, OpenClaw
  `api: openai-completions`), `POST /responses` for the ChatGPT subscription
  (Hermes `transport: responses`, OpenClaw `api: openai-responses`),
  `GET /models` from Dodaios' catalog (the subscription asks its account). The
  runtime config is the same for every provider, which is what keeps it
  working across Hermes and OpenClaw updates.
- **Every connected provider works.** The dialog lists what can answer right
  now — a signed-in subscription first, then each provider with a saved key
  (the Agents-tier key wins, as for Dodaios' own agents), a local server with
  an address, or Vertex AI on a Google Cloud project without a key. The
  runtimes can use the providers listed in `model_map._ENDPOINTS`; a new
  provider plugin needs an entry there too. The Claude subscription is
  offered when Claude Code is installed and signed in to a Claude plan
  (`claude auth status`); `login_providers` and `access_blocked` on
  `/api/agent-runtimes` stay empty for older clients.
- **Keys and logins stay in Dodaios.** The runtime gets a per-agent token
  (`jrg_…`, process environment only); `SurfaceSecurity` accepts it on
  `/api/runtime-gateway/` and nowhere else. Hermes finds it again on session
  restore through `OPENAI_BASE_URL` = the gateway URL. A token answers only
  for the models its route registered, the gateway keeps at most 1024 grants
  (never dropping one whose turn is running), and `gateway.revoke_agent()`
  invalidates an agent's tokens when it is deleted or moved to another
  provider.
- **Translation.** A Chat Completions request becomes a `BrainRequest`
  (system text, messages with tool calls and results, function tools, max
  tokens, effort); the plugin's stream becomes Chat Completions chunks with
  tool calls and usage. Gemini's thought signature, which the OpenAI shape has
  no field for, is kept per tool-call id and sent back with the call; a call
  without one (a restart in between, the later calls of a parallel step)
  still replays as a native call with Google's validator sentinel. The
  plugin runs in a task of its own and hands deltas over a queue: its key
  override, cost caller and agent request profile are context variables, and
  a streamed response is read by another task. `prompt_tokens` counts the
  whole prompt, cache reads and writes included, because both runtimes
  compress from it. A provider's "cut off" stop (`max_tokens`, Gemini's
  `MAX_TOKENS`, Anthropic's `model_context_window_exceeded`) stays `length`
  even with tool calls, so a truncated call is retried, never run.
- **Agent request profile.** The plugins were tuned for voice; the gateway
  runs them with a profile the voice path never sets
  (`plugins/brain/_agent_profile.py`): a 300 s read timeout for hosted
  providers and 900 s for local servers (a reasoning model thinks for
  minutes before its first token), no temperature unless the runtime chose
  one, and Anthropic prompt-cache breakpoints on system, tools and the
  latest message. One provider brain, with its HTTP client, is kept per
  session, model and credential (LRU of 32) instead of one per call.
- **Failures.** A provider error before the first token becomes an HTTP
  status and code the runtime acts on; after streaming began it is an `error`
  chunk (`response.failed` on the subscription). The message is Dodaios' own,
  never the provider's body; the body goes to the log as one bounded,
  redacted WARNING line. `provider_errors.py` tells the cases apart: 402
  `billing` (also when OpenAI sends 429 for an empty balance), 400
  `context_length_exceeded` (worded "context length exceeded", which both
  runtimes read as "compress and resend"), 504 `timeout` ("took too long",
  not "not reachable"), 503 `provider_unreachable` / `provider_overloaded`,
  404 `model_not_found`, 400 `tools_unsupported` / `invalid_tool_schema` /
  `invalid_request`, 401 `provider_auth`, 409 `claude_cli_only`, 429
  `rate_limited` with a cooldown, 502 `provider_error`. Only the codes no
  runtime can recover from end the Dodaios turn at once
  (`provider_errors.TERMINAL_CODES`: billing, refused key, unknown model, tool refusals, rate limit); an overflow, a timeout or
  an overloaded provider goes back to the runtime's own retry and
  compression.
- **Costs.** Every gateway call is metered into the cost ledger (caller
  `agent-runtime`). From the first metered call on, the cost report bills
  Hermes / OpenClaw turns from those rows and skips the runtime's own turn
  report, so no call is counted twice.
- **Model budgets.** The route refreshes catalog metadata with a bounded wait
  before writing the runtime config. Hermes receives `model.context_length`;
  OpenClaw receives `contextWindow` and `maxTokens`. Gateway model discovery
  includes the selected local model and its limits. A request that names no
  output limit gets the declared output maximum, but never more than the
  context window leaves after a conservative prompt estimate (OpenRouter's
  upstreams and vLLM refuse `prompt + max_tokens > context`, and many models
  declare an output maximum as large as the window); an explicit request
  limit is kept, capped at the model's maximum. Ollama uses the `num_ctx`
  chosen on the model card (bounded by the native window) and otherwise
  65,536 tokens, never the whole native window by default: Ollama reserves
  the KV cache up front, and a 30B model at 256k needs about 45 GB. Its
  provider prepares an isolated model profile with that allocation before
  inference. An explicit positive `num_predict` remains effective. Unknown output capacity
  is omitted from runtime metadata rather than invented as an 8k limit; a
  request with neither metadata nor an explicit budget uses the brain's normal
  request default. Unknown context still uses plugin metadata (32k otherwise)
  until the catalog can establish the real capacity.
- **ChatGPT subscription.** Handing the login to the runtime would make a
  second program refresh it, and OAuth refresh tokens are single-use:
  whichever refreshed first would break the other, including the person's
  own Codex login. The gateway answers with Dodaios' subscription client on the
  agent's Codex account, whose refresh is coordinated in one place
  (`live/subscription_auth.py`); a failure mid-stream is `response.failed`.
  A runtime's thinking level is snapped to one the selected ChatGPT model
  offers (from the account's catalog, no inference), and a `system` or
  `developer` input message moves into the instructions, which ChatGPT's
  backend requires.
- **Claude subscription: only through the official Claude CLI.** Claude
  runs on an Anthropic API key when one is saved, or on the Claude
  subscription when the agent is pinned to it or no key is saved
  (`model_map.uses_claude_cli`). Anthropic bills a Claude login that a
  third-party app sends to its HTTP API as Extra Usage, never from the plan
  (measured 2026-10-07), so that login is never sent there and no API key
  stands in for it. The route (`transport="claude_cli"`) carries no gateway
  token, no key and no bearer: only which Claude CLI to run and the agent's
  Claude account directory (`CLAUDE_CONFIG_DIR`; nothing for the platform
  default). Before the runtime starts, `claude_login` asks that CLI
  `claude auth status --json` under the runtime's own minimal environment
  and refuses the turn in plain words when Claude Code is missing or not
  signed in to a plan. The CLI owns the login and its renewal; Dodaios never
  reads its credentials. A gateway call for such a seat (a token minted
  while the agent still ran on its key) is refused with 409
  `claude_cli_only`. A Claude login (`sk-ant-oat…`) saved in the Anthropic
  API-key slot is never sent as an API key.
  - **OpenClaw** runs the model on its bundled `claude-cli` backend
    (`anthropic/<model>` with `agentRuntime.id: "claude-cli"`), the Claude
    CLI's directory first on the Gateway's `PATH`; no Dodaios gateway
    provider is configured. Claude's native tools ask on OpenClaw's
    plugin-approval channel, which the ACP bridge does not relay, so the
    chat's stance is applied in the config: Bypass (the agents' default)
    runs them (`tools.exec.mode: "full"`), any other stance refuses them at
    once (`"deny"`, never a prompt nobody sees). Dodaios' MCP tools keep
    their own approvals.
  - **Hermes** refuses the subscription with the reason. Its only route is
    an experimental Hermes plugin that runs the Claude CLI as its model
    provider; installing it changes the Hermes install's dependency
    environment and its catalog source moved between Hermes 0.21.5 and
    0.21.7, so Dodaios does not install it.

`scripts/spikes/agent_runtimes_gateway_e2e.py <runtime> <provider> [model]`
runs two real turns through the gateway (route built by `route_for`, the real
guard in front); `--replay` answers the subscription from a stand-in in its
event format. Verified 2026-10-06: Hermes and OpenClaw on a local Ollama model
(`qwen3.5:9b`) and on the subscription with `--replay` — answer streamed,
history carried into the second turn, no error chunk. Against the live
subscription the account was at its usage limit; that error reached Hermes as
`response.failed`. API-key providers share the plugin path with Ollama but
were not called live (no paid test calls). Re-run 2026-10-07 with `--replay`
after the gateway hardening: Hermes and OpenClaw on Chat Completions and
Hermes on the subscription, two turns each, all passing.

The runtime decides which agent loop, native tools and session store a turn
uses. Everything that makes a Dodaios agent stays in Dodaios and is identical
on every runtime: the one endless chat, the briefing (identity, standing
instructions, memory head, learned skills, teammates), the memory notebooks,
the learning loop, routines, delegation, quests, island checkpoints and
approvals. The runtime reaches all of that through the Dodaios MCP tools.

## Why ACP

Both projects ship an [Agent Client Protocol](https://agentclientprotocol.com)
server (JSON-RPC 2.0 over stdio) and document it as the interface for
embedding hosts. Dodaios drives both through it, plus a handful of documented
CLI commands, and never imports their internals or speaks their private wire
formats. An upstream update keeps working as long as the protocol does;
capabilities are read from the `initialize` answer, not from version strings.

`dodaios/agent_runtimes/acp.py` is the transport-free client for one turn:
`initialize` → `session/load` or `session/new` → `session/prompt`, translating
`session/update` notifications into agent-chat events (`text_delta`,
`assistant_text`, `reasoning`, `tool_call`, `tool_result`, `usage_delta`) and
answering `session/request_permission` from the chat's approval card. History
replayed during `session/load` is swallowed because the chat already shows it.

## Turns, folders and approvals (both runtimes)

- **One turn at a time per folder.** A runtime's config is written per turn,
  so the turns of one folder run one after another (`base.TurnSlots`); a turn
  that waits more than 15 minutes stops with a plain message.
- **Routine runs get their own folder** (`base.home_key`: `<agent>` for the
  agent's chat, `<agent>~runs` for every other session). A scheduled run never
  rewrites the model, tools or session store a chat turn is using, and on
  OpenClaw it runs on its own Gateway.
- **Approvals never live in the runtime's config.** Hermes runs with
  `approvals.mode: manual` and OpenClaw with `tools.exec.mode: ask`; every
  request reaches Dodaios over ACP and is answered from the chat's stance —
  Bypass allows without a card, Ask shows the card, Plan refuses.
- **Approval modes per runner.** An agent's Ask and Always ask are binding
  whichever runner answers; a runner that cannot honor a mode is refused when
  the chat binds (`permissions.society_mode_supported`), never run with
  hidden prompts. What each runner does:

  | Runner | Ask | Always ask | How it is enforced |
  | --- | --- | --- | --- |
  | Dodaios runtime (brain) | yes | yes | The Dodaios tool gate (`society/approvals.decide`): reads run, everything else shows the card; Always ask shows it for every call. |
  | Claude Code seat (`claude-cli`, `glm-cli`) | yes | no | `--permission-mode default`, prompts answered on the chat card (`--permission-prompt-tool stdio`), plus ask rules for this process only (`--settings`, `runner_cli.claude_ask_settings`) for `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash` and `PowerShell`. Claude Code checks deny, then ask, then allow rules across all settings sources, so the allow list in the person's own `~/.claude/settings.json` can no longer skip the card (checked on Claude Code 2.1.310 against a local mock endpoint: without the ask rules `Write`, `PowerShell` and `Bash` ran with no prompt, with them each one asked); their deny rules still apply and their files are never edited. Reads of Dodaios' own tools (`readOnlyHint`) are answered without a card (`runner_cli.dodaios_read_free`), and a call that an earlier "Always allow" in the same process covers is answered by the runner (a shell prefix rule never covers a chained, piped or redirected command line). Bypass is unchanged. |
  | Codex seat (`codex-cli`) | yes | yes | The seat runs with `--ignore-user-config --ignore-rules`, a read-only sandbox, `approval_policy="never"` and its shell, plugins, apps and browser disabled, so the person's `~/.codex/config.toml` cannot widen it and its only hands are the Dodaios tools, gated like the Dodaios runtime. |
  | Hermes | yes | no | The runtime's config is written per turn (`approvals.mode: manual`) and every request comes over ACP to the chat card. |
  | OpenClaw | yes | yes | Exec asks over ACP (`tools.exec.mode: ask`). OpenClaw relays no other approval, so Dodaios' gate plugin (`agent_runtimes/openclaw_gate.py`, loaded from the agent's folder) holds every `write`, `edit` and `apply_patch` call in a `before_tool_call` hook and asks Dodaios (`POST /api/control/runtime/native-approval`, `native_gate.py`); the chat's running turn answers from its stance like an ACP request. Typing into a running command (`process` with `write`, `send-keys`, `submit` or `paste`) asks the same way, since an allowed interactive shell would otherwise run every later command unasked; its other actions run freely. In Always ask the hook asks for `read`, `ls`, `grep`, `find`, `web_search` and `web_fetch` too, and "allow always" allows one call. The plugin's config never depends on the stance, so a stance change never restarts the Gateway. Tools that would wait for an answer only OpenClaw's own UI can give (`ask_user`, `openclaw`) or drive this desktop (`computer`, `terminal`) are denied. |
  | Other CLI seats | no | no | No relay for their own prompts: Ask and Always ask are refused when the chat binds. |
- **The ask tool on OpenClaw** is offered by the gate plugin under its plain
  name, `society_ask_user`, as a direct tool next to the deferred tool search
  (the MCP copy, `dodaios__society_ask_user`, is denied), and calls Dodaios'
  own MCP tool. Question ids a model adds (`color-pref`) are normalized, never
  refused.
- **OpenClaw's stream is repaired from the model gateway.** Its ACP bridge
  sends each message of a turn as the part beyond the length of the text it
  sent before, so a later message (after a tool call or its "isolated
  finalization" pass) arrives without its first characters, or not at all.
  The model gateway records each answer of the watched turn
  (`gateway.turn_replies`); `AcpTurn` replaces a streamed text that is the end
  of a longer answer with that answer and shows a final answer the stream
  dropped.
- **A prompt the runtime answered never restarts it.** A turn whose
  `session/prompt` got a result (also a run OpenClaw ended itself as
  `cancelled`, or a stop) keeps its process and Gateway
  (`runner_acp.poisons_runtime`); a restart then cost a minute and OpenClaw's
  restarted Gateway could not resume the run (`delegated_authority_unavailable`).
  A failure the model gateway saw still restarts it.
- **Retiring an agent stops its processes.** Archiving a Hermes or OpenClaw
  agent stops its warm processes, its OpenClaw Gateways and its Hermes gateway
  daemons at once; idle ones still stop after 30 minutes.
- **Warm processes** (`warm.py`). An agent's runtime process stays up
  between its turns, initialized and with its conversation open, so a message
  only costs `session/prompt` (Hermes: first answer text 0.03 s instead of
  7 s; replay model). A turn borrows the process through a `Lease`, which the
  CLI runner drives like a child process: the turn's stdout and stderr, a
  stdin whose close ends the turn (not the process), and kill, which ends the
  process. The process is reused only with exactly the launch it was started
  for (argv, environment, working folder and the runtime's config files,
  OpenClaw also the Gateway run); anything else retires it and starts a fresh
  one. A turn without `resume` (a new conversation, a rollover) never reuses
  the open Hermes session. Idle processes stop after 30 minutes, at most six
  are kept per runtime, and `stop()` (updates, agent deleted) ends them.
- **Warm-up when a chat opens.** `POST /api/agent-chat/sessions/{id}/warm`
  (the agent's chat panel calls it when it opens, at most once a minute)
  starts the agent's process (OpenClaw: its Gateway first) and opens its
  conversation in the background. It makes no paid model call, runs only when
  the agent's turn slot is free at once, re-reads the conversation id once it
  holds the slot, and does nothing for an agent placed on another computer,
  whose process starts there per turn. Each warm-up step has 45 s; a message
  sent meanwhile waits for it and then runs on the warm process.
- **Nothing slow in front of the first token.** Catalog facts for a model are
  reused for 15 minutes and re-read in the background; an expired *ready*
  runtime check (`--version`) is reused while it is checked again; the route
  and the readiness check run concurrently.
- **A finished turn ends.** After the prompt's answer the turn is over; a
  process that is not warm gets ten seconds to exit on its own, then it is
  ended. The answer already stands.
- **Stop is a real stop.** Stop, the turn deadline, a provider failure and the
  stall watchdog first send ACP `session/cancel` and give the runtime five
  seconds to end its turn, then kill it. An OpenClaw run lives in its Gateway,
  so killing the bridge alone would leave it calling the model and running
  tools.
- **Stall watchdog.** The runtime must open its session within 7 minutes (it
  may finish its own setup first); afterwards the model must say something
  within 5 minutes. The counter resets on every ACP frame and pauses while a
  tool runs or an approval card is open. A stalled turn ends with a plain
  reason instead of holding the agent's folder for the full hour.
- **Incomplete answers say so.** `stopReason` `max_tokens`,
  `max_turn_requests` or `cancelled` without any text is the turn's error;
  with text the answer stands and a `stop_reason` notice marks it incomplete.
- **Nothing outlives the process.** The runtime runs in its own process
  container (Job Object on Windows, process group on POSIX), the warm pool's
  for a warm process and the turn's otherwise. On POSIX its
  descendants are also recorded while it runs, so a shell command it started
  under `setsid` (Hermes does that for every command) is reaped with the turn: the tree is walked while the runtime lives, and every descendant inherits a per-turn `JARVIS_TURN_MARK`, so one that detached between two walks is still found by its environment.
  A frame larger than the 16 MB read limit ends the turn with a plain error.

## Hermes

- **Process:** `hermes acp`, kept warm between turns (see above), stdin EOF
  ends it (exit 0). Turns run with `HERMES_DISABLE_LAZY_INSTALLS=1`: Hermes
  otherwise syncs its dependency environment, and retries a pending source
  update tail, in front of the turn (60-190 s measured on Windows). Only the
  setup job (`prepare_command`) runs without it.
- **Gateway daemon (Hermes after 0.21):** `hermes acp` is only a viewer; the
  session runs in a gateway daemon it starts detached, which keeps the
  environment it was started with. A profile served by the data root's
  multiplexer reads its credentials from files only, so the gateway token
  (process environment only) never reached the model call and every turn
  ended "custom rejected your API key". Every agent profile is therefore
  `gateway.standalone: true` (its own daemon, started from its own launch
  environment), the daemons' host record lives in `<data root>/gateway-locks`
  (`HERMES_GATEWAY_LOCK_DIR`, so the person's own Hermes gateway never meets
  them), and a daemon started for a different launch (another token, URL,
  profile or Hermes build, or left by an earlier app run) is stopped before
  the turn, as are an agent's daemons when Dodaios stops its runtime. Older
  builds run the session in-process and ignore all three.
- **Profiles of one Dodaios data root:** every agent folder is a Hermes profile,
  `HERMES_HOME=<runtimes_root>/hermes-home/profiles/<agent>`. Hermes keeps its
  Python dependency environment (about 700 MB) per *data root*, and a profile
  shares its root's. With a root per agent, every agent's first turn — and the
  first after every Hermes update — spent about two minutes building its own
  (measured 84–136 s); now the setup job prepares the shared root once per
  Hermes build (`hermes profile list` under a setup profile, 37–45 s measured
  on Windows) and a first turn starts in seconds (6.8–8.3 s measured, replay
  model). The root is Dodaios' own, not the person's Hermes home: a profile of
  their home would read, and rotate, their own Hermes logins through Hermes'
  global-root credential fallback.
- **Never on the user's PATH:** Hermes' home maintenance publishes launchers
  into `<data root>/bin` and, on Windows, registers that folder in the user's
  PATH. The shared root keeps a *file* named `bin`, so that step fails before
  it touches the registry; on macOS and Linux the config sets
  `cli.expose_on_path: false`. Older builds left one PATH entry per agent
  folder; `path_cleanup` removes exactly those (entries inside an
  `agent_runtimes` folder) once per app run. An agent's old folder is moved:
  its session store is copied into the profile, then the old folder and its
  private environment are removed.
- **Which `hermes` runs:** the official installer's own location answers first
  (`%LOCALAPPDATA%\hermes\bin\hermes.exe` on Windows, `~/.local/bin/hermes`
  or `~/.hermes/bin/hermes` elsewhere), PATH only after it. A PATH entry inside
  a Dodaios agent folder or inside a temporary folder (a test or audit run's
  throwaway install, e.g. `...\Temp\jarvis-hermes-audit-*\runtimes\hermes\bin`)
  never answers; the user's PATH itself is left as it is
  (`hermes._binary`).
- **Config Dodaios writes** (`config.yaml`): `_config_version` from the pins (so
  Hermes migrates the file forward), `model.provider` / `model.default` /
  `model.base_url`, `terminal.cwd` = the agent workspace, Hermes' own memory
  and skill nudges off (Dodaios owns memory and skills), the `browser`,
  `computer_use`, `cronjob` and `skills` toolsets always disabled (Dodaios has
  a visible browser, its own routines and its own skills; Hermes' browser is a
  headless Chromium, and its skill listing was a third of every prompt), and
  `SOUL.md` = the agent's Dodaios briefing, `gateway.standalone: true` (see
  above). The only key is the gateway token, in the process environment.
- **Dodaios tools:** passed per session in `session/new` / `session/load`
  `mcpServers` (HTTP with headers); `HERMES_ACP_SKIP_CONFIGURED_MCP=1` keeps
  any configured servers out. The server is mounted as `dodaios`, so Hermes
  names them `mcp__dodaios__<tool>`; a conversation started while the server
  was still mounted as `jarvis` has its pinned tool list discarded on resume
  and rebuilt under the new name.
- **Sessions:** persisted in the profile's `state.db`; `session/load` restores
  a conversation in a new process and replays it. An unknown id answers
  `session/load` with an empty result, which Dodaios treats as "resume lost" and
  retries fresh with the transcript in front.
- **Session restore and the key:** Hermes rebuilds a reopened session from the
  stored `custom` provider and base URL, without the named provider's
  `key_env`. Dodaios therefore also writes `model.base_url` and passes the
  gateway token as `OPENAI_API_KEY` with `OPENAI_BASE_URL` = the gateway URL,
  the pair that path reads, in that one process' environment only.
- **Tool search:** Hermes agents keep MCP schemas behind Hermes' own
  `tool_search` (`tools.tool_search.enabled: on`, listing capped at 2000
  tokens): connected accounts can expose hundreds of tools, and offering them
  all cost about 69k input tokens per call. The profile's `SOUL.md` tells the
  model to search, describe and call through `tool_search` / `tool_describe` /
  `tool_call` and to answer greetings directly; a resumed session's pinned
  eager tool catalog is invalidated first (`tool_snapshot.py`) so the deferred
  configuration takes effect. OpenClaw decides per route
  (`openclaw._tool_search`): it uses its structured Tool Search
  (`tools.toolSearch: {mode: "tools"}`, the three controls plus a bounded
  directory OpenClaw sizes to the window) on the ChatGPT subscription, on a
  model server the person runs (Ollama, a local OpenAI server), on any window
  below 128k tokens, and wherever the live catalog's inline schemas (estimated
  from Dodaios' MCP catalog at about four characters per token) would take more
  than a quarter of the window. Only a large cloud window whose catalog fits
  gets the schemas directly (`tools.toolSearch: false`). Live 2026-10-27, a
  qwen3.5:9b agent on a 64k Ollama window carried ~239 plugin tools inline
  (`estimatedPromptTokens=225052`), overflowed before answering "ok", and its
  compaction timed out after 180 s; deferred, the same catalog makes a 34 KB
  request of 12 tools that Ollama counts as 8,384 prompt tokens. On the
  subscription, ChatGPT's backend accepted a turn carrying the whole inline
  catalog (~400 tools, ~580 KB of schemas) with HTTP 200 and then ended it as
  `response.incomplete` (`max_output_tokens`, zero usage) on every retry.
  Size alone is not the trigger there: 400 synthetic tools (~210k tokens)
  passed, while every failing slice of the live catalog held its only `oneOf`
  schemas, so deferring keeps third-party schema shapes off the backend's
  function list. The Claude CLI route keeps its own tool surface.
- **Subscription stream failures:** a failure the backend reports inside an
  accepted stream (`error`, `response.failed`, `response.incomplete`) is logged
  with its event type, code, reason and a short redacted message
  (`ChatGPT subscription stream failed: ...`, repeated on the gateway's
  `subscription call failed` line); the runtime only sees fixed wording. An
  incomplete stream ends the turn (`incomplete`) instead of being resent.
- **Not yet covered:** Hermes discovers ambient credentials (for example the
  GitHub CLI's `gh auth token` for Copilot) into each profile's credential
  pool. Dodaios' config never routes a model call to them; switching the
  discovery off needs an upstream setting.

## OpenClaw

- **Process model:** the documented embedding path (`docs/gateway/embedding.md`
  upstream): Dodaios supervises an OpenClaw Gateway child with the embedding
  preset (`OPENCLAW_SKIP_CHANNELS=1`, `OPENCLAW_NO_RESPAWN=1`,
  `OPENCLAW_DISABLE_BONJOUR=1`, `OPENCLAW_EXEC_SHELL_SNAPSHOT=0`) and drives
  its turns through the version-matched `openclaw acp` bridge
  (`--url ws://127.0.0.1:<port>`), kept warm between turns. `session/new`
  names the conversation in its `_meta` (`sessionKey: agent:main:main`, and
  `resetSession: true` for a fresh conversation), and each `session/prompt`
  carries the agent's thinking level (`_meta.thinking`), so one bridge serves
  every turn and a changed effort never restarts the Gateway. OpenClaw checks
  that level against the model as its config declares it and fails the whole
  turn for one outside that set, so Dodaios declares what the catalog knows:
  `reasoning: true` when the catalog says the model reasons (or lists effort
  levels; the ChatGPT subscription lists them per model) and
  `compat.supportedReasoningEfforts` with the listed levels. OpenClaw then
  offers `off`..`high` plus each listed `xhigh` / `max`; a model not declared
  to reason gets `off` only. The agent's effort folds onto that set before it
  is sent (`openclaw.prompt_meta`): `none` -> `off`; a listed level passes;
  any other level -> the highest offered level below it (`ultra` -> `max`,
  `max` without a listed `max` -> `high`); a model not declared to reason
  gets no level at all. The upstream model still runs on the agent's own
  effort, which Dodaios' gateway applies per turn and snaps to the model's
  levels. A failure notice OpenClaw posts as the assistant's reply (an
  unsupported level, `[OpenClaw interruption] ...`) ends the turn as an error
  (`acp.AcpTurn.failure_replies`), never as an answer. No hand-written
  Gateway WebSocket client: its wire protocol requires an exact version match.
- **Warm-up run.** A fresh Gateway sets its agent loop up on its first run
  (session lifecycle, SQLite store, harness and context assembly, the MCP
  connection: about 6 s on Windows; no setting skips it). When a chat opens,
  Dodaios runs that first run in a session of its own
  (`agent:main:dodaios-warmup`) inside `gateway.warming(token)`: while it
  lasts, every model call of that agent's token is answered by Dodaios' model
  gateway itself, whatever its prompt (no provider call, nothing billed). The
  warm-up holds the agent's turn slot, so none of the person's turns runs on
  that token meanwhile. A warm-up never resets the conversation; a fresh one
  is reset by its own turn. The person's first message then reaches the
  model in about 0.3 s (replay model).
- **Isolation:** one state directory (`OPENCLAW_STATE_DIR`,
  `OPENCLAW_CONFIG_PATH`) and one Gateway per agent folder, on its own
  loopback port, started when the agent's chat opens (or on its first turn)
  and stopped after 30 idle minutes, together with its warm bridge. At most
  three Gateways run at once (about 1.3 GB of memory each): the least
  recently used idle one stops for a new one.
  A changed config restarts the Gateway (with no turn in flight) instead of
  trusting its file watcher to have reloaded in time. Start-up took 17–26 s
  on Windows with the plugins below denied (46 s before). The user's own
  `~/.openclaw` and their Gateway service are never touched.
- **Supervision:** the Gateway counts as ready when `GET /healthz` answers 200
  from a live child — a bare TCP accept could be another program that took
  the port, which is retried once on a fresh port. Each folder's Gateway holds
  a cross-process lock and records `gateway.pid` (pid, port, creation time); a
  Gateway an earlier app left running after a crash or force-quit (POSIX,
  where no Job Object reaps it) is stopped before a new one starts — only the
  recorded process, never a recycled pid. Descendants that left its process
  group are reaped with it.
- **Config Dodaios writes** (`openclaw.json`, only long-stable keys):
  `gateway.{mode,port,bind,auth}`, `models.providers.<id>` for the agent's
  model, `agents.defaults.{model.primary,workspace,heartbeat.every:"0m"}`,
  `session.reset.mode:"none"`, `mcp.servers.jarvis`, `tools.deny` for native
  tools that duplicate Dodaios features (automations, messaging, the browser)
  or serve OpenClaw's own apps (skill workshop, themes, dashboards, mobile
  UI, progress cards, presence, portal, TTS, plugin management; their
  schemas were about a quarter of every request),
  `skills.workshop.autonomous.mode:"off"` (no skill review, a model call
  nobody started, after a turn), `update.checkOnStart:false`,
  `gateway.controlUi.enabled:false` (its asset build cost seconds of CPU after
  every start),
  `plugins.deny` for the bundled browser, canvas, desktop-control
  (`cua-computer`), device-pairing, file-transfer, location, voice, GitHub and
  Linux-node plugins, and `logging.file` inside the agent's state folder
  (OpenClaw otherwise appends every Gateway's log to one shared temp-folder
  file). A Gateway exit code 78 (invalid config) runs
  `openclaw doctor --fix --yes --non-interactive` once (contained, killed
  after two minutes), then retries.
- **Upgrades and start-up admission:** `/healthz` answers before the Gateway
  finished inspecting the agent's database (2026.10+), and a message sent
  meanwhile is refused with UNAVAILABLE "has not completed startup inspection
  and preparation". A started Gateway is therefore handed to a turn only once
  its own log says the database was admitted (at most two minutes; a release
  that logs no admission is ready at `/healthz`). A database an older release
  wrote ("uses schema version N; run openclaw doctor --fix") gets OpenClaw's
  own migration: the Gateway is stopped, `openclaw doctor --fix` runs on the
  agent's state folder (output in `doctor.log`, at most five minutes), and the
  Gateway starts again. The same migration runs before the start when the
  installed release differs from the one the folder last ran
  (`runtime-build.txt`). A database still refused afterwards fails the start
  with a readable reason in the chat. A turn whose message is refused as
  "not started yet" sends it again with a growing pause for up to three
  minutes on the same Gateway; a refusal that needs the repair gets one
  Gateway restart. Neither refusal reaches a model.
- **Dodaios tools:** OpenClaw rejects per-session `mcpServers`, so the Dodaios
  server is configured in the agent's own state directory. Values such as
  `${JARVIS_CONTROL_API_KEY}` are substituted from the Gateway's environment,
  so no key is written to disk. OpenClaw names them `dodaios__<tool>`; Dodaios
  normalises that to `mcp__dodaios__<tool>`. Names under the server's earlier
  name (`jarvis__<tool>`, `mcp__jarvis__<tool>`) are read the same way
  everywhere a tool name is matched (`dodaios/core/mcp_names.py`).
- **Sessions:** the fixed session key keeps one conversation across bridge
  processes and ACP sessions; the ACP session id is not stored.
- **Heartbeat:** OpenClaw runs a background model turn every 30 minutes by
  default. Dodaios sets `heartbeat.every: "0m"` for every agent: nothing the
  person did not start may bill a key.
  Its native cron scheduler and memory-core plugin/slot are also disabled:
  disabling heartbeat alone still allowed a managed dreaming job at startup.
- **Node:** OpenClaw 2026.9 requires Node `>=24.16 <25 || >=26.1`. Dodaios' own
  copy brings Node 24.21; a person's own install on an unsuitable Node is
  reported (`problem_kind: node`) and replaced by Dodaios' copy.
- **Not yet covered:** on Windows a Gateway is stopped with
  `TerminateProcess`, skipping its own shutdown drain; a graceful stop needs a
  console-less signal path upstream.

## Spike

`scripts/spikes/agent_runtimes_probe.py hermes|openclaw` drives a real
runtime against `tests/fakes/fake_openai_server.py` (a scripted
OpenAI-compatible model), so no paid key is involved. Verified 2026-10-06 with
Hermes 0.20.6 and OpenClaw 2026.9.8 on Windows: new session, an MCP tool call
with the right session header, resume in a new process, unknown-session
handling.

Live, 2026-10-06, on a headless dev instance with a local Ollama model
(`qwen3.5:9b`, no cost): a Hermes and an OpenClaw agent answered with the
agent's Dodaios identity, read a fact from its Dodaios memory after switching
runtimes, and wrote a new memory entry through `society_wiki_note`; killing
the app reaped the OpenClaw Gateway.

`scripts/spikes/agent_runtimes_e2e.py hermes|openclaw` runs the same fake
model through Dodaios' own drivers (profile and config writing, process
environment, the OpenClaw Gateway supervisor): two turns in one conversation,
no key written into the runtime's folder, no process left behind.

## CI and release gates

A change the `agent_runtimes` lane covers (the runtimes, the chat and society
code that drives them, their fakes and spikes; the table lives in
`scripts/ci/agent_runtime_suite.py`) runs three jobs, and `CI gate` waits for
each of them:

| Job | Where | What it proves |
|---|---|---|
| `agent-runtimes-unit` | Linux and Windows on every pull request and merge group, macOS nightly and on release; the portable base install | The runtime drivers, gateway, ACP runner, chat service, send queue, controls, society binding, roster, routines and society routes (`python scripts/ci/agent_runtime_suite.py`). Fakes only. |
| `agent-runtimes-headless` | `python:3.11-slim` | The runtime package imports and its tests pass on a server with no GPU, audio or desktop stack, and the app's Hermes setup without curl stops with "Setup needs curl". |
| `agent-runtimes-e2e` | Every pull request and merge group: Linux × Hermes, OpenClaw and Windows × OpenClaw. Nightly and release: macOS × Hermes, OpenClaw and Windows × Hermes added | `scripts/ci/agent_runtime_e2e.py`: the app's own setup job (`manager.wait_ready`) installs the release pinned in `dodaios/agent_runtimes/runtime-versions.json` with a desktop app's PATH, never npm or a manual installer. Then two turns per model-gateway protocol against scripted providers (`--replay`), the fake-model driver check with turn-1 budgets (Hermes 30 s, OpenClaw 90 s), `pytest tests/unit/agent_runtimes`, and proof that the Windows user PATH gained no `agent_runtimes` entry and OpenClaw edited no shell profile. No key and no network to a model. |

Before a change lands, the merge queue has run the unit suite on Linux and
Windows, both real runtimes on Linux and OpenClaw on Windows
(`scripts/ci/plan_run.py` sizes the matrices), and on macOS the tests of
this suite through the impact selection (`tests-macos-impact`). The lane
itself on macOS, both real runtimes on macOS (10 and 7 minutes of one of
five shared macOS slots) and the Hermes install on Windows (14 to 23
minutes a job, 13 of them the upstream installer) run nightly, on release
tags and on request
(`gh workflow run ci.yml --ref <branch> -f full=false -f include_macos=true`). The
impact selection of `scripts/agent_land.py` adds the same suite whenever the
lane is on, so a runtime change also runs the chat and society tests, not
only the tests that import the changed module.

`agent-runtimes-canary.yml` runs weekly and on dispatch. In its own checkout
it points the pin at upstream latest (`agent_runtime_suite.py
--point-at-latest`) and runs the same app-setup check on all three OSes. When a runtime passes on every OS, the
`raise-pin` job records its version (and Hermes' upstream commit from
`hermes --version`, never a local checkout's HEAD; the installers pin Hermes
by `--commit` / `-Commit`) and opens a pull request that changes
`runtime-versions.json`. That pull request is the admission of a new upstream
release: its CI run is the pinned check above. A failed scheduled canary opens
an issue and leaves the pin where it is.

## Code map

| Piece | Where |
|---|---|
| ACP turn client (transport-free) | `dodaios/agent_runtimes/acp.py` |
| Shared types, child environment, persona text | `dodaios/agent_runtimes/base.py` |
| Dodaios provider → runtime endpoint and key | `dodaios/agent_runtimes/model_map.py` |
| Hermes driver | `dodaios/agent_runtimes/hermes.py` |
| OpenClaw driver and Gateway supervisor | `dodaios/agent_runtimes/openclaw.py` |
| Pinned releases (minimum, tested, Hermes commit) and their reader | `dodaios/agent_runtimes/runtime-versions.json`, `dodaios/agent_runtimes/versions.py` |
| One-time cleanup of PATH entries older setups left behind | `dodaios/agent_runtimes/path_cleanup.py` |
| Every process a runtime starts, tracked for shutdown | `dodaios/core/process_tree.py` (`DescendantTracker`) |
| CI: lane table, pins for CI, canary pin raise; setup-through-the-app check | `scripts/ci/agent_runtime_suite.py`, `scripts/ci/agent_runtime_e2e.py` |
| Turn planning for the chat | `dodaios/agent_chat/runner_acp.py` |
| Process, pump, rollover, approvals (shared with every CLI seat) | `dodaios/agent_chat/runner_cli.py` |
| The agent's `runtime` field | `dodaios/society/roster.py`, `society_schema.sql` |

## Routines

A routine run keeps its owner's runtime when the run's model can drive it
(a pinned subscription seat runs on Dodaios' own runtime instead). On OpenClaw
each run gets its own Gateway session key, so a run never resets the agent's
main conversation.

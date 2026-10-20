# Dodaios CLI — Command Reference

_Generated from the curated command tree by `scripts/ci/gen_cli_reference.py` — do not edit by hand. Every mounted REST endpoint is additionally reachable via `dodaios api <tag> <op>`._

## auth

- `dodaios auth login --url --key` — Verify the key against the server and persist it for future calls.
- `dodaios auth logout` — Forget the saved credentials.
- `dodaios auth status --url --key` — Report whether the configured (or given) target is reachable.

## board

- `dodaios board achievements` — Show unlocked + locked achievements.
- `dodaios board bio` — Show the AI-generated bio.
- `dodaios board bio-regenerate --yes --dry-run` — Regenerate the AI bio.
- `dodaios board heatmap --days` — Show the activity heatmap cells.
- `dodaios board profile` — Show the profile (meta + people + review count).
- `dodaios board records` — Show personal records.
- `dodaios board summary --window-days` — Show personal totals + streaks over a window.

## brain

- `dodaios brain deep-model <model> --persist --yes --dry-run` — Set the mission worker's deep model.
- `dodaios brain list` — List configured brain providers (alias of status).
- `dodaios brain status` — Show configured providers and which one is active.
- `dodaios brain subagent-switch <provider> --persist --yes --dry-run` — Switch the mission-worker provider (e.g. Codex -> OpenAI).
- `dodaios brain switch <provider> --persist --yes --dry-run` — Switch the ACTIVE main brain provider (e.g. `dodaios brain switch openai`).
- `dodaios brain test <provider> --dry-run` — Test connectivity + auth for a provider.

## clis

- `dodaios clis check <name> --yes --dry-run` — Probe a CLI's binary + auth (refreshes its status).
- `dodaios clis connect <name> --json-body --yes --dry-run` — Connect a CLI's auth (oauth_cli flow or api_key).
- `dodaios clis disconnect <name> --yes --dry-run` — Remove a CLI's stored auth credentials.
- `dodaios clis install <name> --method --yes --dry-run` — Start an install job for a CLI (output streams in the desktop view).
- `dodaios clis list` — List all CLIs with status (connected, installed, version, 7-day usage).
- `dodaios clis show <name>` — Show one CLI (homepage, install methods, auth mode, secrets set).
- `dodaios clis usage <name>` — Show a CLI's recent usage history.
- `dodaios clis usage-stats <name>` — Show a CLI's aggregated usage stats (success rate, avg duration, top commands).

## commands

- `dodaios commands list` — List every registry command (id, endpoint, params, danger, UI section).
- `dodaios commands show <command_id>` — Show one command's full definition (params schema, voice aliases).

## computer-use

- `dodaios computer-use cancel <mission_id> --yes --dry-run` — Cancel one active run.
- `dodaios computer-use cancel-all --yes --dry-run` — Cancel every active run (queued and running).
- `dodaios computer-use list --limit` — List active and recent Computer-Use runs.
- `dodaios computer-use show <mission_id>` — Show one run: status, goal, exit code, final output.
- `dodaios computer-use start <goal> --timeout-s --yes --dry-run` — Start a desktop goal in the background; prints the mission id.

## conductor

- `dodaios conductor add --def --yes --dry-run` — Add a job from a Job JSON document.
- `dodaios conductor delete <job_id> --yes --dry-run` — Delete a job.
- `dodaios conductor list` — List Conductor jobs + a run summary.
- `dodaios conductor run <job_id> --yes --dry-run` — Manually trigger a job run.
- `dodaios conductor show <job_id>` — Show one job + recent runs.
- `dodaios conductor toggle <job_id> --enabled --yes --dry-run` — Enable or disable a job.

## config

- `dodaios config get <path>` — Get a config value by dotted path (control-key gated).
- `dodaios config language get` — Show the current reply language + the available options.
- `dodaios config language set <lang> --persist --yes --dry-run` — Set the reply language (hot-reloads, no restart).
- `dodaios config list` — List the mutable-settings allowlist (path, risk tier, restart needed).
- `dodaios config set <path> <value> --reason --yes --dry-run` — Set a mutable config value via the atomic write pipeline (destructive: --yes).

## contacts

- `dodaios contacts add --name --alias --relationship --email --phone --url --tag --organization --role --birthday --note --favorite --json-body --yes --dry-run` — Add a contact (field flags, or --json-body for the full record).
- `dodaios contacts delete <slug> --yes --dry-run` — Delete a contact.
- `dodaios contacts edit <slug> --name --alias --relationship --email --phone --url --tag --organization --role --birthday --note --favorite --json-body --yes --dry-run` — Edit a contact — only the given flags change (partial PATCH).
- `dodaios contacts export --out` — Export all contacts as vCard 3.0 (.vcf).
- `dodaios contacts import <file> --yes --dry-run` — Import contacts from a vCard file (merges, never clobbers).
- `dodaios contacts list` — List contacts.
- `dodaios contacts show <slug>` — Show one contact.

## costs

- `dodaios costs entries --days --provider --model --role --surface --search --sort --limit --offset` — The individual model calls behind the totals.
- `dodaios costs rates --days` — The rate card per model — and which models have no published rate.
- `dodaios costs summary --days --provider --model --role --surface --search` — Totals plus the breakdown by provider, model, role, surface and day.

## docs

- `dodaios docs list` — List documentation pages.
- `dodaios docs search <query>` — Search the docs.
- `dodaios docs show <slug>` — Show one doc page's body.
- `dodaios docs tree` — Show the Diataxis-grouped doc tree.

## friends

- `dodaios friends add --json-body --yes --dry-run` — Add a friend.
- `dodaios friends delete <friend_id> --yes --dry-run` — Delete a friend and their channels.
- `dodaios friends edit <friend_id> --json-body --yes --dry-run` — Edit a friend (partial).
- `dodaios friends list` — List friends with their channels.
- `dodaios friends message <friend_id> --text --yes --dry-run` — Send an outbound message to a friend (consequential — needs --yes).
- `dodaios friends messages <friend_id>` — Show the message thread with a friend.
- `dodaios friends show <friend_id>` — Show one friend (detail + channels + permission profile).

## frontier

- `dodaios frontier ack --yes --dry-run` — Acknowledge (dismiss) the pending frontier proposals.
- `dodaios frontier pending` — List proposed model upgrades awaiting acknowledgement.

## ide

- `dodaios ide archive-terminal <name> --restore --workspace --dry-run` — Hide a coding session from the chat list, or restore it.
- `dodaios ide close-terminals <names> --yes --dry-run` — Stop several coding agents and close their terminal panes.
- `dodaios ide move-terminal <name> <target_workspace> --workspace --beside --side --dry-run` — Move a terminal pane into another open workspace.
- `dodaios ide rename-terminal <name> <new_name> --dry-run` — Rename a running terminal pane without restarting its agent.

## local-models

- `dodaios local-models assistant benchmarks --refresh --provider` — Read the benchmark data used by the assistant.
- `dodaios local-models assistant diagnose --provider` — Start a guided diagnostic conversation.
- `dodaios local-models assistant health --provider` — Read the selected provider's local-model health.
- `dodaios local-models assistant session --provider` — Read the existing assistant session and its readiness.
- `dodaios local-models assistant setup --provider` — Start the existing guided setup conversation.
- `dodaios local-models assistant test --role --provider` — Run the setup test for all roles or the selected roles.
- `dodaios local-models catalog recommended --provider` — The curated shortlist ranked for this machine, with its review date.
- `dodaios local-models catalog search <query> --sort --capability --limit --provider` — Browse the library; offline is reported as a sentence, not a failure.
- `dodaios local-models catalog tags <name> --provider` — Every tag of one library model with size, quantization, context and fit.
- `dodaios local-models hf enable <state> --provider --dry-run` — Show or flip the Hugging Face browsing switch.
- `dodaios local-models hf files <user> <repo> --provider` — The .gguf files of one repository with quantization, size and fit.
- `dodaios local-models hf pull <user> <repo> --quant --provider --dry-run` — Start pulling hf.co/<user>/<repo>[:<quant>] through the normal pull path.
- `dodaios local-models hf search <query> --sort --limit --provider` — GGUF repositories on Hugging Face.
- `dodaios local-models models delete <name> --reassign --provider --yes --dry-run` — Remove a download from the server (refused while a role still uses it).
- `dodaios local-models models list --provider` — Every download with its facts, what is loaded, and the disk total.
- `dodaios local-models models show <name> --provider` — One download with the long facts (license, parameters, template).
- `dodaios local-models models unload <name> --provider --yes --dry-run` — Free the memory a loaded model holds; the next turn pays the load again.
- `dodaios local-models options clear <name> --provider --dry-run` — Drop the profile so the server's defaults apply again.
- `dodaios local-models options get <name> --provider` — The profile of one model as configured (empty when none).
- `dodaios local-models options set <name> <values> --provider --dry-run` — Replace the profile of a model with the given knobs (whole set).
- `dodaios local-models options suggest <name> --provider` — An advisory profile for this machine, with one reason per knob.
- `dodaios local-models roles list --provider` — Every role with its pick, what qualifies, and the recommendation.
- `dodaios local-models roles set <role> <model> --provider --dry-run` — Assign a model to a role (written through the config writers).
- `dodaios local-models server autostart <state> --provider --dry-run` — Show or flip "start the server with Dodaios" (fires only while local models are in use).
- `dodaios local-models server env-guide --os --provider` — Copyable per-OS commands for the server's environment variables.
- `dodaios local-models server log --lines --provider` — The last lines of the server log Dodaios writes when it starts the server.
- `dodaios local-models server status --provider` — Runtime picture plus what is loaded and how much disk the downloads take.
- `dodaios local-models server stop --provider --yes --dry-run` — Stop the server Dodaios itself started (never one started elsewhere).
- `dodaios local-models server test <base_url> --provider` — Probe a host before saving it: version and latency, or why it failed.
- `dodaios local-models server verify --provider` — Prove the setup works: the server, one real chat answer, one real embedding.

## marketplace

- `dodaios marketplace browse` — Show everything the community marketplace offers, and what you already have.
- `dodaios marketplace connect-pat <plugin_id> --token --yes --dry-run` — Connect a plugin with a personal access token.
- `dodaios marketplace connect-poll <plugin_id> <flow_id>` — Poll an in-progress OAuth connect flow.
- `dodaios marketplace connect-start <plugin_id> --yes --dry-run` — Begin an OAuth connect flow (prints the redirect URI + flow id).
- `dodaios marketplace disconnect <plugin_id> --yes --dry-run` — Disconnect a plugin.
- `dodaios marketplace install <item_id> --yes --dry-run` — Install a marketplace entry by name — skill, plugin or agent — and report it.
- `dodaios marketplace list` — List marketplace plugins + their connection status.

## mcps

- `dodaios mcps check <name> --yes --dry-run` — Health-check an MCP server (lists its tools).
- `dodaios mcps delete <name> --yes --dry-run` — Remove an MCP server.
- `dodaios mcps disable <name> --yes --dry-run` — Disable an MCP server.
- `dodaios mcps enable <name> --yes --dry-run` — Enable an MCP server.
- `dodaios mcps import-claude-desktop --yes --dry-run` — Import MCP servers from the Claude Desktop config.
- `dodaios mcps list` — List MCP servers + a summary.

## missions

- `dodaios missions approve-tool <mission_id> <trace_id> --yes --dry-run` — Approve one paused mission tool call and resume it.
- `dodaios missions cancel <mission_id> --yes --dry-run` — Cancel a running mission (kills its worker).
- `dodaios missions deny-tool <mission_id> <trace_id> --reason --dry-run` — Deny one paused mission tool call without executing it.
- `dodaios missions dispatch <prompt> --language --confirmed --yes --dry-run` — Dispatch a new self-healing mission — spawns a worker (destructive: --yes).
- `dodaios missions kill <worker_id> --yes --dry-run` — Hard-kill a worker process by id.
- `dodaios missions list --state --limit` — List missions (optionally filtered by state).
- `dodaios missions rerun <mission_id> --confirmed --yes --dry-run` — Re-dispatch a terminal mission's prompt as a new linked mission.
- `dodaios missions result <mission_id>` — Read a mission's signed outcome and actual deliverable contents.
- `dodaios missions show <mission_id>` — Show one mission with its events + verdicts.
- `dodaios missions tool-approvals <mission_id>` — List supervisor tool calls waiting for approval in a mission.

## outputs

- `dodaios outputs files <slug>` — List the artifacts a mission produced.
- `dodaios outputs graph <slug>` — Print a session's mission-map page (self-contained HTML node graph).
- `dodaios outputs list` — List output sessions (a mission's deliverable folders).
- `dodaios outputs open-with <slug> <path> --opener --yes --dry-run` — Open an artifact with a chosen editor (desktop only).
- `dodaios outputs openers` — List installed editors/apps that can open an artifact.
- `dodaios outputs plan <slug>` — Show a session's plan + steps.
- `dodaios outputs preferred-opener <opener> --yes --dry-run` — Get or set the default artifact opener.

## permissions

- `dodaios permissions open-settings <permission_id> --yes --dry-run` — Open the matching macOS privacy pane through LaunchServices.
- `dodaios permissions request <permission_id> --yes --dry-run` — Ask macOS for one permission through the same service the app uses.
- `dodaios permissions reset <permission_id> --bundle-id --yes --dry-run` — Forget what macOS recorded for Dodaios, so it asks again on next use (macOS only).
- `dodaios permissions status --include-automation` — Show each macOS privacy permission and what is waiting on one. Never prompts.

## refresh

- `dodaios refresh` — Clear the cached API schema (next call re-fetches it).

## sessions

- `dodaios sessions command <session_id> <command> --arguments --request-id --yes --dry-run` — Run an explicit command in a Dodaios or agent chat.
- `dodaios sessions control <session_id>` — Read a chat's current work mode and persistent goal.
- `dodaios sessions delete <session_id> --yes --dry-run` — Delete a text conversation thread.
- `dodaios sessions latest-turn --session-id` — Show the latest persisted user transcript and its complete turn.
- `dodaios sessions list --days --limit` — List text + voice sessions, newest first.
- `dodaios sessions resume <kind> <session_id> --yes --dry-run` — Seed the brain from a past conversation to continue it in text.
- `dodaios sessions show <kind> <session_id>` — Show one conversation with its messages.
- `dodaios sessions speak <kind> <session_id> --yes --dry-run` — Start a voice session seeded from a past conversation (503 on headless).

## skills

- `dodaios skills catalog-install <name> --source-url --title --raw-url --yes --dry-run` — Install a skill from the catalog (lands as a draft).
- `dodaios skills catalog-search <query>` — Search the installable skill catalog.
- `dodaios skills commit --draft --yes --dry-run` — Commit a generated draft to disk (still state=draft until enabled).
- `dodaios skills create <intent> --name --trigger --schedule --language --yes --dry-run` — Author AND write a new skill in one step (the voice path's `create-skill`).
- `dodaios skills disable <name> --yes --dry-run` — Deactivate a skill.
- `dodaios skills draft <intent> --name-hint --category --trigger --schedule --language --yes --dry-run` — Generate a skill draft from an intent WITHOUT writing it (review, then `commit`).
- `dodaios skills enable <name> --yes --dry-run` — Activate a skill.
- `dodaios skills import <source> --yes --dry-run` — Install a skill from a local folder or a SKILL.md link.
- `dodaios skills list` — List all discovered skills.
- `dodaios skills reload --yes --dry-run` — Re-scan the skills directory.
- `dodaios skills show <name>` — Show one skill's detail.

## socials

- `dodaios socials add --json-body --yes --dry-run` — Add a social link.
- `dodaios socials delete <social_id> --yes --dry-run` — Delete a social link.
- `dodaios socials edit <social_id> --json-body --yes --dry-run` — Edit a social link (partial).
- `dodaios socials list` — List social links.

## system

- `dodaios system audio-devices --output --input` — List audio devices, or pick where the voice plays / which mic listens.
- `dodaios system restart --force --yes --dry-run` — Refuse a CLI restart; use the desktop UI's explicit Restart action.
- `dodaios system status` — Report server reachability + version (GET /api/control/auth/probe).

## tasks

- `dodaios tasks cancel <task_id> --yes --dry-run` — Soft-cancel a scheduled/running task.
- `dodaios tasks create --json-body --yes --dry-run` — Create + schedule a task from a TaskSpec JSON document.
- `dodaios tasks delete <task_id> --yes --dry-run` — Hard-delete a task (terminal states only, server-enforced).
- `dodaios tasks get <task_id>` — Show one task with its step timeline.
- `dodaios tasks list --state --limit` — List tasks (optionally filtered by state).

## telephony

- `dodaios telephony config` — Show the telephony config.
- `dodaios telephony outbound <to> --message --yes --dry-run` — Place a real outbound call (destructive: costs money; needs --yes).
- `dodaios telephony status` — Report telephony availability/status.

## version

- `dodaios version` — Print the CLI version.

## wiki

- `dodaios wiki backfill --days --max-sessions --preview --yes --dry-run` — Backfill recent Realtime sessions through evidence-safe Wiki capture.
- `dodaios wiki health` — Show wiki subsystem health: bootstrap, last write, chain failures, backlog (spec A5).
- `dodaios wiki ingest <text> --source --dry-run` — Store a fact through the guarded Wiki curator.
- `dodaios wiki page <slug>` — Read a wiki page by vault path / slug.
- `dodaios wiki recall <query>` — Full-text search the wiki.
- `dodaios wiki reindex --preview` — Rebuild the wiki search index from the active vault.
- `dodaios wiki tree` — Show the vault folder tree + stats.
- `dodaios wiki vaults` — List the user's registered Obsidian vaults (connect picker, spec A6).

## workflows

- `dodaios workflows create --def --yes --dry-run` — Create a workflow from a WorkflowDef JSON document.
- `dodaios workflows delete <workflow_id> --yes --dry-run` — Delete a workflow.
- `dodaios workflows list` — List workflows + a run summary.
- `dodaios workflows run <workflow_id> --yes --dry-run` — Trigger a workflow run.
- `dodaios workflows run-history --workflow-id` — List workflow runs (optionally for one workflow).
- `dodaios workflows show <workflow_id>` — Show one workflow + recent runs.


"""CLI-backed turns — a vendor agent binary drives the session.

Every coding CLI the Agentic IDE registers (``dodaios.workspace.agents``)
has a planner here, so the chat's picker offers the same CLIs a pane does
(maintainer, 2026-08-27: the CLIs connected in the Agentic IDE, and each
one drawn as a chat, never as a terminal). Nine entries, seven wire shapes:

* **Claude-shaped NDJSON** — ``claude`` (Claude Code), ``grok`` (Grok
  Build, whose ``--output-format streaming-messages-json`` is the Anthropic
  Messages wire shape on purpose) and GLM Coding Plan, which IS Claude Code
  pointed at Z.ai's endpoint through the registry's environment factory.
  One translator turns their ``system`` / ``stream_event`` / ``assistant`` /
  ``user`` / ``result`` lines into agent-chat events.
* **Codex NDJSON** — ``codex exec --json`` with ``thread.*`` / ``turn.*`` /
  ``item.*`` lines.
* **Antigravity NDJSON** — ``agy --output-format stream-json`` with
  ``event: init | step_update | result`` lines (``step_update`` carries text
  deltas and tool steps keyed by ``step_index``; verified against agy 1.1.19).
* **OpenCode NDJSON** — ``opencode run --format json`` with ``step_start`` /
  ``text`` / ``reasoning`` / ``tool_use`` / ``step_finish`` / ``error``
  lines, each wrapping one ``part`` of the session record and naming the
  session on every line (verified against opencode 1.18.23).
* **Kimi NDJSON** — ``kimi -p --output-format stream-json`` writes chat
  messages by ``role``: an ``assistant`` line with its text and
  ``tool_calls`` (OpenAI's function-call shape, arguments as a JSON string)
  and a ``tool`` line per result. Nothing streams and nothing names the
  session, so the id is found afterwards in Kimi's own session store
  (``agentic_ide.agent_sessions``), the way a pane finds its own
  (verified against kimi-code 0.29.2).
* **Plain text** — ``dsh --profile headless`` (DeepSeek Harness) prints the
  final message and exits: no tool stream, no session, one answer.
* **Cursor stream-json** — ``agent -p --output-format stream-json`` with
  ``system`` / ``assistant`` / ``tool_call`` / ``result`` lines (Cursor's
  documented print-mode wire; session id on every line).

Every CLI that keeps a conversation resumes it natively (``claude --resume``,
``codex exec resume``, ``grok -r``, ``agy --conversation``, ``opencode run
--session``, ``kimi --session``, ``agent --resume``), so the session row keeps the vendor's id
in ``vendor_session`` and a later turn continues the same conversation — the
tools, skills, MCP servers and permissions are the CLI's own, exactly as in
a terminal. The person's permission mode maps onto the closest stance each
CLI offers. A print-mode CLI cannot ask back: Claude answers permission
prompts over stdin; Codex has ``--approve-for-me``. agy 1.1.26 instead
soft-denies the tool and **exits**, so the chat shows ``run_command - failed``
and goes idle with no answer — ``accept-edits`` therefore also passes
``--dangerously-skip-permissions`` (the same flag the mission worker has
used since 2026-06). Jarvis tools reached over MCP still go through
:class:`~dodaios.core.protocols.SupervisorToolGateway`.

Spawning follows the mission workers: shell-free argv, the prompt on stdin
where the binary accepts it, ``NO_WINDOW_CREATIONFLAGS``, UTF-8 decoding,
and the agent-account environment (``dodaios.agent_accounts.spawn_env``) so
the active subscription seat is the one that answers.
"""

# ruff: noqa: F401, I001
from __future__ import annotations

import asyncio
from dataclasses import replace

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat.cli_catalog import CatalogCache, catalog_key, discover_codex_models
from dodaios.agent_chat.speed import apply_speed

from dodaios.agent_chat.runner_cli.base import (
    ACCOUNT_OVERRIDE,
    CLI_BINARIES,
    CliPlan,
    CliUnavailable,
    LeadModelInput,
    _ACCOUNT_ENVS,
    _CARRIED_HOMES,
    _CATALOG_CWD,
    _CATALOG_IGNORE_CONFIG,
    _CHILD_ENV_DROPS,
    _CLAUDE_CODE_RUNNERS,
    _COMPACT_IDENTITY_RUNNERS,
    _LEAD_RECORD,
    _PLAN_PREAMBLE,
    _PREPARED_MODELS,
    _REFRESH_EVERY,
    _REFRESH_SENT,
    _REMOTE_PLANNING,
    _SEAT_CONVERSATIONS,
    _TURN_SEATS,
    _account_env,
    _argv_prompt,
    _behind_shim,
    _carry_thread_conversation,
    _catalog_cwd,
    _cli_tool_summary,
    _digest,
    _identity_message,
    _is_batch,
    _is_usage_limit,
    _json_flag_value,
    _login_id,
    _note_turn_seat,
    _registry_env,
    _remember_models,
    _resolved_cwd,
    _seat_with_budget,
    _share_user_setup,
    _which,
    _with_identity,
    _without_parent_session,
    apply_child_env_drops,
    cli_catalog_scope,
    cli_installed,
    drop_child_env,
    lead_model_input,
    log,
    release_child_env,
    run_tag,
)
from dodaios.agent_chat.runner_cli.claude import (
    CLAUDE_ALLOW_BYPASS_FLAG,
    SILENT_TURN_REMINDER_ENV,
    TODO_TOOLS_ENV,
    _CARD_SESSION_MODES,
    _CLAUDE_COMMANDS_TIMEOUT_S,
    _CLAUDE_EDIT_TOOLS,
    _CLAUDE_RECOMMENDED,
    _CLAUDE_SHELL_TOOLS,
    _COMMAND_START,
    _SHELL_CHAINING,
    _VENDOR_SHELL_TOOLS,
    _VENDOR_WEB_AND_AGENT_TOOLS,
    _claude_refuses_bypass_here,
    _plan_claude_code,
    allow_bypass_after_plan,
    bridge_stance,
    claude_argv_prefix,
    claude_bypass_chosen,
    claude_control_init,
    claude_question_rows,
    claude_reported_commands,
    claude_rules_cover,
    claude_session_rules,
    claude_stream_input,
    dodaios_read_free,
    identity_turn_flags,
    opens_with_command,
    plan_claude,
    plan_glm,
    read_claude_commands,
    warm_claude_capabilities,
)
from dodaios.agent_chat.runner_cli.claude_stream import (
    GROK_BACKGROUND_WORK,
    _CHARS_PER_TOKEN,
    _CLAUDE_TASK_SUBTYPES,
    _CLAUDE_USAGE_KEYS,
    _ClaudeState,
    _GROK_BACKGROUND_TOOLS,
    _GROK_TASK_ENDED,
    _GROK_TASK_LIVE,
    _GROK_TASK_STARTED,
    _GROK_TASK_STATUS,
    _LIVE_OUTPUT_STEP,
    _TASK_ENDED_STATUSES,
    _claude_compaction_close,
    _claude_compaction_events,
    _claude_compaction_open,
    _claude_merge_usage,
    _claude_outstanding,
    _claude_request_summary,
    _claude_subagent_line,
    _claude_task_events,
    _claude_track_task,
    _claude_usage_event,
    _claude_usage_totals,
    _claude_wait_events,
    _content_text,
    _grok_track_tasks,
    _task_usage,
    grok_idle_wait,
    subagent_status,
    translate_claude_line,
)
from dodaios.agent_chat.runner_cli.grok import (
    grok_argv_prefix,
    plan_grok,
    read_grok_models,
)
from dodaios.agent_chat.runner_cli.agy import (
    AGY_FALLBACK_MODELS,
    _AGY_CATALOG,
    _AGY_CATALOG_TTL_S,
    _AGY_DEFAULT_EFFORT,
    _AGY_EFFORT_SUFFIXES,
    _AGY_PRINT_TIMEOUT,
    _AGY_TOOL_SUMMARY_KEYS,
    _AgyState,
    _agy_catalog_cached,
    _agy_catalog_is_live,
    _agy_effective_effort,
    _agy_model_ladder,
    _agy_summary,
    _is_base_gemini_id,
    _nearest_lower,
    _strip_effort_label,
    agy_argv_prefix,
    agy_model_args,
    agy_model_catalog,
    agy_probe_cwd,
    plan_agy,
    read_agy_models,
    translate_agy_line,
)
from dodaios.agent_chat.runner_cli.codex import (
    _CODEX_AGENT_LIVE,
    _CODEX_CATALOG,
    _CODEX_TASK_DISABLED,
    _CodexState,
    _codex_collab_events,
    _codex_item_id,
    _deliver_codex_images,
    codex_argv_prefix,
    isolate_task_tools,
    plan_codex,
    read_codex_models,
    translate_codex_line,
)
from dodaios.agent_chat.runner_cli.opencode import (
    _OPENCODE_CATALOG,
    _OPENCODE_CATALOG_TTL_S,
    _OPENCODE_TOKEN_KEYS,
    _OpenCodeState,
    _part_duration_ms,
    opencode_argv_prefix,
    plan_opencode,
    read_opencode_models,
    translate_opencode_line,
)
from dodaios.agent_chat.runner_cli.kimi import (
    _KimiState,
    _kimi_arguments,
    _kimi_session_after,
    kimi_argv_prefix,
    plan_kimi,
    translate_kimi_line,
)
from dodaios.agent_chat.runner_cli.custom import (
    dsh_argv_prefix,
    plan_custom_cli,
    plan_dsh,
)
from dodaios.agent_chat.runner_cli.cursor import (
    _CursorState,
    _cursor_message_text,
    _cursor_tool_output,
    _cursor_tool_payload,
    cursor_argv_prefix,
    plan_cursor,
    translate_cursor_line,
)
from dodaios.agent_chat.runner_cli.plans import (
    CLI_RUNNERS,
    _ACP_CANCEL_GRACE_S,
    _ACP_EXIT_GRACE_S,
    _ACP_HANDSHAKE_TIMEOUT_S,
    _ACP_IDLE_TIMEOUT_S,
    _ACP_WATCH_TICK_S,
    _PLANNERS,
    _release_plan,
    supports_cli_runner,
)
from dodaios.agent_chat.runner_cli.drive import (
    _EXIT_POLL_S,
    _GROK_IDLE_HINT_S,
    _HURRY,
    _KILL_WAIT_S,
    _LINGERING,
    _Outcome,
    _PIPE_DRAIN_S,
    _READLINE_LIMIT,
    _REAP_GRACE_S,
    _REAP_HURRY_S,
    _RESULT_EXIT_GRACE_S,
    _SHAPES,
    _TURN_TIMEOUT_S,
    _TextState,
    _UNRESOLVED_TOOLS,
    _WAKE_GRACE_S,
    _answer_settled,
    _await_lingering,
    _close_pipes,
    _drive_cli,
    _exited_within,
    _hosted_meta,
    _kill,
    _linger,
    _natural_end,
    _note_lead_input,
    _pipes_went_quiet,
    _reap_after_answer,
    _run_cli_once,
    _spawn_child,
    _survives_restart,
    _translate_nothing,
    _unread,
    _until_end_or_answer,
    _until_exit,
)
from dodaios.agent_chat.runner_cli.turn import (
    SEAT_SWITCH_NOTICE_KIND,
    _ALREADY_SENT,
    _MODEL_FALLBACK_SURFACES,
    _RESUME_LOST_MARKERS,
    _RUNTIME_READY_FIRST_DELAY_S,
    _RUNTIME_READY_MAX_DELAY_S,
    _RUNTIME_READY_WAIT_S,
    _TOOL_ABORT_MARKERS,
    _continue_on_fallback_model,
    _continue_on_next_seat,
    _ensure_seat_watch,
    _fallback_spent,
    _keep_going_prompt,
    _lead_record,
    _merge_cli_outcome,
    _model_fallback_takes,
    _on_model,
    _resume_was_lost,
    _send_again_when_runtime_ready,
    _surface_identity,
    _switch_thread_model,
    _tool_abort_is_recoverable,
    resume_hosted_cli_turn,
    run_cli_turn,
)

"""Claude Code (and GLM) planning: argv, control handshake, permission rules, plan builders."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat import runner_cli as _rc
from dodaios.agent_chat.permissions import (
    ladder_key,
    mode_after_plan,
    normalize_permission,
)
from dodaios.agent_chat.runner_cli.base import (
    _CLAUDE_CODE_RUNNERS,
    CLI_BINARIES,
    CliPlan,
    CliUnavailable,
    _identity_message,
    _json_flag_value,
    _resolved_cwd,
    log,
)
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS


def claude_argv_prefix() -> list[str]:
    binary = _rc._which(*CLI_BINARIES["claude-cli"])
    if not binary:
        raise CliUnavailable("Claude Code (claude) is not installed or not on PATH.")
    from dodaios.claude_auth import claude_cli_argv_prefix

    return claude_cli_argv_prefix(binary)


def warm_claude_capabilities() -> None:
    """Run the Claude CLI's flag probes (blocking, cached) so planning only reads them."""
    from dodaios.claude_auth import (
        claude_cli_supports_allow_bypass,
        claude_cli_supports_thinking_display,
    )

    try:
        prefix = _rc.claude_argv_prefix()
    except CliUnavailable:
        return  # planning reports the missing CLI itself
    claude_cli_supports_thinking_display(prefix)
    claude_cli_supports_allow_bypass(prefix)


def claude_control_init() -> str:
    """The handshake that turns Claude Code's control protocol on.

    Without it, ``--permission-prompt-tool stdio`` is a flag the CLI accepts
    and never uses: it has no client on the other end that it knows can answer,
    so every tool call runs straight through and "Ask before acting" behaves
    exactly like "Auto-accept edits" (maintainer report 2026-08-24). The CLI
    answers this with a ``control_response`` listing its commands; from then on
    a permission prompt arrives as ``control_request {subtype: can_use_tool}``
    and the chat's approval card answers it on stdin.

    ``hooks: null`` says this client registers none of its own — the CLI's
    configured hooks still run.
    """
    return (
        json.dumps(
            {
                "type": "control_request",
                "request_id": "jarvis-init",
                "request": {"subtype": "initialize", "hooks": None},
            },
            ensure_ascii=False,
        )
        + "\n"
    )


#: How long Claude Code gets to answer the handshake of a command-list probe.
_CLAUDE_COMMANDS_TIMEOUT_S: Final[float] = 12.0


def claude_reported_commands(obj: dict[str, Any]) -> list[Any] | None:
    """The command list inside one line of Claude Code's stream, if it has one.

    Three lines carry it: the answer to the control handshake (every command
    with its description and argument hint), the ``system/init`` event of a
    turn (names only) and ``system/commands_changed`` (the full list again,
    sent when a skill or plugin appeared mid-session).
    """
    body: Any = obj
    if obj.get("type") == "control_response":
        inner = obj.get("response")
        body = inner.get("response") if isinstance(inner, dict) else None
    elif not (obj.get("type") == "system" and obj.get("subtype") in ("init", "commands_changed")):
        return None
    if not isinstance(body, dict):
        return None
    for key in ("commands", "slash_commands"):
        found = body.get(key)
        if isinstance(found, list) and found:
            return found
    return None


def read_claude_commands(runner: str, cwd: Path | str | None) -> list[Any] | None:
    """The slash commands Claude Code itself lists in ``cwd``, asked without a turn.

    The CLI answers the control handshake (``claude_control_init``) with every
    command it accepts — its built-ins (``/goal``, ``/compact``, ...), the
    skills and the plugin commands — each with a description and an argument
    hint. Stdin ends right after the handshake: no message is sent, no model is
    called, and the CLI exits. The probe keeps no session, starts no MCP server
    and runs no hook, because it stands for a "/" typed in a thread, not for
    work.

    Blocking (about a second) — call it off the event loop. ``None`` when the
    CLI is missing, the seat is not configured, or no list came back (an older
    CLI that does not know one of the flags).
    """
    import subprocess

    try:
        if runner == "glm-cli":
            env = _rc._registry_env("glm", dict(os.environ))
        else:
            env = _rc._account_env("claude")
        argv = [
            *_rc.claude_argv_prefix(),
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--input-format",
            "stream-json",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--settings",
            json.dumps({"disableAllHooks": True}),
        ]
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv,
            input=claude_control_init().encode("utf-8"),
            capture_output=True,
            timeout=_CLAUDE_COMMANDS_TIMEOUT_S,
            env=env,
            cwd=str(_resolved_cwd(cwd)),
            creationflags=NO_WINDOW_CREATIONFLAGS,
            check=False,
        )
    except (CliUnavailable, OSError, subprocess.SubprocessError) as exc:
        log.debug("agent chat: %s command list unavailable: %s", runner, type(exc).__name__)
        return None
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:  # a non-JSON line of the CLI is not the answer
            continue
        if isinstance(obj, dict) and obj.get("type") == "control_response":
            return claude_reported_commands(obj)
    return None


#: The session modes an "Always allow" on one card may switch Claude Code to.
_CARD_SESSION_MODES: Final[frozenset[str]] = frozenset({"acceptEdits"})


def claude_session_rules(tool_name: str, suggestions: Any) -> list[dict[str, Any]]:
    """What "Always allow" answers Claude Code: its own rule, for this session.

    A ``can_use_tool`` request carries ``permission_suggestions`` — the rule
    its own prompt would offer ("don't ask again for git log commands here").
    Those name a settings file as their destination; the chat keeps them to
    the running session, so a click never writes into the person's repo or
    user settings. Without a suggestion the tool itself is allowed.

    A suggestion that switches the whole session to a mode above "accept
    edits" is dropped: one click on one card must never put the thread in
    "Bypass permissions". Only the permission pill does that.
    """
    rules = [
        {**rule, "destination": "session"}
        for rule in (suggestions if isinstance(suggestions, list) else [])
        if isinstance(rule, dict)
        and rule.get("type")
        and (rule.get("type") != "setMode" or rule.get("mode") in _CARD_SESSION_MODES)
    ]
    return rules or [
        {
            "type": "addRules",
            "rules": [{"toolName": tool_name}],
            "behavior": "allow",
            "destination": "session",
        }
    ]


#: The gated tools that Claude Code's "accept edits" mode lets through.
_CLAUDE_EDIT_TOOLS: Final[frozenset[str]] = frozenset(
    {"Edit", "Write", "MultiEdit", "NotebookEdit"}
)

_CLAUDE_SHELL_TOOLS: Final[frozenset[str]] = frozenset({"Bash", "PowerShell"})

#: Characters that chain, redirect or substitute shell commands. A prefix rule
#: ("git log:*") speaks for ONE command; Claude Code splits a compound line
#: before matching, this matcher does not, so such a line always asks again.
_SHELL_CHAINING: Final[tuple[str, ...]] = (";", "&", "|", "<", ">", "`", "$(", "\n", "\r")


def claude_rules_cover(rules: Iterable[dict[str, Any]], tool_name: str, tool_input: Any) -> bool:
    """Whether a rule from an earlier "Always allow" in this session covers a call.

    Every turn is a new CLI process that has not heard of the session rule an
    earlier card handed its predecessor, so the runner answers the repeat
    itself. Only what the rule clearly covers
    is answered: the whole tool, a shell command prefix, or the edit tools of
    an "accept edits" mode. Anything else asks again (the safe side).
    """
    from fnmatch import fnmatchcase

    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or "").strip()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        kind = rule.get("type")
        if kind == "setMode":
            # Only "accept edits" is a mode a card may grant (``_CARD_SESSION_MODES``).
            mode = rule.get("mode")
            if mode == "acceptEdits" and tool_name in _CLAUDE_EDIT_TOOLS:
                return True
            continue
        if kind not in ("addRules", "replaceRules") or rule.get("behavior") != "allow":
            continue
        for entry in rule.get("rules") or ():
            if not isinstance(entry, dict) or entry.get("toolName") != tool_name:
                continue
            content = str(entry.get("ruleContent") or "").strip()
            if not content:
                return True
            if tool_name in _CLAUDE_SHELL_TOOLS and command:
                if any(mark in command for mark in _SHELL_CHAINING):
                    continue
                pattern = content[:-2] + " *" if content.endswith(":*") else content
                if command == content or command == pattern.removesuffix(" *"):
                    return True
                if fnmatchcase(command, pattern):
                    return True
    return False


def bridge_stance(runner: str, session: Any) -> str:
    """The stance Dodaios' own tool gate takes for a vendor CLI session.

    The agent surface hands no stance to the runner (the vendor CLI keeps its
    own ladder), so the gate would ask for every consequential Dodaios tool,
    even when the person picked "Bypass permissions" or "Full access" there.
    The top rung of every ladder is the promise that nothing asks; the gate
    keeps it. Every lower rung asks as before.
    """
    mode = str(getattr(session, "permission_mode", "") or "")
    try:
        from dodaios.agent_chat.permissions import _stance

        return "bypass" if mode and _stance(runner, mode) >= 3 else "ask"
    except Exception:  # noqa: BLE001 - an unknown runner or mode asks, as before
        return "ask"


def claude_bypass_chosen(runner: str, session: Any) -> bool:
    """Whether the person picked "Bypass permissions" for this Claude Code session.

    "Bypass permissions" promises that nothing asks. Claude Code keeps that
    promise until the model calls ``EnterPlanMode`` on its own: from then on
    the process sends a permission prompt for every shell command, and each
    one became an approval card (live 2026-11-11). The session's stored mode
    is still the person's pick, so the runner answers those prompts itself.
    The plan approval (``ExitPlanMode``) and the model's own questions
    (``AskUserQuestion``) are not permission prompts and still reach the person.
    """
    stance = str(getattr(session, "permission_mode", "") or "")
    if not stance:
        return False
    try:
        return normalize_permission(runner, stance) == "bypassPermissions"
    except Exception:  # noqa: BLE001 - an unknown runner or mode asks, as before
        return False


#: Offers "Bypass permissions" to a Claude Code process without starting in it.
CLAUDE_ALLOW_BYPASS_FLAG: Final[str] = "--allow-dangerously-skip-permissions"


def _claude_refuses_bypass_here() -> bool:
    """Whether Claude Code would exit instead of offering bypass (root outside a sandbox)."""
    geteuid = getattr(os, "geteuid", None)
    return callable(geteuid) and geteuid() == 0 and os.environ.get("IS_SANDBOX") != "1"


def allow_bypass_after_plan(argv: list[str], runner: str, session: Any) -> None:
    """Let a Claude Code turn that starts in Plan go on in "Bypass permissions".

    An approved plan is answered with the mode the thread returns to. Claude
    Code takes "bypassPermissions" from that answer only when the process was
    started with bypass on offer; otherwise it drops to its ask-everything
    mode and every call of the building turn became an approval card (live
    2026-11-15). So a thread that plans and whose permission pill says
    "Bypass permissions" starts with the offer.

    Left out where the CLI would not start with it: an older CLI that does
    not know the flag, and root outside a sandbox. There the runner answers
    the prompts itself once the plan is approved (:func:`claude_bypass_chosen`).
    """
    if runner not in _CLAUDE_CODE_RUNNERS or CLAUDE_ALLOW_BYPASS_FLAG in argv:
        return
    try:
        started_in = argv[argv.index("--permission-mode") + 1]
    except (ValueError, IndexError):  # no mode on the command line: nothing to offer
        return
    if started_in != "plan":
        return
    from dodaios.agent_chat.surface_kits import kit_for
    from dodaios.claude_auth import claude_cli_allow_bypass_known

    surface = str(getattr(session, "surface", "") or "agent")
    if not kit_for(surface).turn_prompts:
        return  # only a coding thread's plan approval names a mode (``_leave_plan_mode``)
    build = mode_after_plan(
        ladder_key(surface, runner),
        str(getattr(session, "permission_mode", "") or ""),
        str(getattr(session, "build_mode", "") or ""),
    )
    if normalize_permission(runner, build) != "bypassPermissions":
        return
    if _rc._claude_refuses_bypass_here():
        return
    try:
        known = claude_cli_allow_bypass_known(_rc.claude_argv_prefix())
    except CliUnavailable:  # planning reports the missing CLI itself
        return
    if known:
        argv.append(CLAUDE_ALLOW_BYPASS_FLAG)


async def dodaios_read_free(session: Any, tool_name: str, tool_input: Any) -> bool:
    """Whether a Claude Code prompt for one of Dodaios' own tools needs no card.

    In "Ask" a read runs freely and only actions and writes ask. Claude Code
    asks about every MCP tool it has no allow rule for, so a listing such as
    ``society_routines`` would put a card in front of the person. A tool the
    Dodaios tool server marks read-only (``readOnlyHint``, for these
    arguments) is answered here; a write still goes to the card, and the
    Dodaios tool gate checks it again when it runs. "Always ask", Plan, and an
    agent's own require-approval rule keep asking.
    """
    from dodaios.core.branding import MCP_TOOLS_SERVER_NAME

    prefix = f"mcp__{MCP_TOOLS_SERVER_NAME}__"
    if not tool_name.startswith(prefix):
        return False
    stance = str(getattr(session, "permission_mode", "") or "")
    if stance in ("always_ask", "plan", "read-only"):
        return False
    wire = tool_name[len(prefix) :]
    args = tool_input if isinstance(tool_input, dict) else {}
    session_id = str(getattr(session, "session_id", "") or "")
    try:
        from dodaios.mcp.dodaios_tools_server import wire_read_only

        if not await wire_read_only(session_id, wire, args):
            return False
        if session_id.startswith("society:"):
            from dodaios.society.surface import requires_explicit_approval

            return not requires_explicit_approval(session_id, wire, args)
    except Exception:  # noqa: BLE001 — unsure means the card asks, as before
        log.debug("agent chat: read-only check failed for %s", tool_name, exc_info=True)
        return False
    return True


#: How Claude Code marks the option it recommends: a suffix on the label.
_CLAUDE_RECOMMENDED: Final[re.Pattern[str]] = re.compile(r"\s*\(recommended\)\s*$", re.I)


def claude_question_rows(rows: list[Any]) -> list[Any]:
    """Claude Code's ``AskUserQuestion`` rows as the question card reads them.

    The CLI's model writes its recommendation into the label ("Via Singapore
    (Recommended)"). The card has its own mark for that, on the first row: the
    suffix comes off and the option is named as the recommended one, so the
    card moves it to the front instead of showing the words twice. A question
    with no such suffix recommends nothing (``recommended: None``), so the
    card puts no mark on an option the model did not recommend.
    """
    out: list[Any] = []
    for row in rows:
        options = row.get("options") if isinstance(row, dict) else None
        if not isinstance(options, list):
            out.append(row)
            continue
        cleaned: list[Any] = []
        recommended: int | None = None
        for index, option in enumerate(options):
            label = option.get("label") if isinstance(option, dict) else option
            if isinstance(label, str) and _CLAUDE_RECOMMENDED.search(label):
                label = _CLAUDE_RECOMMENDED.sub("", label)
                option = {**option, "label": label} if isinstance(option, dict) else label
                if recommended is None:
                    recommended = index
            cleaned.append(option)
        out.append({**row, "options": cleaned, "recommended": recommended})
    return out


def claude_stream_input(prompt: str) -> str:
    """One NDJSON user message for ``--input-format stream-json``."""
    return (
        json.dumps(
            {"type": "user", "message": {"role": "user", "content": prompt}},
            ensure_ascii=False,
        )
        + "\n"
    )


#: The vendor tools Claude Code does not get on an identity turn (the lead's and a
#: society seat's). They reach the web or the machine, or start a sub-agent, without
#: passing the Dodaios gateway, where the risk tiers, the origin ledger, the outbound
#: check and the audit log live (AP-3):
#:
#: * ``WebSearch`` / ``WebFetch``: the Dodaios web tools stamp every result with its origin.
#: * ``Task`` / ``Agent``: the lead delegates through the Dodaios tools; a society seat
#:   is a worker and hires nobody.
_VENDOR_WEB_AND_AGENT_TOOLS: Final[tuple[str, ...]] = ("WebSearch", "WebFetch", "Task", "Agent")


#: The lead's shell goes through ``run_shell`` on the Dodaios gateway, which tiers
#: every command by its impact. The vendor's own shell would run the same command
#: with no tier, no approval card and no audit record (the live lead ran 34 of them).
#: The vendor's file tools stay: they act in the chat's working folder and the
#: chat's permission mode applies to them. A society seat keeps its vendor shell
#: because its briefing promises one in its own workspace and it also has
#: ``society_shell``.
_VENDOR_SHELL_TOOLS: Final[tuple[str, ...]] = (
    "Bash",
    "BashOutput",
    "KillShell",
    "KillBash",
    "PowerShell",
    "Monitor",
)


_COMMAND_START: Final[re.Pattern[str]] = re.compile(r"^\s*/[A-Za-z0-9][\w:.-]*(?:\s|$)")


def opens_with_command(prompt: str) -> bool:
    """Whether a message opens with a slash command (``/context``, ``/goal ship it``).

    A CLI runs a command only when it is the first thing of the message, so
    nothing may be put in front of such a message. A path (``/usr/bin``) is
    not a command: its first word has a second slash.
    """
    return bool(_COMMAND_START.match(prompt or ""))


def identity_turn_flags(runner: str, identity: dodaios_harness.Identity) -> list[str]:
    """The flags that keep an identity turn (lead or society seat) inside the gateway.

    Claude Code (and GLM, which is Claude Code): ``--strict-mcp-config`` loads only
    the Dodaios server, so the person's own MCP servers and the cloud connectors of
    their Claude account (a mail connector, say) are not reachable around the trust
    layer; the vendor's web, sub-agent and (for the lead) shell tools are removed.
    Grok Build: its web tools are disabled. Codex does the equivalent in ``plan_codex``.
    The other seats have no flag for it; ``docs/lead-seat-parity.md`` lists the gaps.
    """
    society = identity.session_id.startswith("society:")
    if runner == "claude-cli":
        removed = _VENDOR_WEB_AND_AGENT_TOOLS + (() if society else _VENDOR_SHELL_TOOLS)
        return ["--strict-mcp-config", "--disallowedTools", ",".join(removed)]
    if runner == "grok-cli":
        return ["--disable-web-search"]
    return []


def plan_claude(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None = None,
) -> CliPlan:
    return _plan_claude_code(
        prompt=prompt,
        cwd=cwd,
        model=model,
        effort=effort,
        permission_mode=permission_mode,
        resume=resume,
        identity=identity,
        env=dodaios_harness.apply_env(_rc._account_env("claude")),
        thinking_summaries=True,
        tool_summaries=True,
    )


def plan_glm(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None = None,
) -> CliPlan:
    """GLM Coding Plan: Claude Code's own plan, pointed at Z.ai by the registry.

    Z.ai ships no CLI; its documentation says to run Anthropic's binary
    against its endpoint, so everything — the control protocol that answers
    permission prompts from the chat, ``--resume``, the MCP tools — is
    inherited rather than re-implemented. Two things differ: the environment
    is ``glm_spawn_env``'s (and its ``None`` refuses the turn instead of
    letting Claude Code answer from, and bill, the wrong vendor), and no
    ``--effort`` is sent, because that flag belongs to Anthropic's endpoint
    (``_GLM_PICKS`` in ``dodaios.workspace.agents``).
    """
    return _plan_claude_code(
        prompt=prompt,
        cwd=cwd,
        model=model,
        effort="",
        permission_mode=permission_mode,
        resume=resume,
        identity=identity,
        env=dodaios_harness.apply_env(_rc._registry_env("glm", dict(os.environ))),
        ladder="glm-cli",
    )


#: Claude Code's switch for its mid-turn "say what you're doing" reminder.
SILENT_TURN_REMINDER_ENV: Final[str] = "CLAUDE_CODE_SILENT_TURN_REMINDER"


#: Claude Code's switch for the tools an agent keeps its own to-do list with.
TODO_TOOLS_ENV: Final[str] = "CLAUDE_CODE_ENABLE_TODO_TOOLS"


def _plan_claude_code(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None,
    env: dict[str, str],
    thinking_summaries: bool = False,
    tool_summaries: bool = False,
    ladder: str = "claude-cli",
) -> CliPlan:
    # GLM runs this binary with its own ladder (acceptEdits, no Auto).
    mode = normalize_permission(ladder, permission_mode)
    if tool_summaries:
        # Claude Code then writes a short title after each run of tool calls
        # ("Read a.txt", "Rewrote the parser and ran its tests"), the line a
        # thread shows for that run. Anthropic's endpoint only: GLM's is never
        # asked for the extra summary call.
        env = {**env, "CLAUDE_CODE_EMIT_TOOL_USE_SUMMARIES": "true"}
    if identity is None and TODO_TOOLS_ENV not in env:
        # A coding thread: the agent may keep a to-do list for a longer job,
        # and the thread shows it as a checklist. Claude Code gives its list
        # tools (TaskCreate, TaskUpdate, ...) to its newer models only when the
        # host asks for them; older models have them anyway. A person who set
        # the variable themselves keeps their choice.
        env = {**env, TODO_TOOLS_ENV: "true"}
    if identity is not None:
        # An assistant's chat (Jarvis or a society seat): every text is a chat
        # message. Claude Code's own "the user hasn't heard from you, say what
        # you're doing" reminder made the assistant send status messages
        # nobody asked for (seven in one evening, 2026-11-12). The chat shows
        # that it works; the reply style says when to write.
        env = {**env, SILENT_TURN_REMINDER_ENV: "0"}
    prefix = _rc.claude_argv_prefix()
    argv = [
        *prefix,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        # The control protocol: the user message goes in as NDJSON and a
        # permission prompt comes back as a ``control_request`` line that the
        # chat answers on stdin — so "ask" really asks, here, in the chat.
        "--input-format",
        "stream-json",
        "--permission-prompt-tool",
        "stdio",
        "--permission-mode",
        mode,
    ]
    settings: dict[str, Any] = {}
    if effort == "ultracode":
        # Claude Code's Ultracode is no ``--effort`` value of its own: it is
        # the session-scoped ``ultracode`` setting (standing multi-agent
        # workflow orchestration) on top of ``xhigh`` — the level the CLI's
        # own ``/effort ultracode`` keeps. The CLI ignores the key on a model
        # or account that cannot run workflows.
        settings["ultracode"] = True
        effort = "xhigh"
    if identity is not None:
        # An assistant's own file and shell tools never open the secret store:
        # a hook refuses the call before it runs, in every permission mode
        # (dodaios/credential_broker/vault_guard.py).
        from dodaios.credential_broker.vault_guard import hook_settings

        settings.update(hook_settings())
    if settings:
        argv += ["--settings", _json_flag_value(prefix, json.dumps(settings))]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    # Without this the stream carries empty thinking blocks and the chat shows
    # no reasoning. The probe ran off the event loop before planning
    # (``warm_claude_capabilities``); an older CLI without the flag skips it.
    # Anthropic's endpoint only — GLM's compatible one is not asked for a
    # thinking setting it never documented.
    from dodaios.claude_auth import claude_cli_thinking_display_known

    if thinking_summaries and claude_cli_thinking_display_known(prefix):
        argv += ["--thinking-display", "summarized"]
    # Jarvis' own tools, and the identity that says when to use them. Both are
    # skipped when the app cannot offer them (no control key, server not bound
    # yet) — the session then behaves exactly as it did before. On the Jarvis
    # surface the identity is Jarvis' whole head, in a FILE: argv cannot carry
    # it on Windows (32 767 characters for the whole command line).
    mcp_config = dodaios_harness.mcp_config_json(identity.session_id if identity else None)
    if mcp_config:
        argv += ["--mcp-config", _json_flag_value(prefix, mcp_config)]
        if identity is not None:
            argv += identity_turn_flags("claude-cli", identity)
        if identity is not None and identity.path is not None:
            argv += ["--append-system-prompt-file", str(identity.path)]
        elif identity is not None:
            argv += ["--append-system-prompt", dodaios_harness.SYSTEM_PREAMBLE]
        else:
            # No assistant identity: a coding thread, which keeps its sub-agents.
            argv += ["--append-system-prompt", dodaios_harness.CODING_PREAMBLE]
    from dodaios.agent_chat.thread_sessions import split_fork

    # The lead's resumed conversation: what landed in the chat outside this CLI
    # session goes in front of the message; the identity travels in the file.
    prompt = _identity_message(ladder, prompt, identity, resume)
    resume_id, fork_source = split_fork(resume)
    if fork_source:
        # A forked thread's first turn: Claude copies the source conversation
        # under the new id (the one combination that also takes --session-id).
        sid = str(uuid.uuid4())
        argv += ["--resume", fork_source, "--fork-session", "--session-id", sid]
    elif resume_id:
        argv += ["--resume", resume_id]
        sid = resume_id
    else:
        sid = str(uuid.uuid4())
        argv += ["--session-id", sid]
    return CliPlan(
        argv,
        env,
        claude_stream_input(prompt),
        "claude",
        sid,
        keep_stdin=True,
        control_init=claude_control_init(),
    )

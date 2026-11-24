"""Command definitions: agentic ide.

Split mechanically out of ``dodaios.commands.registry._build_registry``; the order of
the assembled registry is pinned by tests/unit/commands/test_registry_snapshot.py.
"""
from __future__ import annotations

from dodaios.commands.registry import (
    AppCommand,
    _coding_agent_ids,
    _str_param,
)


def _part1() -> tuple[AppCommand, ...]:
    return (
        # The Agentic IDE runs coding agents in named terminals; these three
        # commands are what make the workspace addressable by voice. Reading is
        # free (status / report); writing is one narrow channel — type a prompt
        # into a named terminal — and it can only ever type text plus Enter (the
        # endpoint strips control characters, so voice cannot interrupt or kill
        # an agent). No entry here is worker_allowed: a mission worker has no
        # business steering the user's interactive coding panes (AP-5).
        AppCommand(
            id="agentic-ide-status",
            title="Agentic IDE status",
            description=(
                "Report the open Agentic-IDE workspace: which folder, which "
                "coding agents run in which named terminals, and whether the "
                "focused coding mode is on."
            ),
            method="GET",
            # The brief projection, deliberately not /state: the full state is
            # a ~25 000-character UI snapshot whose tail the tool-result cap
            # slices off mid-JSON — the model paid ~2 000 input tokens per
            # loop iteration for a broken fragment (2026-07-28 cost audit).
            path="/api/agentic-ide/state/brief",
            ui_section="agentic-ide",
            voice_aliases={
                "de": ("was läuft in der agentic ide",),  # i18n-allow: input vocab
                "en": ("what is running in the agentic ide",),
                "es": ("qué se está ejecutando en el ide agéntico",),  # i18n-allow: input vocab
                "pt": ("o que está a correr no ide agêntico",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="agentic-ide-terminal-report",
            title="Report on one Agentic-IDE terminal",
            description=(
                "Read what the coding agent in a named terminal is doing — its "
                "status and its recent terminal output. Use this whenever the "
                "user asks about a terminal by name (e.g. 'what is Mika doing?')."
            ),
            method="GET",
            path="/api/agentic-ide/terminals/{name}/report",
            params={
                "type": "object",
                "properties": {
                    "name": _str_param(
                        "Call-sign of the terminal, e.g. 'Mika'.", min_length=1
                    ),
                    "lines": {
                        "type": "integer",
                        "default": 40,
                        # Model-facing ceiling only; the REST route itself
                        # clamps at 300 for the UI. Past ~60 lines the
                        # tool-result cap truncates the report anyway, so a
                        # larger ask just burns input tokens on every
                        # further loop iteration (2026-07-28 cost audit).
                        "minimum": 1,
                        "maximum": 60,
                        "description": "How many recent output lines to read.",
                    },
                },
                "required": ["name"],
            },
            path_params=("name",),
            ui_section="agentic-ide",
            voice_aliases={
                "de": ("was macht mika",),  # i18n-allow: input vocab
                "en": ("what is mika doing",),
                "es": ("qué está haciendo mika",),  # i18n-allow: input vocab
                "pt": ("o que está a mika a fazer",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="agentic-ide-prompt",
            title="Prompt an Agentic-IDE terminal",
            description=(
                "Send an instruction to the coding agent in ONE terminal. "
                "Terminals are called T plus their place in the grid (T1, T2, "
                "T3, left to right). Use this whenever the user tells a "
                "terminal to do something ('tell T1 to ...', "
                "'T2 soll ...', "  # i18n-allow: quoted addressing example
                "'let terminal three "
                "refactor ...', 'prompt the second terminal') "
                "— that work belongs to that agent, never to a background "
                "worker. For SEVERAL terminals ('T1 and T2 both ...', 'let "
                "the two of them ...') call 'agentic-ide-fanout' instead, with "
                "every call-sign in 'terminals': it briefs them at once and "
                "reports which ones really got the work. Calling this command "
                "twice for a pair leaves the second agent idle whenever the "
                "second call is forgotten, which is the failure mode fanout "
                "exists to remove. "
                "Pass the instruction in the USER's words: everything "
                "they asked for, every constraint and file they named, nothing "
                "invented and nothing summarised away. Do NOT write the brief "
                "yourself — a prompt writer that has read this repository turns "
                "what you pass into a briefed task with the relevant files "
                "attached, and a headline you composed instead arrives at the "
                "agent as its whole assignment. "
                "Only ever names a terminal that is ALREADY running: if the "
                "call fails with 'no terminal called …', opening a pane will not "
                "create that name — use 'agentic-ide-fanout' with spawn to open "
                "and brief one in a single step, and never repeat the spawn. "
                "CHECK THE REPLY: it carries a 'submitted' flag. True means the "
                "agent accepted the prompt and started. False means the text is "
                "only sitting in that terminal's input box — say so plainly and "
                "name the terminal, never report it as done."
            ),
            method="POST",
            path="/api/agentic-ide/terminals/{name}/prompt",
            params={
                "type": "object",
                "properties": {
                    "name": _str_param(
                        "Call-sign of the terminal to prompt, e.g. 'Mika'.",
                        min_length=1,
                    ),
                    "prompt": _str_param(
                        "The instruction to type into that agent.",
                        min_length=1,
                        max_length=4000,
                    ),
                    "compose": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "Leave this out. On by default: the instruction is "
                            "rewritten into a briefed task with this "
                            "workspace's files attached, which is what makes a "
                            "spoken sentence worth running. Set it false ONLY "
                            "for a literal keystroke that must reach the agent "
                            "unchanged, such as 'continue' or 'yes'."
                        ),
                    },
                },
                "required": ["name", "prompt"],
            },
            path_params=("name",),
            ui_section="agentic-ide",
            voice_aliases={
                "de": ("sag mika sie soll die tests laufen lassen",),  # i18n-allow: input vocab
                "en": ("tell mika to run the tests",),
                "es": ("dile a mika que ejecute las pruebas",),  # i18n-allow: input vocab
                "pt": ("diz à mika para correr os testes",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="agentic-ide-fanout",
            title="Open and brief Agentic-IDE terminals in one step",
            description=(
                "Give ONE task to coding terminals — existing ones, brand-new "
                "ones, or both — in a single call. This is the ONLY correct way "
                "to handle 'if no terminal is called that, open one and prompt "
                "it' and 'spawn N terminals and let them do X': pass the work as "
                "'instruction', the panes to brief as 'terminals', and the panes "
                "to open first as 'spawn'. Never emulate it by opening panes and "
                "then prompting — call-signs are the panes' positions (T1, T2, "
                "…) and are assigned by the workspace, so a "
                "pane you open is NOT called the name you had in mind, and "
                "re-spawning after a failed prompt just leaves blank panes "
                "behind. Set 'split' true only when the user asked for the work "
                "to be DIVIDED between the agents. "
                "CHECK THE REPLY: 'delivered' names the agents that really got "
                "the task and 'undelivered' those that did not — report both, "
                "and use the call-signs the reply gives you. A spawn repeating "
                "an instruction that recently went to panes still open is "
                "refused as a duplicate; the refusal names who is already on "
                "it — tell the user that fleet is working, do not retry."
            ),
            method="POST",
            path="/api/agentic-ide/fanout",
            params={
                "type": "object",
                "properties": {
                    "instruction": _str_param(
                        "The work the agents should do, in plain words.",
                        min_length=1,
                        max_length=4000,
                    ),
                    "terminals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Call-signs of running terminals to brief. Leave "
                            "empty to brief only the newly opened panes."
                        ),
                    },
                    "spawn": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "count": {
                                    "type": "integer",
                                    "description": "Panes to open in this group.",
                                },
                                "agent": {
                                    "type": "string",
                                    "enum": _coding_agent_ids() or None,
                                    "description": (
                                        "Coding agent for this group; omit to "
                                        "inherit the last pane's."
                                    ),
                                },
                            },
                            "required": ["count"],
                        },
                        "description": (
                            "Panes to open before briefing, group by group. "
                            "Only the newly opened panes are briefed, so agents "
                            "already working are not interrupted."
                        ),
                    },
                    "split": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Divide the instruction into one distinct assignment "
                            "per agent instead of giving all of them the same "
                            "brief."
                        ),
                    },
                    "force": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Leave this out. A spawn whose instruction recently "
                            "went to panes that are still open is refused as a "
                            "duplicate, and the refusal names the panes already "
                            "working on it — report those instead of retrying. "
                            "Set true ONLY when the user explicitly asked to run "
                            "the same task again on a fresh fleet."
                        ),
                    },
                },
                "required": ["instruction"],
            },
            ui_section="agentic-ide",
            voice_aliases={
                "de": (
                    "spawne ein terminal und lass es die tests fixen",  # i18n-allow
                ),
                "en": ("open a terminal and have it fix the tests",),
                "es": ("abre una terminal y que arregle las pruebas",),  # i18n-allow: input vocab
                "pt": (  # i18n-allow: input vocab
                    "abre um terminal e põe-no a corrigir os testes",  # i18n-allow: input vocab
                ),
            },
        ),
    )


def _part2() -> tuple[AppCommand, ...]:
    return (
        AppCommand(
            id="agentic-ide-spawn-terminals",
            title="Open more Agentic-IDE terminals",
            description=(
                "Open bare coding terminal panes in the open workspace, without work: only "
                "when the user asks for terminals ('open two more Codex terminals'). A new "
                "agent meant to do something is workspace-orchestrate create instead. Pass "
                "count, and agent only when the user named one; omitted, the panes run what "
                "the last pane runs. Call-signs (T1, T2, ...) are assigned by the workspace: "
                "address the panes by the reply's names. If 'capped' is true the workspace "
                "maximum cut the request short: say how many opened."
            ),
            method="POST",
            path="/api/agentic-ide/terminals/batch",
            params={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "default": 1,
                        "description": "How many terminals to open.",
                    },
                    "agent": {
                        "type": "string",
                        "enum": _coding_agent_ids() or None,
                        "description": (
                            "Coding agent for the new panes; omit to inherit "
                            "the last pane's."
                        ),
                    },
                },
                "required": ["count"],
            },
            ui_section="agentic-ide",
            voice_aliases={
                "de": ("spawne fünf neue terminals",),  # i18n-allow: input vocab
                "en": ("spawn five new claude code terminals",),
                "es": ("abre dos terminales de codex",),  # i18n-allow: input vocab
                "pt": ("abre dois terminais de codex",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="agentic-ide-rename-terminal",
            title="Rename an Agentic-IDE terminal",
            description=(
                "Rename one open terminal, keeping its agent and conversation ('rename T1 "
                "to Frontend'). The new name must be unique in the workspace."
            ),
            method="PATCH",
            path="/api/agentic-ide/terminals/{terminal}",
            params={
                "type": "object",
                "properties": {
                    "terminal": _str_param(
                        "Current call-sign of the terminal, e.g. 'T1'.",
                        min_length=1,
                    ),
                    "name": _str_param(
                        "New call-sign for the terminal, e.g. 'Frontend'.",
                        min_length=1,
                        max_length=40,
                    ),
                },
                "required": ["terminal", "name"],
            },
            path_params=("terminal",),
            ui_section="agentic-ide",
            voice_aliases={
                "de": ("benenne t1 in frontend um",),  # i18n-allow: input vocab
                "en": ("rename t1 to frontend",),
                "es": ("renombra t1 a frontend",),  # i18n-allow: input vocab
                "pt": ("muda o nome do t1 para frontend",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="agentic-ide-move-terminal",
            title="Move an Agentic-IDE terminal in the grid",
            description=(
                "Rearrange the grid: put one open terminal at another's place; nothing "
                "starts or stops ('swap Mika and Nova', 'move Mika under Nova'). swap "
                "exchanges the panes; left/right give the moved pane its own column beside "
                "the target; above/below stack it in the target's column."
            ),
            method="POST",
            path="/api/agentic-ide/terminals/{name}/move",
            params={
                "type": "object",
                "properties": {
                    "name": _str_param(
                        "Call-sign of the terminal to move, e.g. 'Mika'.",
                        min_length=1,
                    ),
                    "target": _str_param(
                        "Call-sign of the terminal it should move to, e.g. 'Nova'.",
                        min_length=1,
                    ),
                    "position": _str_param(
                        "Where it lands relative to the target.",
                        enum=["swap", "left", "right", "above", "below"],
                    ),
                },
                "required": ["name", "target"],
            },
            path_params=("name",),
            ui_section="agentic-ide",
            voice_aliases={
                "de": ("tausche mika und nova",),  # i18n-allow: input vocab
                "en": ("swap mika and nova",),
                "es": ("intercambia mika y nova",),  # i18n-allow: input vocab
                "pt": ("troca a mika e a nova",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="agentic-ide-close-agent-terminals",
            title="Close Agentic-IDE terminals by coding agent",
            description=(
                "Stop and remove every terminal of one coding CLI in the front "
                "workspace. Use only when the user explicitly asks to close all "
                "Claude Code or all Codex terminals; this is destructive and "
                "requires confirmation."
            ),
            method="DELETE",
            path="/api/agentic-ide/terminals/agent/{agent}",
            params={
                "type": "object",
                "properties": {
                    "agent": _str_param(
                        "Coding agent whose terminals should be closed.",
                        enum=_coding_agent_ids() or None,
                    ),
                },
                "required": ["agent"],
            },
            path_params=("agent",),
            dangerous=True,
            ui_section="agentic-ide",
            voice_aliases={
                "de": ("schließe alle codex terminals",),  # i18n-allow: input vocab
                "en": ("close all codex terminals",),
                "es": ("cierra todas las terminales de codex",),  # i18n-allow: input vocab
                "pt": ("fecha todos os terminais de codex",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="agentic-ide-focus",
            title="Toggle Agentic-IDE focus mode",
            description=(
                "Turn the focused coding mode on or off. While on, answers are "
                "given inside the open coding workspace; turning it off returns "
                "to normal behaviour without stopping any agent."
            ),
            method="PUT",
            path="/api/agentic-ide/mode",
            params={
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "True enters focused coding mode, False leaves it.",
                    },
                },
                "required": ["enabled"],
            },
            ui_section="agentic-ide",
            voice_aliases={
                "de": ("geh in den coding modus",),  # i18n-allow: input vocab
                "en": ("switch into coding mode",),
                "es": ("entra en el modo de programación",),  # i18n-allow: input vocab
                "pt": ("entra no modo de programação",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="agentic-ide-resume",
            title="Resume the last Agentic-IDE workspace",
            description=(
                "Reopen the last coding workspace: same folder, named terminals, grid "
                "positions and CLIs, continuing conversations where the CLI supports it. Use "
                "when the user wants their terminals back after a close or restart. Check "
                "the reply: 'resumable_count' continued, 'started_fresh' reopened empty; "
                "name the empty ones."
            ),
            method="POST",
            path="/api/agentic-ide/resume",
            ui_section="agentic-ide",
            voice_aliases={
                "de": ("stell meine terminals wieder her",),  # i18n-allow: input vocab
                "en": ("resume all my coding sessions",),
                "es": ("restaura mis terminales",),  # i18n-allow: input vocab
                "pt": ("retoma os meus terminais",),  # i18n-allow: input vocab
            },
        ),
    )


def build() -> tuple[AppCommand, ...]:
    return (_part1() + _part2())

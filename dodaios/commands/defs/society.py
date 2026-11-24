"""Command definitions: society.

Split mechanically out of ``dodaios.commands.registry._build_registry``; the order of
the assembled registry is pinned by tests/unit/commands/test_registry_snapshot.py.
"""
from __future__ import annotations

from dodaios.commands.registry import (
    _READINESS_RULE,
    AppCommand,
    _routine_ref_params,
    _routine_schedule_param,
    _services_param,
    _str_param,
)


def build() -> tuple[AppCommand, ...]:
    return (
        AppCommand(
            id="society-agent-catalog",
            title="Read available agent models",
            description=(
                "Read the live provider and model catalog for persistent society agents "
                "before a requested model change."
            ),
            method="GET", path="/api/agent-chat/catalog", ui_section="agents",
            params={"type": "object", "properties": {
                "surface": {"type": "string", "enum": ["society"], "default": "society"},
            }},
            voice_aliases={
                "de": ("welche modelle gibt es für meine agenten",),  # i18n-allow: input vocab
                "en": ("which models are available for my agents",),
                "es": ("qué modelos pueden usar mis agentes",),  # i18n-allow: input vocab
                "pt": ("que modelos podem os meus agentes usar",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="society-switch-agent-model",
            title="Change one team agent's model",
            description=(
                "Change one persistent agent's provider/model/effort only on user request. "
                "Use society-agent-catalog to select a supported model. Reuses the Agents "
                "UI model-switch endpoint and preserves the canonical chat. Report the "
                "returned stored state and whether reseated is confirmed."
            ),
            method="POST", path="/api/society/agents/{agent_id}/model",
            path_params=("agent_id",), ui_section="agents",
            params={"type": "object", "properties": {
                "agent_id": _str_param("Real agent id from society_status.", min_length=1),
                "provider": _str_param("Provider id from the live society catalog.", min_length=1),
                "model": _str_param("Model id offered for that provider."),
                "effort": _str_param("Supported reasoning effort."),
                "account_id": _str_param("Explicitly requested existing subscription account id."),
            }, "required": ["agent_id", "provider"]},
            voice_aliases={
                "de": ("wechsle das modell von Scout",),  # i18n-allow: input vocab
                "en": ("change Scout's model",),
                "es": ("cambia el modelo de Scout",),  # i18n-allow: input vocab
                "pt": ("muda o modelo do Scout",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="society-list-routines",
            title="List an agent's routines",
            description=(
                "List one agent's scheduled routines with ids, schedules, state and next run."
            ),
            method="GET", path="/api/society/agents/{agent_id}/routines",
            path_params=("agent_id",), ui_section="agents",
            params={"type": "object", "properties": {
                "agent_id": _str_param("Agent id or exact name.", min_length=1),
            }, "required": ["agent_id"]},
            voice_aliases={
                "de": ("welche routinen hat Scout",),  # i18n-allow: input vocab
                "en": ("which routines does Scout have",),
                "es": ("qué rutinas tiene Scout",),  # i18n-allow: input vocab
                "pt": ("que rotinas tem o Scout",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="society-check-readiness",
            title="Check that an agent's work can run",
            description=(
                "Check whether an agent and its routines can do their job right now: the "
                "services named are connected (plugins, CLIs), the websites have a stored "
                "login for this agent, and the model seat is usable. Call it before you "
                "tell the user a delegated or scheduled job is ready, and again after they "
                "connected or signed in. On 'blocked', call each blocker's fix tool."
            ),
            method="POST", path="/api/society/agents/{agent_id}/readiness",
            path_params=("agent_id",), ui_section="agents",
            params={"type": "object", "properties": {
                "agent_id": _str_param("Agent id or exact name.", min_length=1),
                "services": _services_param(),
            }, "required": ["agent_id", "services"]},
            voice_aliases={
                "de": ("kann Scout schon loslegen",),  # i18n-allow: input vocab
                "en": ("is Scout ready to run",),
                "es": ("puede Scout empezar ya",),  # i18n-allow: input vocab
                "pt": ("o Scout já pode começar",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="society-create-routine",
            title="Schedule a routine for an agent",
            description=(
                "The ONLY way to make an agent do something on a schedule (daily briefing, "
                "weekly report, every morning at 8). Never use create-skill for this. The "
                "prompt is the complete task the agent runs each time: sources, steps, "
                "output. For a routine that watches something, write into the prompt that "
                "the agent stays quiet while nothing changed and reports only a real change, "
                "a completion, a failure or something the user must do, unless the user "
                "asked for regular updates. Speak the returned next_run; on "
                "timezone_required ask the user. " + _READINESS_RULE
            ),
            # Not dangerous: the user ordered it, and a routine is paused or
            # deleted in one step (a second spoken yes was a live complaint).
            method="POST", path="/api/society/agents/{agent_id}/routines",
            path_params=("agent_id",), ui_section="agents",
            params={"type": "object", "properties": {
                "agent_id": _str_param("Agent id or exact name.", min_length=1),
                "title": _str_param("Short routine name.", min_length=1, max_length=200),
                "prompt": _str_param(
                    "Self-contained instructions for each run.", min_length=1, max_length=16_000,
                ),
                "schedule": _routine_schedule_param(),
                "announce_on_success": _str_param(
                    "Optional line Dodaios says when a run finishes.", max_length=500,
                ),
                "services": _services_param(),
            }, "required": ["agent_id", "title", "prompt", "schedule"]},
            voice_aliases={
                "de": ("gib mir jeden morgen um acht ein briefing",),  # i18n-allow: input vocab
                "en": ("give me a briefing every morning at eight",),
                "es": ("dame un resumen cada mañana a las ocho",),  # i18n-allow: input vocab
                "pt": ("dá-me um resumo todas as manhãs às oito",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="society-update-routine",
            title="Change an agent's routine",
            description=(
                "Change a routine's title, prompt or schedule. Send all three: read the "
                "current values with society-list-routines and change only what was asked."
            ),
            method="PATCH", path="/api/society/agents/{agent_id}/routines/{task_id}",
            path_params=("agent_id", "task_id"), ui_section="agents",
            params={"type": "object", "properties": {
                **_routine_ref_params(),
                "title": _str_param("Routine name.", min_length=1, max_length=200),
                "prompt": _str_param("Full instructions.", min_length=1, max_length=16_000),
                "schedule": _routine_schedule_param(examples=False),
            }, "required": ["agent_id", "task_id", "title", "prompt", "schedule"]},
            voice_aliases={
                "de": ("verschieb das briefing auf sieben uhr",),  # i18n-allow: input vocab
                "en": ("move the briefing to seven",),
                "es": ("mueve el resumen a las siete",),  # i18n-allow: input vocab
                "pt": ("passa o resumo para as sete",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="society-routine-operation",
            title="Pause, resume, delete or run a routine",
            description=(
                "Pause, resume, delete or run-now one agent routine on user request."
            ),
            method="POST",
            path="/api/society/agents/{agent_id}/routines/{task_id}/operation",
            path_params=("agent_id", "task_id"), ui_section="agents", dangerous=True,
            params={"type": "object", "properties": {
                **_routine_ref_params(),
                "operation": _str_param(
                    "What to do.", enum=["pause", "resume", "delete", "run"],
                ),
            }, "required": ["agent_id", "task_id", "operation"]},
            voice_aliases={
                "de": ("pausiere das morgenbriefing",),  # i18n-allow: input vocab
                "en": ("pause the morning briefing",),
                "es": ("pausa el resumen de la mañana",),  # i18n-allow: input vocab
                "pt": ("pausa o resumo da manhã",),  # i18n-allow: input vocab
            },
        ),
    )

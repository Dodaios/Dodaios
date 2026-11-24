"""Command Registry — ONE machine-readable catalog of user-facing app commands.

The registry is the single source of truth that lets every surface agree on
what a "command" is (the AP-4 anti-drift class):

- the brain's ``app-command`` router tool (pipeline voice/chat) exposes the
  catalog to the LLM as an enum-constrained schema,
- ``GET /api/commands`` serves it to the desktop UI (and, via the dynamic
  OpenAPI layer, to the ``jarvis`` CLI),
- ``scripts/ci/gen_commands_reference.py`` renders it into
  ``docs/commands-reference.md`` (drift-gated),
- Phase B wires the same catalog into the realtime engines' tool calling.

Every command maps to exactly ONE already-mounted, already-validated REST
endpoint — the registry never grows its own execution logic, so command
behavior can never drift from what the UI button for the same action does.
Parity tests (tests/unit/commands/) assert every entry's endpoint exists in
the live OpenAPI schema and every ``ui_section`` is a real sidebar section.

Latency & footprint: the catalog is plain in-process data built lazily on
first access (AP-26 — nothing here touches the boot critical path) and
measures a few KB.

To add a command: put it in the matching area module under
``dodaios/commands/defs/`` (order there is the registry order), then regenerate
the snapshot in tests/unit/commands/ and ``docs/commands-reference.md``.

Language note: ``voice_aliases`` values are speech-recognition INPUT
vocabulary (the English-only rule in AGENTS.md allows it) and therefore may be non-English;
every other string in this module is English.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from dodaios.i18n.locales import SUPPORTED_LOCALES

# The central language list (dodaios.i18n.locales, constants only); parity-
# tested against dodaios.brain.manager.SUPPORTED_REPLY_LANGUAGES.
REPLY_LANGUAGES: tuple[str, ...] = ("auto", *SUPPORTED_LOCALES)

VOICE_MODES: tuple[str, ...] = ("pipeline", "realtime")


@dataclass(frozen=True)
class AppCommand:
    """One user-facing app command, bound to exactly one REST endpoint."""

    id: str                    # stable kebab-case identifier
    title: str                 # short human-readable title (EN)
    description: str           # one-liner for the LLM schema + docs (EN)
    method: str                # HTTP method of the backing endpoint
    path: str                  # endpoint path, may contain {placeholders}
    params: dict[str, Any] = field(default_factory=dict)  # JSON schema (object)
    path_params: tuple[str, ...] = ()  # args substituted into the path
    dangerous: bool = False    # True → requires explicit confirmation
    worker_allowed: bool = False  # Explicit least-privilege Jarvis-Agent grant
    ui_section: str = "settings"  # sidebar section hosting the same action
    voice_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "method": self.method,
            "path": self.path,
            "params": self.params,
            "path_params": list(self.path_params),
            "dangerous": self.dangerous,
            "worker_allowed": self.worker_allowed,
            "ui_section": self.ui_section,
            "voice_aliases": {k: list(v) for k, v in self.voice_aliases.items()},
        }


def _provider_ids(tier: str, *, brain_switchable_only: bool = False) -> list[str]:
    """Provider ids for ``tier`` from the static catalog; [] when unavailable.

    Lazy import: the provider catalog is pure data, but this module must stay
    importable (docs generation, tests) without pulling the UI layer eagerly.
    """
    try:
        from dodaios.ui.web.provider_spec import PROVIDERS
    except Exception:  # pragma: no cover - defensive: registry must not crash
        return []
    ids = [
        p.id
        for p in PROVIDERS
        if p.tier == tier
        and (not brain_switchable_only or getattr(p, "brain_switchable", True))
    ]
    return sorted(ids)


def _coding_agent_ids() -> list[str]:
    """Coding CLIs a workspace pane can run, from the ONE agent registry.

    Never a literal list. A registered CLI that the voice schema does not know
    about is unreachable by voice while being fully supported everywhere else —
    the pane opens from the UI, resumes, accepts prompts, and is simply absent
    from the one surface that is supposed to drive it. Reading the registry is
    what lets a newly registered agent be spawned the day it lands, without a
    second table remembering to agree (the same rule §5 sets for providers:
    gate on the capability, never on a name someone typed twice).
    """
    try:
        from dodaios.workspace.agents import coding_agent_names
    except Exception:  # pragma: no cover - defensive: registry must not crash
        return []
    return sorted(coding_agent_names())


def _all_provider_ids() -> list[str]:
    try:
        from dodaios.ui.web.provider_spec import PROVIDERS
    except Exception:  # pragma: no cover - defensive
        return []
    return sorted(p.id for p in PROVIDERS)


def _str_param(description: str, *, enum: list[str] | None = None,
               min_length: int | None = None, max_length: int | None = None,
               ) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "description": description}
    if enum:
        schema["enum"] = enum
    if min_length is not None:
        schema["minLength"] = min_length
    if max_length is not None:
        schema["maxLength"] = max_length
    return schema


def _provider_switch_params(
    tier: str,
    *,
    brain_switchable_only: bool = False,
    allow_experimental_ack: bool = False,
) -> dict[str, Any]:
    enum = _provider_ids(tier, brain_switchable_only=brain_switchable_only)
    properties: dict[str, Any] = {
        "provider": _str_param(
            f"Target {tier} provider id.", enum=enum or None, min_length=1
        ),
        "persist": {
            "type": "boolean",
            "default": True,
            "description": "Persist the choice to jarvis.toml (survives restart).",
        },
    }
    if allow_experimental_ack:
        properties["accept_experimental"] = {
            "type": "boolean",
            "default": False,
            "description": "Explicitly acknowledge an experimental provider transport.",
        }
    return {
        "type": "object",
        "properties": properties,
        "required": ["provider"],
    }


def _str_list(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _ritual_properties() -> dict[str, Any]:
    """What a ritual is made of, for the commands that write or change one."""
    clock = "24-hour HH:MM, the user's clock"
    return {
        "name": _str_param("Short name, e.g. 'Good morning'.", min_length=1, max_length=60),
        "phrases": _str_list(
            "What the user says after the wake word (or types) to start it, in their "
            "language, without the wake word: 'Guten Morgen'. Up to five, each up to six words."
        ),
        "steps": {
            "type": "array",
            "description": "In order, each one sentence in the user's own words.",
            "items": {
                "type": "object",
                "properties": {
                    "when": _str_param(
                        "'now': done when the phrase is said (start music, open an app). "
                        "'ahead': gathered beforehand and kept back (news, pull requests, "
                        "calendar, mail).",
                        enum=["now", "ahead"],
                    ),
                    "text": _str_param("The step.", min_length=1, max_length=500),
                    "id": _str_param("When changing a ritual: the id of the step this replaces."),
                    "call": {
                        "type": "object",
                        "description": (
                            "Only for a 'now' step that is exactly ONE call of one of your "
                            "tools with fixed arguments: it is then made at once, without "
                            "you. Find the arguments out first. Leave out for a step that "
                            "needs judgment."
                        ),
                        "properties": {
                            "tool": _str_param("Tool name, without a server prefix."),
                            "args": {"type": "object", "description": "Its arguments."},
                            "says": _str_param(
                                "The call in a few plain words, user's language: "
                                "'YouTube Music: liked songs'.", max_length=160,
                            ),
                        },
                        "required": ["tool", "args", "says"],
                    },
                },
                "required": ["when", "text"],
            },
        },
        "window_from": _str_param(
            f"Optional. Start of the time of day the phrase starts it, {clock}. Outside it "
            "the phrase is an ordinary greeting."
        ),
        "window_to": _str_param(f"End of that window, {clock}. Needed with window_from."),
        "weekdays": {
            "type": "array", "items": {"type": "integer"},
            "description": "Optional. Days it may start on, Monday is 0; default every day.",
        },
        "once_per_day": {
            "type": "boolean",
            "description": "Default true: the phrase starts it only the first time on a day.",
        },
        "prepare_from": _str_param(
            f"Optional. When the 'ahead' steps start gathering, {clock}; default the start "
            "of the window, at most 12 hours before it opens."
        ),
    }


def _ritual_ref_param() -> dict[str, Any]:
    return _str_param("The ritual's id or its exact name.", min_length=1)


_RITUAL_GUIDE = (
    "A ritual is steps the user wrote beforehand and starts by SAYING a short phrase after "
    "the wake word, or typing it ('Good morning': music, news, pull requests). Use it, not "
    "a routine or skill, whenever something should happen when the user says something; a "
    "routine runs by the clock. "
)


def _services_param() -> dict[str, Any]:
    return _str_list(
        "Every service or website with an account that the work must reach to post, send "
        "or sign in, by name, e.g. ['x', 'reddit', 'gmail']. [] only when it needs none."
    )


_READINESS_RULE = (
    "Pass services. The result's readiness says whether the job can run: only status "
    "'ready' may be reported as ready or done. On 'blocked', call each blocker's fix tool "
    "in the same turn so its Connect or login card is shown, and tell the user it is set "
    "up but blocked until they connect or sign in. On 'unverified', call "
    "society-check-readiness with the services first."
)

def _routine_schedule_param(*, examples: bool = True) -> dict[str, Any]:
    if not examples:
        return {**_routine_schedule_param(), "description": "Same shape as in creation."}
    return {
        "type": "object",
        "description": (
            'When it runs. "every day at 8" = {"kind":"calendar","local_time":"08:00"}; '
            'weekdays add "days":["mon","tue","wed","thu","fri"]; '
            '"every 2 hours" = {"kind":"every","interval_seconds":7200}; '
            'once = {"kind":"at_time","iso_timestamp":"2026-10-01T08:00:00"}. '
            "timezone is filled from the user's device; pass it only when they name one."
        ),
        "properties": {
            "kind": {"type": "string", "enum": ["calendar", "cron", "every", "at_time"]},
            "local_time": {"type": "string", "description": "HH:MM on the user's clock."},
            "days": _str_list("Weekdays mon..sun; omit for every day."),
            "interval_seconds": {"type": "number", "minimum": 60},
            "expression": {"type": "string", "description": "Five-field cron."},
            "iso_timestamp": {"type": "string"},
            "timezone": {"type": "string", "description": "IANA zone, e.g. Europe/Berlin."},
        },
        "required": ["kind"],
    }


def _routine_ref_params() -> dict[str, Any]:
    return {
        "agent_id": _str_param("Agent id or exact name.", min_length=1),
        "task_id": _str_param("Routine id from society-list-routines.", min_length=1),
    }


def _build_registry() -> tuple[AppCommand, ...]:
    """Assemble the curated v1 command set (high-value commands first —
    the long tail stays reachable through the dynamic CLI ``api`` layer).

    The definitions live in ``dodaios/commands/defs/<area>.py`` (one module per
    command area, each exporting ``build()``); this only concatenates them in
    order. Imported here, not at module top, so importing the registry stays cheap
    and the area modules can import ``AppCommand`` and the schema helpers from it."""
    from dodaios.commands.defs import (
        agent_briefs,
        agentic_ide,
        designs,
        dictation,
        knowledge,
        marketplace,
        missions,
        providers,
        pull_requests,
        rituals,
        skills,
        society,
        system,
        voice_language,
    )

    return (
        *society.build(),
        *rituals.build(),
        *pull_requests.build(),
        *providers.build(),
        *voice_language.build(),
        *designs.build(),
        *knowledge.build(),
        *marketplace.build(),
        *dictation.build(),
        *system.build(),
        *missions.build(),
        *skills.build(),
        *agent_briefs.build(),
        *agentic_ide.build(),
    )


@lru_cache(maxsize=1)
def get_registry() -> tuple[AppCommand, ...]:
    """The command catalog — built lazily on first access, then cached."""
    return _build_registry()


def get_command(command_id: str) -> AppCommand | None:
    """Look up one command by id, or None."""
    for cmd in get_registry():
        if cmd.id == command_id:
            return cmd
    return None


def registry_as_dicts() -> list[dict[str, Any]]:
    """The catalog as plain dicts (route responses, docs generation)."""
    return [cmd.as_dict() for cmd in get_registry()]

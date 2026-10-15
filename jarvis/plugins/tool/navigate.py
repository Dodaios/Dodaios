"""``navigate`` — move the desktop UI to a sidebar section by voice/chat.

Router-tier, risk ``safe`` (pure UI navigation — no side effects beyond
switching the active screen). The brain calls it when the user asks to open or
show a section ("zeig die Socials", "open settings", "show the agents"). It
publishes a :class:`~jarvis.core.events.NavigateSidebar` event; the frontend
listener (``useWebSocket.ts``) switches the active section when ``section`` is a
known ``SectionId`` and otherwise no-ops gracefully.

A direct safe-gated UI action, never a spawn — it never enters a worker tool-set
(AP-5/AP-14). ``KNOWN`` mirrors the frontend ``SECTION_IDS`` (store/events.ts);
a parity test (tests/unit/plugins/tool/test_navigate.py) guards against drift.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.core.events import NavigateSidebar
from jarvis.core.protocols import ToolResult

# Canonical section ids — mirror of SECTION_IDS in
# jarvis/ui/web/frontend/src/store/events.ts (parity-tested).
KNOWN: frozenset[str] = frozenset(
    {
        "chats",
        # Today: the person's own task list.
        "today",
        "agents",
        "skills",
        "plugins",
        "docs",
        "mcps",
        "sessions",
        # Spend & Tokens.
        "costs",
        "clis",
        "cli-test-hub",
        "board",
        "languages",
        "profile",
        "memory",
        "apikeys",
        # Computers: the user's servers and local VMs, reached over SSH.
        "computers",
        "settings",
        "telephony",
        "telephony-setup",
        "socials",
        "taskbar",
        "feedback",
        "agent-instructions",
        # Appshots: the shortcut and destination for showing the front window.
        "appshots",
        "dictionary",
        "dictation",
        "voice-shortcuts",
        "voice-language",
        "voice-api-keys",
        "visualization",
        "agentic-ide",
        # The other two ids of the coding surface. They resolve to the same
        # workspace, and they were missing here while being valid SECTION_IDS —
        # which left the parity guard below red and made "open the terminal
        # grid" an unknown section to the brain.
        "agentic-ide-classic",
        "chat-workspace",
        # The marketplace, in the app: community plugins and skills in one
        # storefront.
        "marketplace",
        # My Pets: the desktop pet, its look, and the pets the user created.
        "pets",
        # Keyboard shortcuts: every shortcut in one place, with a key tester.
        "shortcuts",
    }
)

# Natural-language aliases (DE + EN) → canonical id. The router usually passes an
# id from the schema enum; this is the safety net for spoken labels/synonyms.
_ALIASES: dict[str, str] = {
    # Retired inspection links open the saved conversation archive.
    "run_inspector": "sessions",
    # Agentic IDE — the spoken forms people reach for. "agentic" is a mouthful
    # in every supported language, so the plain-words variants matter more here
    # than for sections whose label is already a common noun.
    "agentic ide": "agentic-ide",
    "agentic": "agentic-ide",
    "ide": "agentic-ide",
    "coding mode": "agentic-ide",
    "coding workspace": "agentic-ide",
    "codier-modus": "agentic-ide",  # i18n-allow: input vocab
    "programmier-modus": "agentic-ide",  # i18n-allow: input vocab
    "modo de programación": "agentic-ide",  # i18n-allow: input vocab
    "social": "socials",
    "social media": "socials",
    "soziale medien": "socials",
    "settings": "settings",
    "einstellungen": "settings",
    "config": "settings",
    "konfiguration": "settings",
    # The Agents section is the agent society (the island, the roster, the
    # cards). The retired "sub-agents" wording still lands there rather than
    # nowhere, and the society's own names are spoken forms too.
    "agents": "agents",
    "agenten": "agents",
    "sub-agents": "agents",
    "sub agents": "agents",
    "subagents": "agents",
    "subagenten": "agents",
    "society": "agents",
    "agent society": "agents",
    "agenten-gesellschaft": "agents",  # i18n-allow: input vocab
    "gesellschaft": "agents",  # i18n-allow: input vocab
    "my agents": "agents",
    "meine agenten": "agents",  # i18n-allow: input vocab
    "mis agentes": "agents",  # i18n-allow: input vocab
    "team": "agents",
    "island": "agents",
    "insel": "agents",  # i18n-allow: input vocab
    "isla": "agents",  # i18n-allow: input vocab
    # The Agentic IDE holds coding TERMINALS, not agents: the spoken forms
    # that say so land on the workspace, never on the society.
    "terminals": "agentic-ide",
    "coding terminals": "agentic-ide",
    "terminal grid": "agentic-ide",
    "coding clis": "agentic-ide",
    "chat": "chats",
    # The person's own task list. "aufgaben"/"tasks" keep landing on the
    # agents' routines below; these words are unambiguous.
    "heute": "today",  # i18n-allow: input vocab
    "todo": "today",
    "todos": "today",
    "to-do": "today",
    "to do": "today",
    "to-do list": "today",
    "todo list": "today",
    "aufgabenliste": "today",  # i18n-allow: input vocab
    "hoy": "today",  # i18n-allow: input vocab
    "skill": "skills",
    "fähigkeiten": "skills",
    "faehigkeiten": "skills",
    "plugin": "plugins",
    "documentation": "docs",
    "dokumentation": "docs",
    "dokumente": "docs",
    "doku": "docs",
    "mcp": "mcps",
    # The retired Automations section: scheduled work lives on agents now
    # (each agent's routines), so its old id and spoken names land there.
    "tasks": "agents",
    "task": "agents",
    "aufgaben": "agents",
    "aufgabe": "agents",
    "automations": "agents",
    "routines": "agents",
    "schedules": "agents",
    "transkription": "sessions",
    "transcription": "sessions",
    "session": "sessions",
    "cli": "clis",
    "kosten": "costs",  # i18n-allow: input vocab
    "kostenübersicht": "costs",  # i18n-allow: input vocab
    "verbrauch": "costs",  # i18n-allow: input vocab
    "token-kosten": "costs",  # i18n-allow: input vocab
    "token": "costs",
    "tokens": "costs",
    "spend": "costs",
    "spending": "costs",
    "billing": "costs",
    "costes": "costs",  # i18n-allow: input vocab
    "gastos": "costs",  # i18n-allow: input vocab
    "cli test hub": "cli-test-hub",
    "test hub": "cli-test-hub",
    "testhub": "cli-test-hub",
    "language": "languages",
    "sprache": "languages",
    "sprachen": "languages",
    "profil": "profile",
    "notes": "memory",
    "notizen": "memory",
    "notiz": "memory",
    "wiki": "memory",
    "computers": "computers",
    "servers": "computers",
    "vps": "computers",
    "virtual machines": "computers",
    "virtual machine": "computers",
    "vms": "computers",
    "virtuelle maschinen": "computers",  # i18n-allow: input vocab
    "ordenadores": "computers",  # i18n-allow: input vocab
    "servidores": "computers",  # i18n-allow: input vocab
    "api keys": "apikeys",
    "api-keys": "apikeys",
    "api key": "apikeys",
    "keys": "apikeys",
    "schlüssel": "apikeys",
    "telefonie": "telephony",
    "telefon": "telephony",
    "phone": "telephony",
    "telephony setup": "telephony-setup",
    "telefonie setup": "telephony-setup",
    "telefon setup": "telephony-setup",
    "telefonie einrichten": "telephony-setup",
    # The Outputs section folded into Artifacts (2026-08-23): every run is
    # listed there now, with or without a page. The old words still land.
    "outputs": "visualization",
    "output": "visualization",
    "ausgaben": "visualization",  # i18n-allow: input vocab
    "ergebnisse": "visualization",  # i18n-allow: input vocab
    "resultados": "visualization",  # i18n-allow: input vocab
    "appshot": "appshots",
    "app shots": "appshots",
    "app shot": "appshots",
    "task bar": "taskbar",
    "taskleiste": "taskbar",
    # The Artifacts section (section id kept as "visualization" — its 2026-08
    # name — because the id crosses the navigate parity test, the detachable
    # view registry and deep links). Spoken forms: the new name first.
    "artifacts": "visualization",
    "artifact": "visualization",
    "artefakte": "visualization",  # i18n-allow: input vocab
    "artefakt": "visualization",  # i18n-allow: input vocab
    "artefactos": "visualization",  # i18n-allow: input vocab
    "artefacto": "visualization",  # i18n-allow: input vocab
    "visualisation": "visualization",
    "visuals": "visualization",
    "charts": "visualization",
    "diagrams": "visualization",
    "visualisierung": "visualization",  # i18n-allow: input vocab
    "visualisierungen": "visualization",  # i18n-allow: input vocab
    "diagramme": "visualization",  # i18n-allow: input vocab
    "visualización": "visualization",  # i18n-allow: input vocab
    "visualizaciones": "visualization",  # i18n-allow: input vocab
    "gráficos": "visualization",  # i18n-allow: input vocab
    # "Extensions" is the merged sidebar entry fronting skills + plugins + clis
    # + mcps. The bare name lands on the Skills tab; "tools" lands on the Tools
    # tab (which defaults to Plugins). The underlying section ids are unchanged.
    "extensions": "skills",
    "erweiterungen": "skills",
    "erweiterung": "skills",
    "tools": "plugins",
    "werkzeuge": "plugins",
    # Voice section tabs. Deliberately NARROW, multi-word phrases only: the
    # brain-side matcher (jarvis/brain/navigation_intent.py) runs BEFORE the
    # capability gate, so a bare "voice" / "stimme" / "voz" alias would hijack
    # every utterance that merely mentions the voice.
    "dictation shortcuts": "voice-shortcuts",
    "dictation keys": "voice-shortcuts",
    "diktat-tastenkürzel": "voice-shortcuts",  # i18n-allow: input vocab
    "diktat-tasten": "voice-shortcuts",  # i18n-allow: input vocab
    "atajos de dictado": "voice-shortcuts",  # i18n-allow: input vocab
    # The Keyboard shortcuts page (Settings hub). The dictation-only words
    # above keep landing on the voice tab.
    "keyboard shortcuts": "shortcuts",
    "shortcuts": "shortcuts",
    "hotkeys": "shortcuts",
    "keybinds": "shortcuts",
    "key bindings": "shortcuts",
    "tastenkürzel": "shortcuts",  # i18n-allow: input vocab
    "tastenkombinationen": "shortcuts",  # i18n-allow: input vocab
    "atajos de teclado": "shortcuts",  # i18n-allow: input vocab
    "atajos": "shortcuts",  # i18n-allow: input vocab
    "dictation language": "voice-language",
    "diktat-sprache": "voice-language",  # i18n-allow: input vocab
    "idioma de dictado": "voice-language",  # i18n-allow: input vocab
    "voice input keys": "voice-api-keys",
    "spracheingabe-schlüssel": "voice-api-keys",  # i18n-allow: input vocab
    "claves de entrada de voz": "voice-api-keys",  # i18n-allow: input vocab
    # The marketplace. "store"/"shop" are the words people actually reach for,
    # and none of these names anything else in the app.
    "market": "marketplace",
    "market place": "marketplace",
    "store": "marketplace",
    "shop": "marketplace",
    "marktplatz": "marketplace",  # i18n-allow: input vocab
    "mercado": "marketplace",  # i18n-allow: input vocab
    "tienda": "marketplace",  # i18n-allow: input vocab
    # My Pets. Only phrases that name the app's own pet: the bare word "pets"
    # is already the section id, and anything broader ("animals") would pull
    # ordinary questions about animals onto a settings page.
    "my pets": "pets",
    "my pet": "pets",
    "desktop pet": "pets",
    "desktop pets": "pets",
    "haustier": "pets",  # i18n-allow: input vocab
    "meine pets": "pets",  # i18n-allow: input vocab
    "mein haustier": "pets",  # i18n-allow: input vocab
    "mis mascotas": "pets",  # i18n-allow: input vocab
    "mascota de escritorio": "pets",  # i18n-allow: input vocab
}


# phrase → canonical id, reused by the brain-side navigation-intent matcher
# (jarvis/brain/navigation_intent.py) so both share one section vocabulary.
SECTION_PHRASES: dict[str, str] = {**{s: s for s in KNOWN}, **_ALIASES}


def _resolve(raw: str) -> str | None:
    """Map a spoken section name/alias to a canonical id, or None if unknown."""
    s = " ".join((raw or "").strip().lower().split())
    if not s:
        return None
    if s in KNOWN:
        return s
    if s in _ALIASES:
        return _ALIASES[s]
    # tolerate hyphen/space spelling variants ("cli test hub" ↔ "cli-test-hub").
    hyphen = s.replace(" ", "-")
    if hyphen in KNOWN:
        return hyphen
    if hyphen in _ALIASES:
        return _ALIASES[hyphen]
    spaced = s.replace("-", " ")
    if spaced in _ALIASES:
        return _ALIASES[spaced]
    return None


log = logging.getLogger(__name__)

# What a target lookup answers: ``found`` with an id and a name, ``ask`` with
# the candidates that fit, ``unknown`` with what exists, or ``unavailable``.
Lookup = dict[str, Any]
#: How many conversations a title is matched against, newest first.
_CHAT_SEARCH_LIMIT = 200


def _find_agent(spoken: str) -> Lookup:
    """The named agent a spoken reference means, from the live roster."""
    try:
        from jarvis.society.agent_names import display_name, lookup_in
        from jarvis.society.runtime import current_runtime

        runtime = current_runtime()
        if runtime is None:
            return {"status": "unavailable"}
        found = lookup_in(runtime.roster.snapshot(), spoken, surface="navigate")
    except Exception:  # noqa: BLE001 - no agent team on this install: say so, do not crash
        log.warning("navigate: agent lookup failed", exc_info=True)
        return {"status": "unavailable"}
    if found.decision == "act" and found.agent is not None:
        return {"status": "found", "id": found.agent.agent_id, "name": display_name(found.agent)}
    if found.decision == "ask" and found.candidates:
        return {"status": "ask", "candidates": [display_name(a) for a in found.candidates]}
    return {"status": "unknown", "available": found.available_names()}


async def _find_chat(spoken: str) -> Lookup:
    """The conversation with this id or title among the assistant's own chats."""
    from jarvis.core.runtime_refs import get_web_app

    service = getattr(getattr(get_web_app(), "state", None), "agent_chat", None)
    store = getattr(service, "store", None)
    if store is None:
        return {"status": "unavailable"}
    sessions = await asyncio.to_thread(store.list_sessions, _CHAT_SEARCH_LIMIT, surface="jarvis")
    wanted = " ".join(spoken.split()).casefold()
    exact = [
        s for s in sessions
        if s.session_id == spoken.strip() or " ".join(s.title.split()).casefold() == wanted
    ]
    matches = exact or [s for s in sessions if wanted and wanted in s.title.casefold()]
    if len(matches) == 1 or exact:
        # Several chats can carry one title; the newest is the one meant.
        return {"status": "found", "id": matches[0].session_id, "name": matches[0].title}
    if matches:
        return {"status": "ask", "candidates": [s.title for s in matches[:8]]}
    return {"status": "unknown", "available": [s.title for s in sessions[:8] if s.title]}


async def _show_workspace(spoken: str) -> Lookup:
    """Bring a coding workspace on screen through the workspace service."""
    try:
        from jarvis.agentic_ide.orchestration import get_orchestrator

        result = await get_orchestrator().run({"action": "show", "workspace": spoken})
    except Exception:  # noqa: BLE001 - no coding surface on this install: say so
        log.warning("navigate: workspace lookup failed", exc_info=True)
        return {"status": "unavailable"}
    if result.get("status") == "shown":
        return {"status": "found", "id": "", "name": str(result.get("workspace") or spoken)}
    candidates = [
        str(item.get("name") or item.get("workspace") or "")
        for item in result.get("candidates") or []
        if isinstance(item, dict)
    ]
    return {
        "status": "ask" if candidates else "unknown",
        "candidates": candidates,
        "available": candidates,
        "reason": str(result.get("reason") or ""),
    }


class NavigateTool:
    """Switch the desktop app's active section, or open one thing inside it."""

    name: str = "navigate"
    risk_tier: str = "safe"
    description: str = (
        "Open/switch the desktop app to a sidebar section (the UI screen the user "
        "sees). Use when the user asks to show or open a section — 'zeig die "
        "Socials', 'open settings', 'show the agents', 'geh zu den Aufgaben'. Pass "
        "the section id in 'section'. To open one thing instead, pass exactly one of "
        "agent (a named agent's chat), chat (a conversation, by its title) or "
        "workspace (a coding workspace) and no section. Do NOT use it for anything "
        "other than moving the UI."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": sorted(KNOWN),
                "description": (
                    "The sidebar section id to open (e.g. 'socials', 'settings', 'agents')."
                ),
            },
            "agent": {
                "type": "string",
                "description": "A named agent: opens the chat with that agent.",
            },
            "chat": {
                "type": "string",
                "description": "A conversation's title (or id): opens that conversation.",
            },
            "workspace": {
                "type": "string",
                "description": "A coding workspace's name: brings it on screen.",
            },
        },
    }

    def __init__(
        self,
        bus: Any,
        *,
        find_agent: Callable[[str], Lookup] = _find_agent,
        find_chat: Callable[[str], Awaitable[Lookup]] = _find_chat,
        show_workspace: Callable[[str], Awaitable[Lookup]] = _show_workspace,
    ) -> None:
        self._bus = bus
        self._find_agent = find_agent
        self._find_chat = find_chat
        self._show_workspace = show_workspace

    @classmethod
    def known_sections(cls) -> set[str]:
        return set(KNOWN)

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        targets = {
            kind: " ".join(str(args.get(kind) or "").split())
            for kind in ("agent", "chat", "workspace")
        }
        named = {kind: value for kind, value in targets.items() if value}
        if len(named) > 1 or (named and str(args.get("section") or "").strip()):
            return ToolResult(
                success=False,
                output={"requested": dict(args)},
                error="Pass one destination: a section, or one of agent, chat, workspace.",
            )
        if named:
            kind, spoken = next(iter(named.items()))
            return await self._open(kind, spoken)
        section = _resolve(str(args.get("section", "")))
        if section is None:
            return ToolResult(
                success=False,
                output={"requested": args.get("section")},
                error=(
                    f"Unknown section {args.get('section')!r}. Valid sections: "
                    + ", ".join(sorted(KNOWN))
                ),
            )
        await self._bus.publish(
            NavigateSidebar(section=section, source_layer="brain.tool.navigate")
        )
        return ToolResult(
            success=True,
            output={"section": section, "summary": f"Opened the {section} section."},
        )

    async def _open(self, kind: str, spoken: str) -> ToolResult:
        """Resolve one named destination and move the UI to it, or say why not."""
        if kind == "agent":
            found = self._find_agent(spoken)
        elif kind == "chat":
            found = await self._find_chat(spoken)
        else:
            found = await self._show_workspace(spoken)
        status = found.get("status")
        if status != "found":
            if status == "ask":
                error = (
                    f"More than one {kind} fits {spoken!r}: "
                    + ", ".join(found.get("candidates") or [])
                    + ". Ask the user which one."
                )
            elif status == "unknown":
                known = ", ".join(found.get("available") or []) or "none"
                detail = f" {found['reason']}" if found.get("reason") else ""
                error = f"No {kind} is called {spoken!r}. Known: {known}.{detail}"
            else:
                error = f"This app cannot open a {kind} right now."
            return ToolResult(success=False, output={"requested": spoken, **found}, error=error)
        if kind == "workspace":
            # The workspace service already brought it on screen; show its section.
            event = NavigateSidebar(section="agentic-ide", source_layer="brain.tool.navigate")
        else:
            event = NavigateSidebar(
                section="chats", target=kind, target_id=str(found["id"]),
                source_layer="brain.tool.navigate",
            )
        await self._bus.publish(event)
        return ToolResult(
            success=True,
            output={
                "section": event.section, kind: found["name"],
                "summary": f"Opened the {kind} {found['name']}.",
            },
        )

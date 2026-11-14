"""Is a delegated or scheduled job able to run, or only set up?

An agent with a routine ("post on X every day at 16:30") can be created while
nothing it needs is reachable: the plugin is not connected, the website has no
stored login, the agent has no usable model seat. The creation used to answer
with the stored row alone, and the lead reported "done" for a job whose every
run would fail.

:func:`check_readiness` answers what a run needs and what is missing, from
facts the app already holds:

* services the caller names (``services``), and marketplace plugins the text
  of the job names by itself: a plugin or CLI has to be connected, any other
  service is a website and needs a login in the agent's vault;
* the agent's focus capabilities whose service is not connected;
* the model seat the run answers on (:mod:`.seat_preflight`, and the rules of
  :mod:`.routine_runner` that skip or fail a run before it starts).

Every missing piece comes back as a blocker with the tool call that opens its
card (``society_request_connect``, ``society_request_login``). An answer the
app cannot give (unknown connection state, no vault) is never a blocker.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable, Sequence
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = ["BLOCKED", "READY", "UNVERIFIED", "check_readiness"]

READY: Final[str] = "ready"
BLOCKED: Final[str] = "blocked"
#: Nothing found missing, but nobody said which services the job needs.
UNVERIFIED: Final[str] = "unverified"

_MAX_SERVICES: Final[int] = 12
#: A plugin name this short ("X") is matched in text by its exact spelling only.
_SHORT_NAME: Final[int] = 3
_SEAT_TIMEOUT_S: Final[float] = 8.0


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").casefold())


def _names(ident: str, display: str) -> list[str]:
    """The spellings of one service: "X (Twitter)" is "x", "X" and "Twitter"."""
    head, _, rest = str(display or "").partition("(")
    parts = [ident.replace("_", " "), display, head]
    parts += re.split(r"[&,/]| and ", rest.replace(")", " "))
    seen: dict[str, None] = {}
    for part in parts:
        part = " ".join(str(part).split())
        if part:
            seen.setdefault(part, None)
    return list(seen)


def _mentioned(text: str, name: str) -> bool:
    flags = 0 if len(name) < _SHORT_NAME else re.IGNORECASE
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text, flags) is not None


def _plugin_specs() -> list[Any]:
    try:
        from dodaios.marketplace.catalog_data import load_catalog

        return list(load_catalog().plugins)
    except Exception:  # noqa: BLE001 — without the catalog nothing is known to be missing
        log.warning("society readiness: marketplace catalog unavailable", exc_info=True)
        return []


def _cli_specs() -> list[Any]:
    try:
        from dodaios.clis.shared import get_active_registry

        registry = get_active_registry()
        return list(registry.catalog().all().values()) if registry is not None else []
    except Exception:  # noqa: BLE001 — without the catalog nothing is known to be missing
        log.warning("society readiness: CLI catalog unavailable", exc_info=True)
        return []


def _has_login(agent_id: str, name: str) -> bool | None:
    """Whether the agent's vault holds a login for the site; ``None`` = unknown."""
    from . import credentials

    vault = credentials.current_vault()
    if vault is None:
        return None
    try:
        return bool(vault.has_login(agent_id, credentials.login_key(name)))
    except credentials.CredentialError:  # not a site name: nothing to look up
        return None
    except Exception:  # noqa: BLE001 — an unreadable vault is unknown, not missing
        log.warning("society readiness: vault unreadable for %s", agent_id, exc_info=True)
        return None


def _connect_blocker(kind: str, target: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": target.id,
        "label": target.label,
        "missing": f"{target.label} is not connected",
        "fix": {"tool": "society_request_connect", "args": {"kind": kind, "id": target.id}},
    }


def _service_blocker(rt: Any, agent: Any, name: str) -> tuple[str, dict[str, Any] | None]:
    """``(label, blocker or None)`` for one named service."""
    from dodaios.agent_chat.credential_requests import CLI, PLUGIN

    from .connect_tool import resolve_target

    wanted = _norm(name)
    for kind, specs in ((PLUGIN, _plugin_specs()), (CLI, _cli_specs())):
        for spec in specs:
            ident = str(getattr(spec, "id", None) or getattr(spec, "name", "") or "")
            display = str(getattr(spec, "display_name", "") or ident)
            if wanted not in {_norm(n) for n in _names(ident, display)}:
                continue
            target = resolve_target(kind, ident)
            if target is None or target.connected is not False:
                return display, None
            if kind == PLUGIN and _has_login(agent.agent_id, name):
                return display, None  # it signs in through its browser instead
            return display, _connect_blocker(kind, target)
    try:
        rows = list(rt.catalog())
    except Exception:  # noqa: BLE001 — the catalog is one of several sources
        log.warning("society readiness: capability catalog unavailable", exc_info=True)
        rows = []
    for row in rows:
        spellings = {row.id.partition(":")[2], row.label, row.tool_name, *row.aliases}
        if wanted in {_norm(s) for s in spellings if s} and row.connected:
            return row.label, None  # a hand the agent already has
    if _has_login(agent.agent_id, name) is not False:
        return name, None
    return name, {
        "kind": "login",
        "site": name,
        "missing": f"no {name} login is stored for {agent.name}",
        "fix": {
            "tool": "society_request_login",
            "args": {"site": name, "agent": agent.agent_id},
        },
    }


def _named_in_text(rt: Any, texts: Iterable[str]) -> list[str]:
    """Unconnected marketplace plugins the job's own text names."""
    text = "\n".join(t for t in texts if t)
    if not text:
        return []
    try:
        open_ids = set(rt.unconnected_plugins())
    except Exception:  # noqa: BLE001 — unknown state names nothing
        log.warning("society readiness: plugin state unavailable", exc_info=True)
        return []
    found = []
    for spec in _plugin_specs():
        if spec.id not in open_ids:
            continue
        # A short id ("x") is a letter in running text; only its display spelling counts.
        ident = spec.id if len(spec.id) >= _SHORT_NAME else ""
        if any(_mentioned(text, n) for n in _names(ident, spec.display_name)):
            found.append(spec.id)
    return found


def _focus_blockers(rt: Any, agent: Any) -> list[dict[str, Any]]:
    try:
        rows = {row.id: row for row in rt.catalog()}
    except Exception:  # noqa: BLE001 — the catalog is one of several sources
        log.warning("society readiness: capability catalog unavailable", exc_info=True)
        return []
    found = []
    for cap in getattr(agent, "focus", None) or ():
        row = rows.get(cap)
        if row is None or row.connected:
            continue
        kind = str(row.kind)
        if kind not in ("plugin", "cli"):
            continue
        ident = cap.partition(":")[2]
        found.append(
            {
                "kind": kind,
                "id": ident,
                "label": row.label,
                "missing": f"{row.label} is not connected",
                "fix": {"tool": "society_request_connect", "args": {"kind": kind, "id": ident}},
            }
        )
    return found


async def _seat_blocker(rt: Any, agent: Any, task_id: str) -> dict[str, Any] | None:
    """Why a run of this agent could not start on its model seat, if it could not."""
    from dodaios.brain.background_policy import BackgroundDeferred

    from .routine_runner import _hold_unattended_run_off_keys, _seat_for_run
    from .seat_preflight import preflight_seat

    async def probe() -> str:
        provider, model, _effort, account_id = await _seat_for_run(rt, agent, task_id)
        if not provider:
            return ""  # no seat is named anywhere: nothing a check could refuse
        await _hold_unattended_run_off_keys(provider, account_id)
        problem = await preflight_seat(provider, model, account_id)
        return problem.text if problem is not None else ""

    try:
        # Creation answers a person or a turn: a slow provider probe reads as unknown.
        reason = await asyncio.wait_for(probe(), timeout=_SEAT_TIMEOUT_S)
    except (RuntimeError, BackgroundDeferred) as exc:  # the run's own refusal is the answer
        reason = str(exc)
    except Exception:  # noqa: BLE001 — an unknown answer is never a blocker
        log.debug("society readiness: seat check inconclusive", exc_info=True)
        return None
    if not reason:
        return None
    return {
        "kind": "seat",
        "label": "model seat",
        "missing": reason,
        "fix": {
            "tool": "society-switch-agent-model",
            "args": {"agent_id": agent.agent_id},
            "note": "Pick a model the user can run; society-agent-catalog lists them.",
        },
    }


def _instruction(agent: Any, blockers: Sequence[dict[str, Any]]) -> str:
    missing = "; ".join(str(b["missing"]) for b in blockers)
    return (
        f"NOT READY: {agent.name} is set up but cannot do this yet ({missing}). In this same "
        "turn call each blocker's fix tool so its card is on screen (a login card is asked "
        "with the agent given; a turn shows at most three cards, so open the rest on the "
        "next turn). Then tell the user in one or two sentences that it is set up but "
        "blocked until they connect or sign in, naming every missing service. Do not say it "
        "is done, ready or running, and do not announce a first run."
    )


async def check_readiness(
    rt: Any,
    agent: Any,
    *,
    services: Sequence[str] | None = None,
    texts: Iterable[str] = (),
    task_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """What a job of ``agent`` needs and what is missing right now.

    ``services`` are the accounts the caller says each run must reach; ``None``
    means nobody said, and a clean result is then only ``unverified``.
    ``task_ids`` are the routines whose own (pinned) model seat is checked;
    without one the agent's seat is.
    """
    named = [" ".join(str(s).split()) for s in services or () if str(s).strip()]
    named = named[:_MAX_SERVICES]
    named += [s for s in await asyncio.to_thread(_named_in_text, rt, list(texts))]
    checked: list[str] = []
    blockers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(blocker: dict[str, Any] | None) -> None:
        if blocker is None:
            return
        ident = blocker.get("id") or blocker.get("site") or blocker["missing"]
        key = (str(blocker["kind"]), _norm(ident))
        if key not in seen:
            seen.add(key)
            blockers.append(blocker)

    for name in named:
        try:
            label, blocker = await asyncio.to_thread(_service_blocker, rt, agent, name)
        except Exception:  # noqa: BLE001 — one unreadable service does not hide the others
            log.warning("society readiness: could not check %s", name, exc_info=True)
            continue
        if label not in checked:
            checked.append(label)
        add(blocker)
    for blocker in await asyncio.to_thread(_focus_blockers, rt, agent):
        add(blocker)
    for task_id in list(task_ids) or [""]:
        add(await _seat_blocker(rt, agent, task_id))
    checked.append("model seat")
    result: dict[str, Any] = {"checked": checked}
    if blockers:
        result["status"] = BLOCKED
        result["blockers"] = blockers
        result["instruction"] = _instruction(agent, blockers)
    elif services is None:
        result["status"] = UNVERIFIED
        result["instruction"] = (
            "No services were named, so accounts on websites were not checked. If a run "
            "has to post, send or sign in anywhere, call society-check-readiness with "
            "every such service before you tell the user it is ready."
        )
    else:
        result["status"] = READY
    return result

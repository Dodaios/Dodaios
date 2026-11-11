"""The status light: "N running, M need you" as one small, glanceable summary.

A pure fold over what the work board, the jobs ledger, the attention list and
the seat-health record already know. Nothing here reads a provider, speaks or
notifies: it only shapes rows for the app's top bar, where the person looks
when they choose to.

Each row carries a ``link`` the app follows when it is clicked: either an
agent chat card (``agent_id`` with an optional ``session_id`` / ``ref_id``) or
a ``section`` of the app (the Agentic IDE for a coding pane, the board for a
mission).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

#: Coding-agent states that mean a person has to act (see workspace status).
_PANE_NEEDS_YOU: Final[frozenset[str]] = frozenset({"needs_input", "needs_attention"})
_PANE_BUSY: Final[str] = "busy"
#: Missions that wait on the person rather than run.
_MISSION_NEEDS_YOU: Final[frozenset[str]] = frozenset({"WAITING_CAPACITY"})
#: Rows per list: the light is a glance, the board and the inbox hold the rest.
MAX_ROWS: Final[int] = 25
_TITLE_CHARS: Final[int] = 160


def _text(value: Any, limit: int = _TITLE_CHARS) -> str:
    return " ".join(str(value or "").split())[:limit]


def _from_board(
    board: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """(running, needs_you, mission ids) read from the compact board sections."""
    running: list[dict[str, Any]] = []
    needs: list[dict[str, Any]] = []
    missions: set[str] = set()
    coding = board.get("coding_agents")
    if isinstance(coding, Mapping):
        for workspace in coding.get("workspaces") or []:
            if not isinstance(workspace, Mapping):
                continue
            for agent in workspace.get("agents") or []:
                if not isinstance(agent, Mapping):
                    continue
                state = str(agent.get("state") or "")
                name = _text(agent.get("title") or agent.get("name") or agent.get("cli"), 80)
                where = _text(workspace.get("workspace"), 60)
                row = {
                    "kind": "pane",
                    "id": _text(agent.get("terminal_id"), 120),
                    "title": f"{name} ({where})" if where else name,
                    "link": {"section": "agentic-ide"},
                }
                if state in _PANE_NEEDS_YOU:
                    needs.append({**row, "state": state})
                elif state == _PANE_BUSY:
                    running.append({**row, "state": state})
    team = board.get("team")
    if isinstance(team, Mapping):
        for member in team.get("working") or []:
            if isinstance(member, Mapping):
                agent_id = _text(member.get("agent_id") or member.get("id"), 120)
                running.append(
                    {
                        "kind": "team",
                        "id": agent_id,
                        "title": _text(member.get("name") or agent_id, 80),
                        "state": "working",
                        "link": {"agent_id": agent_id} if agent_id else {"section": "agents"},
                    }
                )
    rows = board.get("missions")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        mission_id = _text(row.get("mission_id"), 120)
        missions.add(mission_id)
        item = {
            "kind": "mission",
            "id": mission_id,
            "title": _text(row.get("request")) or mission_id,
            "state": str(row.get("state") or ""),
            "link": {"section": "board"},
        }
        (needs if item["state"] in _MISSION_NEEDS_YOU else running).append(item)
    tasks = board.get("tasks")
    for row in tasks if isinstance(tasks, list) else []:
        if isinstance(row, Mapping):
            running.append(
                {
                    "kind": "task",
                    "id": _text(row.get("task_id"), 120),
                    "title": _text(row.get("title")),
                    "state": str(row.get("state") or "running"),
                    "link": {"section": "agents"},
                }
            )
    return running, needs, missions


def build_status_light(
    *,
    board: Mapping[str, Any] | None = None,
    jobs: Iterable[Any] = (),
    attention: Iterable[Mapping[str, Any]] = (),
    seats: Iterable[Any] = (),
    findings: Iterable[Mapping[str, Any]] = (),
    prepared: Iterable[Mapping[str, Any]] = (),
    browsers: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Fold the sources into ``{running, needs_you, trouble, counts, tone}``.

    ``jobs`` are open ledger jobs; one that a board mission already shows (same
    ``ref``) is not listed twice. ``attention`` is the per-agent cards list.
    ``seats`` are :class:`~dodaios.brain.seat_health.SeatVerdict` values.
    ``findings`` are the watchdog's open findings (``key``, ``kind``, ``title``).
    ``prepared`` are drafts and fixes made in advance that wait for the person; they are
    counted and listed apart from "needs you" and never raise the tone.
    ``browsers`` are the agents' live browsers (``agent_id``, ``running``,
    ``request_id``, ``reason``): a task running in one is a running row, an open
    takeover request is a needs-you row; both open that agent's browser view.
    """
    running, board_needs, mission_ids = _from_board(board or {})
    for job in jobs:
        if str(getattr(job, "ref", "") or "") in mission_ids:
            continue
        running.append(
            {
                "kind": "job",
                "id": job.id,
                "title": _text(job.title) or job.kind,
                "state": job.state,
                "link": {"section": "agents"},
            }
        )
    needs_you = [
        {
            "kind": str(card.get("kind") or ""),
            "id": str(card.get("ref_id") or ""),
            "title": _text(card.get("summary")),
            "state": "waiting",
            "since_ms": int(card.get("since_ms") or 0),
            "link": {
                "agent_id": str(card.get("agent_id") or ""),
                "session_id": str(card.get("session_id") or ""),
                "ref_id": str(card.get("ref_id") or ""),
            },
        }
        for card in attention
    ] + board_needs
    for browser in browsers:
        link = {"agent_id": str(browser.get("agent_id") or "")}
        if browser.get("request_id"):
            needs_you.append(
                {
                    "kind": "browser_takeover",
                    "id": str(browser["request_id"]),
                    "title": _text(browser.get("reason")),
                    "state": "waiting",
                    "link": link,
                }
            )
        elif browser.get("running"):
            running.append(
                {
                    "kind": "browser",
                    "id": link["agent_id"],
                    "title": _text(browser.get("title")),
                    "state": "working",
                    "link": link,
                }
            )
    trouble = [
        {
            "provider": seat.provider,
            "account": seat.account,
            "class": seat.cls,
            "reason": seat.reason(),
            "blocked": bool(seat.blocked),
        }
        for seat in seats
    ]
    stuck = [
        {
            "id": _text(f.get("key"), 120),
            "kind": _text(f.get("kind"), 60),
            "title": _text(f.get("title")),
        }
        for f in findings
    ]
    waiting = [
        {
            "id": _text(p.get("id"), 120),
            "kind": _text(p.get("kind"), 60),
            "title": _text(p.get("title")),
            "thread_key": _text(p.get("thread_key"), 200),
            "link": {"section": "agents"},
        }
        for p in prepared
    ]
    return {
        "counts": {
            "running": len(running),
            "needs_you": len(needs_you),
            "prepared": len(waiting),
        },
        "running": running[:MAX_ROWS],
        "needs_you": needs_you[:MAX_ROWS],
        "trouble": trouble[:MAX_ROWS],
        "findings": stuck[:MAX_ROWS],
        "prepared": waiting[:MAX_ROWS],
        "tone": "warn" if trouble or stuck else "calm",
    }

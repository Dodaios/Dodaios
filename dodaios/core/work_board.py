"""The one board of running work: how each source's listing reads on it.

Shared by the voice ``task_status`` and the ``work_board`` tool every typed
lead seat has, so both show the same rows from the same sources.
"""

from __future__ import annotations

from typing import Any

# Where the user's running work outside one conversation is read, by section:
# the catalog tool that knows it and the arguments for its compact listing.
BOARD_SOURCES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("coding_agents", "workspace-orchestrate", {"action": "status"}),
    ("missions", "missions-list", {"active": True, "limit": 20}),
    ("team", "society_status", {"board": True}),
)
# Read by the typed lead's board only: scheduled and running routines.
TASK_SOURCE: tuple[str, str, dict[str, Any]] = (
    "tasks",
    "tasks-list",
    {"state": "running", "limit": 20},
)
# Agent states a person has to act on, or that mean work is in flight.
_QUIET_AGENT_STATES = frozenset({"idle", "empty"})
_REQUEST_CHARS = 200


def board_section(section: str, output: Any) -> Any:
    """One source's listing as the board shows it; None when it has another shape."""
    if section == "coding_agents":
        if not isinstance(output, dict) or output.get("status") != "ok":
            return None
        return {key: output[key] for key in ("counts", "needs_you", "workspaces") if key in output}
    if section in ("missions", "tasks"):
        response = output.get("response") if isinstance(output, dict) else None
        rows = response.get(section) if isinstance(response, dict) else None
        if not isinstance(rows, list):
            return None
        if section == "tasks":
            return [
                {"task_id": row.get("id"), "title": row.get("title"), "state": row.get("state")}
                for row in rows
                if isinstance(row, dict)
            ]
        return [
            {"mission_id": row.get("id"), "state": row.get("state"), "request": row.get("prompt")}
            for row in rows
            if isinstance(row, dict)
        ]
    if section == "team":
        agents = output.get("agents") if isinstance(output, dict) else None
        return agents if isinstance(agents, list) else None
    return None


def compact_section(section: str, rows: Any) -> Any:
    """The summary-first reading of a board section.

    Coding workspaces keep their git state but list only the agents that are
    busy or need the user; the team lists only agents that are working;
    request text is clipped. Counts say what was left out.
    """
    if section == "coding_agents" and isinstance(rows, dict):
        workspaces = []
        for workspace in rows.get("workspaces") or []:
            if not isinstance(workspace, dict):
                continue
            agents = [a for a in workspace.get("agents") or [] if isinstance(a, dict)]
            active = [a for a in agents if str(a.get("state")) not in _QUIET_AGENT_STATES]
            row = {k: v for k, v in workspace.items() if k != "agents"}
            row["agents"] = active
            if len(agents) > len(active):
                row["idle_agents"] = len(agents) - len(active)
            workspaces.append(row)
        return {**rows, "workspaces": workspaces}
    if section == "team" and isinstance(rows, list):
        working = [r for r in rows if isinstance(r, dict) and r.get("state") == "working"]
        return {"working": working, "idle": len(rows) - len(working)}
    if section in ("missions", "tasks") and isinstance(rows, list):
        return [_clip(row) for row in rows]
    return rows


def _clip(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    return {
        key: (value[:_REQUEST_CHARS] if key in ("request", "title") and isinstance(value, str)
              else value)
        for key, value in row.items()
    }

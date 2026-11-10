"""The plan behind the one-click "Use a free local model" button.

The first-run conversation, the setup window and the model picker offer one
button that makes a local model answer without any settings page. The button
needs a single answer before it starts: which model, for THIS machine, and
what is still missing (the Ollama runtime, the server process, the download).

That answer is assembled here from parts that already exist and are already
tested, so the button and the Local models section can never disagree:

* the hardware probes and the curated shortlist (:mod:`ollama_pull`),
* the installed-first chat pick (:func:`ollama_roles.list_roles`) — a user
  who already has a model on disk is not sent to download another one,
* the runtime picture (:func:`ollama_runtime.runtime_status`) — not
  installed, installed but stopped, starting, or running.

Doing the steps (install, start, pull, select) stays with the existing
routes; the frontend drives them one by one and re-reads this plan once the
server answers, because only then can the installed models be seen.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from dodaios.brain import ollama_pull, ollama_roles, ollama_runtime
from dodaios.brain.ollama_inventory import same_model

log = logging.getLogger(__name__)

__all__ = ["quickstart_plan", "hardware_sentence"]


def hardware_sentence(memory_gb: float | None, accelerator_gb: float) -> str:
    """One English line naming the memory the pick was judged against."""
    parts: list[str] = []
    if accelerator_gb > 0:
        parts.append(f"{accelerator_gb:.0f} GB graphics memory")
    if memory_gb is not None:
        parts.append(f"{memory_gb:.0f} GB RAM")
    if not parts:
        return "This computer's memory could not be read."
    return "This computer: " + ", ".join(parts) + "."


def _shortlist_row(rows: list[dict[str, Any]], model: str) -> dict[str, Any] | None:
    return next((r for r in rows if same_model(str(r.get("id", "")), model)), None)


async def quickstart_plan(cfg: Any) -> dict[str, Any]:
    """The model the one-click button would use here, and what is missing.

    Never raises for an unreachable server or a failed probe: a fresh machine
    without Ollama is the main audience, so "not installed" is a normal
    answer, and the pick then comes from the shortlist alone.
    """
    recommended, runtime = await asyncio.gather(
        ollama_pull.recommendations(),
        asyncio.to_thread(ollama_runtime.runtime_status),
    )
    rows: list[dict[str, Any]] = list(recommended.get("models") or [])
    installed_names = {str(n) for n in recommended.get("installed") or []}
    machine = ollama_roles.machine_from(recommended)

    model, reason = "", ""
    try:
        states, _error = await ollama_roles.list_roles(
            ollama_pull.server_root(), cfg, shortlist=rows, machine=machine
        )
        chat = next((s for s in states if s.spec.id == "chat"), None)
        if chat is not None:
            model, reason = chat.recommended, chat.recommended_reason
    except Exception:  # noqa: BLE001 — the shortlist below still gives an answer
        log.info("ollama-quickstart: role pick unavailable", exc_info=True)

    if not model:
        pick = next(
            (r for r in rows if "chat" in (r.get("recommended_for") or [])),
            next((r for r in rows if r.get("role") == "chat"), None),
        )
        if pick is not None:
            model = str(pick["id"])
            reason = "The best download for this computer."

    row = _shortlist_row(rows, model) if model else None
    installed = bool(model) and any(same_model(model, name) for name in installed_names)
    memory_gb = recommended.get("memory_gb")
    accel_gb = float(recommended.get("accelerator_gb") or 0.0)

    return {
        "model": model,
        "label": str(row.get("label")) if row else model,
        "size_gb": float(row["size_gb"]) if row and row.get("size_gb") is not None else None,
        "installed": installed,
        "fit": str(row.get("fit")) if row else ("comfortable" if installed else "unknown"),
        "fit_note": str(row.get("fit_note")) if row else "",
        "reason": reason,
        "hardware": {
            "memory_gb": memory_gb,
            "accelerator_gb": accel_gb,
            "accelerator_source": recommended.get("accelerator_source") or "none",
            "summary": hardware_sentence(
                memory_gb if isinstance(memory_gb, (int, float)) else None, accel_gb
            ),
        },
        "runtime": {
            "installed": bool(runtime.get("installed")),
            "running": bool(runtime.get("running")),
            "starting": bool(runtime.get("starting")),
            "host_kind": str(runtime.get("host_kind") or "local"),
            "detail": str(runtime.get("detail") or ""),
        },
        "server_reachable": bool(recommended.get("server_reachable")),
    }

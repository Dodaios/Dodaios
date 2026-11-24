"""What the app shows about the assistant improving itself: one read-only summary.

Everything here is read from what the kernel recorded (``bench.db``, the
self-change registry, the parameter store). Nothing is computed for display
only, and nothing is changed: the page shows the same numbers the gate acted
on.

The shape is the contract of ``GET /api/self-improvement``. Sentences are not
built here. The page gets numbers and names and words them in the person's
language; the only English texts are the reasons the kernel stored with its
evidence (shown as they are, in the details).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import dodaios
from dodaios.rsi import params
from dodaios.rsi.bench import run
from dodaios.rsi.bench.model import Source, Split
from dodaios.rsi.night import (
    BUDGET_SHARE,
    EVERY_S,
    IDLE_AFTER_S,
    MAX_MODEL_CALLS,
    RAMP_MODEL_CALLS,
    Night,
    calls_tonight,
)
from dodaios.self_change import Surface
from dodaios.self_change.store import Change

__all__ = ["build", "daily_use"]

log = logging.getLogger(__name__)

_NIGHTS = 14
_SERIES = 400
#: Weeks of daily use shown.
_WEEKS = 8
#: The weekly score reads the whole chat record: at most once in this long.
_DAILY_TTL_S = 600.0
_daily_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def daily_use(chat_db: Path | None, *, now: float | None = None) -> dict[str, Any] | None:
    """How the person's own requests went, week by week (``dodaios.evals.agent_score``).

    This is what happened, not a measurement of cause: the requests of one week
    are not the requests of the next. It stands beside the benchmark, which
    compares like with like, and never decides anything. ``None`` when there is
    no chat record, it cannot be read, or it holds no request in these weeks.
    """
    if chat_db is None or not Path(chat_db).is_file():
        return None
    stamp = time.time() if now is None else now
    key = str(chat_db)
    cached = _daily_cache.get(key)
    if cached is not None and stamp - cached[0] < _DAILY_TTL_S:
        return cached[1]
    found: dict[str, Any] | None = None
    try:
        from dodaios.evals.agent_score import build_report

        since = int((stamp - _WEEKS * 7 * 86400) * 1000)
        report = build_report(Path(chat_db), None, None, since_ms=since)
        weeks = [
            {
                "start_ms": int(window["start_ms"]),
                "turns": int(window["turns"]),
                "rated": bool(window.get("rated")),
                "score": window.get("upsilon") if window.get("rated") else None,
            }
            for window in report.get("windows") or []
        ]
        lifetime = report.get("lifetime") or {}
        turns = int(report.get("turns") or 0)
        # No request in these weeks (or a record that holds none): nothing to show.
        if turns:
            found = {
                "weeks": weeks[-_WEEKS:],
                "turns": turns,
                "score": lifetime.get("score"),
            }
    except Exception:  # noqa: BLE001 — the page shows the benchmark without this part
        log.info("self-improvement: the score of daily use could not be read", exc_info=True)
    _daily_cache[key] = (stamp, found)
    return found


def _value(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text).get("value")
    except (ValueError, AttributeError):  # shown as "unknown" rather than failing the page
        return None


def _measurement(row: dict[str, Any]) -> dict[str, Any]:
    """One stored piece of evidence, flattened for the page."""
    found = row["evidence"]
    target = found.get("target") or {}
    out = {
        "ts_ms": row["ts_ms"],
        "step": row["step"],
        "verdict": row["verdict"],
        "split": found.get("split") or "",
        "reason": found.get("reason") or "",
        "domain": target.get("domain") or "",
        "diff": target.get("diff"),
        "low": target.get("low"),
        "high": target.get("high"),
        "n": target.get("n") or 0,
        "cost_diff": target.get("cost_diff"),
    }
    if "metric" in target:
        # A coding policy's trial (dodaios/rsi/trainer.py): requests, not tasks,
        # the metric it claimed, the other arm, and each arm's plain means.
        out["metric"] = target.get("metric") or ""
        out["n_reference"] = target.get("n_reference") or 0
        out["arms"] = found.get("arms")
    return out


def _policy_value(text: str | None) -> dict[str, Any] | None:
    """A coding policy as the page reads it; ``None`` for a text that is not one."""
    from dodaios.rsi.policy import Policy, PolicyError

    try:
        policy = Policy.from_text(text)
    except PolicyError:  # shown without values rather than failing the page
        return None
    return {
        "hold": policy.hold,
        "p_max": policy.p_max,
        "evidence_wait_s": policy.evidence_wait_s,
        "lines": [line for line in policy.domain_block.splitlines() if line.strip()],
    }


def _policy_kinds(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """What a policy change does, in the page's closed set of words."""
    kinds: list[str] = []
    if after["hold"] and not before["hold"]:
        kinds.append("hold")
    elif before["hold"] and not after["hold"]:
        kinds.append("release")
    elif after["hold"]:
        if after["p_max"] < before["p_max"]:
            kinds.append("fewer_fixes")
        if after["evidence_wait_s"] < before["evidence_wait_s"]:
            kinds.append("shorter_wait")
    if any(line not in before["lines"] for line in after["lines"]):
        kinds.append("brief_line")
    return kinds


def _policy(change: Change, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """The fields of a coding policy row: the cell, what changed, against what.

    A candidate is compared with the active policy it went on trial against,
    and an accepted policy with the one it was measured against (both kept in
    the trainer's evidence); a change without that evidence with the text it
    replaced.
    """
    cell, _, slot = change.target.rpartition("#")
    domain, model, harness = ([*cell.split("|", 2), "", ""])[:3]
    claim, reference = None, None
    for row in evidence:
        found = row.get("evidence") or {}
        claim = claim or found.get("claim")
        reference = reference or found.get("reference")
    before = _policy_value(reference if reference is not None else change.before)
    after = _policy_value(change.after)
    added = [
        line
        for line in (after or {}).get("lines", [])
        if line not in (before or {}).get("lines", [])
    ]
    return {
        "before": before,
        "after": after,
        "policy": {
            "cell": cell,
            "slot": slot,
            "domain": domain,
            "model": model,
            "harness": harness,
            "kinds": _policy_kinds(before, after) if before and after else [],
            "lines": added,
            "claim": claim,
        },
    }


def _note_text(change: Change) -> str:
    """The words of a note the assistant wrote for itself, read from the memory right now.

    The registry holds no text of it, so a note the person forgot is gone here too.
    """
    from dodaios.rsi import adopt

    found = adopt.memory_id(change)
    if not found:
        return ""
    try:
        from dodaios.memory.vault import runtime as vault_runtime

        vault = vault_runtime.active()
        memory = vault.get(found) if vault is not None else None
    except Exception:  # noqa: BLE001 — the list shows the entry without its words
        log.info("self-improvement: a note's text could not be read", exc_info=True)
        return ""
    return memory.text if memory is not None else ""


def _change(night: Night, change: Change) -> dict[str, Any]:
    store = params.installed()
    index = store.index if store is not None else params.INDEX
    param = index.get(change.target) if change.surface is Surface.PARAMETER else None
    stored = night.registry.store.evidence(change.id)
    evidence = [_measurement(row) for row in stored]
    admit = next((e for e in evidence if e["step"] == "admit"), None)
    checks = [e for e in evidence if e["step"] == "settle"]
    row = {
        "id": change.id,
        "surface": change.surface.value,
        "target": change.target,
        "state": change.state.value,
        "author": change.author,
        "reason": change.reason,
        "text": _note_text(change),
        "measured": bool(evidence),
        "since_ms": night.registry.store.applied_ms(change.id) or change.created_ms,
        "before": _value(change.before),
        "after": _value(change.after),
        "default": param.default if param is not None else None,
        "doc": param.doc if param is not None else "",
        "admitted": admit,
        "last_check": checks[-1] if checks else None,
    }
    if change.surface is Surface.CODING_POLICY:
        row.update(_policy(change, stored))
    return row


def _policies(changes: list[Change]) -> tuple[set[str], list[Change]]:
    """Which coding policy changes the page lists, and the candidates on trial among them.

    The trainer writes a cell's active policy and its candidate as two
    targets. Only the newest change in effect on a target is what runs; an
    older one was replaced and a removal (a trial that ended) is no policy.
    Returns the ids to leave out of the list of learned changes, and the
    candidates on trial (a canary on half the requests, not learned yet).
    """
    newest: dict[str, Change] = {}
    for change in changes:
        if change.surface is not Surface.CODING_POLICY:
            continue
        seen = newest.get(change.target)
        if seen is None or change.seq > seen.seq:
            newest[change.target] = change
    shown = {c.id for c in newest.values() if c.after is not None and c.target.endswith("#active")}
    trials = [c for c in newest.values() if c.after is not None and c.target.endswith("#candidate")]
    hidden = {c.id for c in changes if c.surface is Surface.CODING_POLICY and c.id not in shown}
    return hidden, sorted(trials, key=lambda c: c.seq)


def _domains(night: Night) -> list[dict[str, Any]]:
    counts = night.bench.counts()
    latest: dict[str, dict[str, Any]] = {}
    for point in night.bench.series(split=Split.SEALED.value, limit=_SERIES):
        latest[point["domain"]] = point
    out: list[dict[str, Any]] = []
    for domain in run.runnable():
        own = {split.value: len(night.gate.tasks(domain, split)) for split in Split}
        out.append(
            {
                "domain": domain.value,
                "tasks": own,
                "tasks_total": sum(own.values()),
                "all_tasks": counts.get(domain.value, {}),
                "measured": domain.value in latest,
                "point": latest.get(domain.value),
            }
        )
    return out


def build(
    night: Night, *, now_ms: int | None = None, chat_db: Path | None = None
) -> dict[str, Any]:
    """The summary for one installation."""
    registry = night.registry
    last = night.last_ms()
    store = params.installed()
    resting = [e.public() for e in store.entries() if e.status != "live"] if store else []
    nights = night.bench.nights(_NIGHTS)
    learned = registry.learned()
    hidden, trials = _policies(learned)
    return {
        "status": {
            "app": dodaios.__version__,
            "paused": night.paused(),
            "readonly": night.bench.readonly,
            "last_night_ms": last,
            "next_night_ms": last + int(EVERY_S * 1000) if last else 0,
            "decides_on": [s.value for s in night.sources],
            "own_tasks": any(s is not Source.SEED for s in night.sources),
        },
        "limits": {
            "idle_after_s": IDLE_AFTER_S,
            "every_s": EVERY_S,
            "budget_share": BUDGET_SHARE,
            "max_model_calls": MAX_MODEL_CALLS,
            #: While too few tasks exist to decide on, a night may build with this many.
            "ramp_model_calls": RAMP_MODEL_CALLS,
            #: What the next night may use.
            "model_calls_tonight": calls_tonight(night.bench),
        },
        "domains": _domains(night),
        "series": night.bench.series(split=Split.SEALED.value, limit=_SERIES),
        "stack": [
            _change(night, change) for change in reversed(learned) if change.id not in hidden
        ],
        "candidates": [_change(night, change) for change in [*registry.candidates(), *trials]],
        "nights": nights,
        "resting": resting,
        "daily_use": daily_use(chat_db),
        "now_ms": now_ms if now_ms is not None else int(time.time() * 1000),
    }

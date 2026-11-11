"""The causal trace tree: which turn started which work, and where the time and cost went.

Every unit of orchestrated work is a node with a ``span_id`` and the
``parent_span_id`` of whatever caused it:

    lead turn -> assignment (society ASSIGN) -> agent turn -> mission / artifact job -> ...

Two stores hold the nodes, and this module joins them (no new heavy dependency):

* ``spans`` (``traces.db``, SQLite): one row per chat turn, written when the turn
  starts and closed from its ``turn_finished`` event (status, seat, cost, tokens);
* the jobs ledger (:mod:`dodaios.orchestrator.jobs`): one row per hand-off
  (assignment, mission, artifact, pane prompt, team thread), which now carries its
  own ``span_id`` / ``parent_span_id`` / ``root_span_id`` columns.

The parent of a node is always read from trusted state, never from a tool
argument: the chat turn in flight (``current_chat_turn``), or the span a vendor
CLI's MCP call names in the harness header, which the MCP route validates.

An assignment's span id is the ASSIGN event id; the agent turn it starts names it
as its parent (the delivery already carries the event id as the incoming message
id), so the chain closes without a lookup table.

Every write here is best effort for the caller: a trace problem never fails the
work it describes. Reads are bounded (``MAX_NODES``) and summary-first.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

#: Nodes one tree read returns; a longer tree says so (``truncated``).
MAX_NODES: Final[int] = 500
MAX_ROOTS: Final[int] = 200
_TITLE_MAX: Final[int] = 160
_RECEIPTS_MAX: Final[int] = 10

#: What the harness header may carry. Turn ids, event ids and job ids all fit.
SPAN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    span_id        TEXT PRIMARY KEY,
    parent_span_id TEXT NOT NULL DEFAULT '',
    root_span_id   TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'turn',
    origin         TEXT NOT NULL DEFAULT '',
    session_id     TEXT NOT NULL DEFAULT '',
    title          TEXT NOT NULL DEFAULT '',
    provider       TEXT NOT NULL DEFAULT '',
    model          TEXT NOT NULL DEFAULT '',
    runner         TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'running',
    error          TEXT NOT NULL DEFAULT '',
    cost_usd       REAL,
    tokens_in      INTEGER,
    tokens_out     INTEGER,
    boot_id        TEXT NOT NULL DEFAULT '',
    started_ms     INTEGER NOT NULL,
    ended_ms       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_spans_root ON spans(root_span_id, started_ms);
CREATE INDEX IF NOT EXISTS idx_spans_session ON spans(session_id, started_ms DESC);
"""

_COLS = (
    "span_id, parent_span_id, root_span_id, kind, origin, session_id, title, provider, model, "
    "runner, status, error, cost_usd, tokens_in, tokens_out, boot_id, started_ms, ended_ms"
)
_KEYS = tuple(c.strip() for c in _COLS.split(","))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clip(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):  # a malformed figure reads as unknown
        return None


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):  # a malformed figure reads as unknown
        return None


class TraceStore:
    """SQLite store of turn spans. One connection, WAL, a lock around every use."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        with self._lock:
            if self._path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def open_span(
        self,
        span_id: str,
        *,
        parent_span_id: str = "",
        root_span_id: str = "",
        kind: str = "turn",
        origin: str = "",
        session_id: str = "",
        title: str = "",
        provider: str = "",
        model: str = "",
        runner: str = "",
    ) -> None:
        from dodaios.orchestrator.jobs import BOOT_ID

        with self._lock:
            self._conn.execute(
                f"INSERT OR IGNORE INTO spans ({_COLS}) "  # noqa: S608 - fixed columns
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    span_id, parent_span_id, root_span_id or span_id, kind, origin, session_id,
                    _clip(title, _TITLE_MAX), provider, model, runner, "running", "", None,
                    None, None, BOOT_ID, _now_ms(), None,
                ),
            )
            self._conn.commit()

    def close_span(
        self,
        span_id: str,
        *,
        status: str,
        error: str = "",
        cost_usd: float | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE spans SET status = ?, error = ?, cost_usd = ?, tokens_in = ?, "
                "tokens_out = ?, ended_ms = ? WHERE span_id = ?",
                (status, _clip(error, 400), cost_usd, tokens_in, tokens_out, _now_ms(), span_id),
            )
            self._conn.commit()

    def get(self, span_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_COLS} FROM spans WHERE span_id = ?",  # noqa: S608
                (span_id,),
            ).fetchone()
        return dict(zip(_KEYS, row, strict=True)) if row else None

    def in_root(self, root_span_id: str, *, limit: int = MAX_NODES + 1) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_COLS} FROM spans WHERE root_span_id = ? "  # noqa: S608
                "ORDER BY started_ms ASC LIMIT ?",
                (root_span_id, max(1, int(limit))),
            ).fetchall()
        return [dict(zip(_KEYS, row, strict=True)) for row in rows]

    def roots_for_session(self, session: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_COLS} FROM spans WHERE session_id = ? "  # noqa: S608
                "AND parent_span_id = '' ORDER BY started_ms DESC LIMIT ?",
                (session, max(1, int(limit))),
            ).fetchall()
        return [dict(zip(_KEYS, row, strict=True)) for row in rows]

    def count_in_root(self, root_span_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM spans WHERE root_span_id = ?", (root_span_id,)
            ).fetchone()
        return int(row[0]) if row else 0


# --------------------------------------------------------------------- module state

_store: TraceStore | None = None
_store_lock = threading.Lock()


def get_store() -> TraceStore:
    """The process trace store, opened on first use in the app's data directory."""
    global _store
    with _store_lock:
        if _store is None:
            from dodaios.core.config import DATA_DIR

            _store = TraceStore(Path(DATA_DIR) / "traces.db")
        return _store


def set_store(store: TraceStore | None) -> None:
    """Replace the process store (tests, an embedding host)."""
    global _store
    with _store_lock:
        _store = store


# ------------------------------------------------------------------ trusted provenance


def current_span() -> str:
    """The node that causes work started right now, from trusted state only.

    The chat turn in flight wins. A vendor CLI whose turn has been closed on the
    app side still names its span in the harness header, which the MCP route
    validated. Nothing here reads a tool argument.
    """
    from dodaios.core.chat_turn import current_chat_turn, mcp_span_ref, turn_span_id

    span = turn_span_id(current_chat_turn.get())
    if span:
        return span
    return mcp_span_ref.get() or ""


def root_for(parent_span_id: str) -> str:
    """The root of the tree ``parent_span_id`` belongs to; the id itself if unknown."""
    if not parent_span_id:
        return ""
    try:
        row = get_store().get(parent_span_id)
        if row is not None:
            return str(row["root_span_id"])
        from dodaios.orchestrator import jobs

        job = jobs.get_ledger().by_span(parent_span_id)
        if job is not None:
            return job.root_span_id or job.span_id
    except Exception:  # noqa: BLE001 - tracing is optional
        log.warning("traces: could not resolve the root of %s", parent_span_id, exc_info=True)
    return parent_span_id


def resolve_root(any_id: str) -> str:
    """The root for any node id (a turn id, a span id, a job id), or ``""`` if unknown."""
    any_id = (any_id or "").strip()
    if not any_id:
        return ""
    try:
        row = get_store().get(any_id)
        if row is not None:
            return str(row["root_span_id"])
        from dodaios.orchestrator import jobs

        ledger = jobs.get_ledger()
        job = ledger.get(any_id) or ledger.by_span(any_id)
        if job is not None:
            return job.root_span_id or job.span_id
        if get_store().count_in_root(any_id) or ledger.in_root(any_id, limit=1):
            return any_id
    except Exception:  # noqa: BLE001
        log.warning("traces: could not resolve %s", any_id, exc_info=True)
    return ""


def trace_prefix(turn: Any = None) -> str:
    """The origin word for a trace id: voice, chat, routine, trigger, agent, system.

    ``turn`` defaults to the chat turn in flight; no turn at all is a voice call.
    """
    from dodaios.core.chat_turn import current_chat_turn, origin_of

    return origin_of(turn if turn is not None else current_chat_turn.get())


# --------------------------------------------------------------------- turn lifecycle


def open_turn(
    turn: Any,
    *,
    title: str = "",
    provider: str = "",
    model: str = "",
    runner: str = "",
) -> None:
    """Record that ``turn`` started (best effort)."""
    try:
        from dodaios.core.chat_turn import origin_of, turn_span_id

        span = turn_span_id(turn)
        parent = turn.parent_span_id or ""
        get_store().open_span(
            span,
            parent_span_id=parent,
            root_span_id=root_for(parent) or span,
            origin=origin_of(turn),
            session_id=turn.session_id,
            title=title or turn.user_text,
            provider=provider,
            model=model,
            runner=runner,
        )
    except Exception:  # noqa: BLE001 - never fail a turn for its trace
        log.warning("traces: could not open a span for turn %s", getattr(turn, "turn_id", "?"),
                    exc_info=True)


def close_turn(turn_id: str, payload: dict[str, Any]) -> None:
    """Close the span of ``turn_id`` from its ``turn_finished`` payload (best effort).

    The span id of a turn defaults to its turn id; a turn that carried its own
    ``span_id`` is closed through the same id because ``open_turn`` wrote it.
    """
    try:
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        status = str(payload.get("status") or "done")
        get_store().close_span(
            str(payload.get("span_id") or turn_id),
            status="done" if status in ("done", "ok", "completed", "success") else status,
            error=str(payload.get("error") or ""),
            cost_usd=_float(payload.get("cost_usd")),
            tokens_in=_int(usage.get("input_tokens", usage.get("prompt_tokens"))),
            tokens_out=_int(usage.get("output_tokens", usage.get("completion_tokens"))),
        )
    except Exception:  # noqa: BLE001
        log.warning("traces: could not close the span of turn %s", turn_id, exc_info=True)


# --------------------------------------------------------------------------- read model

def _span_node(row: dict[str, Any], now: int) -> dict[str, Any]:
    from dodaios.orchestrator.jobs import BOOT_ID

    status = row["status"]
    if status == "running" and row["boot_id"] != BOOT_ID:
        status = "interrupted"  # the app that ran it is gone
    ended = row["ended_ms"]
    node: dict[str, Any] = {
        "id": row["span_id"],
        "parent": row["parent_span_id"],
        "kind": row["kind"],
        "origin": row["origin"],
        "title": row["title"],
        "status": status,
        "started_ms": row["started_ms"],
        "ended_ms": ended,
        "seat": {k: row[k] for k in ("provider", "model", "runner") if row[k]},
        "cost_usd": row["cost_usd"],
        "session": row["session_id"],
    }
    if row["tokens_in"] is not None or row["tokens_out"] is not None:
        node["tokens"] = {"in": row["tokens_in"], "out": row["tokens_out"]}
    if row["error"]:
        node["error"] = row["error"]
    node["_live"] = status == "running"
    fallback = now if status == "running" else row["started_ms"]
    node["_end"] = ended if ended is not None else fallback
    return node


def _job_node(job: Any, now: int) -> dict[str, Any]:
    settled = job.state not in ("queued", "running")
    node: dict[str, Any] = {
        "id": job.span_id or job.id,
        "parent": job.parent_span_id,
        "kind": job.kind,
        "job_id": job.id,
        "title": _clip(job.title, _TITLE_MAX),
        "status": job.state,
        "started_ms": job.created_ms,
        "ended_ms": job.updated_ms if settled else None,
        "seat": {"target": job.target} if job.target else {},
        "cost_usd": job.cost_usd,
    }
    if job.error:
        node["error"] = job.error
    receipts = job.meta.get("receipts") if isinstance(job.meta, dict) else None
    if isinstance(receipts, list) and receipts:
        node["receipts"] = [_clip(r, 200) for r in receipts[:_RECEIPTS_MAX]]
    if job.result_ref:
        node["result_ref"] = job.result_ref
    node["_live"] = not settled
    node["_end"] = job.updated_ms if settled else now
    return node


def _finish(node: dict[str, Any], now: int) -> None:
    start = node["started_ms"]
    end = node.pop("_end")
    live = node.pop("_live")
    known = live or node["ended_ms"] is not None
    node["duration_ms"] = max(0, int(end - start)) if known else None
    node["_end_ms"] = end


def build_tree(
    root_id: str,
    *,
    store: TraceStore | None = None,
    ledger: Any = None,
    now_ms: int | None = None,
    max_nodes: int = MAX_NODES,
) -> dict[str, Any] | None:
    """Join the turn spans and the jobs of one root into a bounded tree, or ``None``.

    Each node: id, kind, title, status, started/ended/duration, seat (provider,
    model, runner or the job's target), cost and tokens when known, receipts when
    the job carries them. ``cost_total_usd`` and ``duration_ms`` roll up: a node's
    total is its own cost plus its children's, except that a job with children
    shows the children only (its own figure is the same work the agent turn
    below it already reports). ``critical_path`` follows the chain that ended last.
    """
    from dodaios.orchestrator import jobs

    store = store or get_store()
    ledger = ledger or jobs.get_ledger()
    now = now_ms or _now_ms()
    nodes: dict[str, dict[str, Any]] = {}
    for row in store.in_root(root_id, limit=max_nodes + 1):
        nodes[row["span_id"]] = _span_node(row, now)
    for job in ledger.in_root(root_id, limit=max_nodes + 1):
        nodes.setdefault(job.span_id or job.id, _job_node(job, now))
    if not nodes:
        return None
    truncated = len(nodes) > max_nodes
    if truncated:
        keep = sorted(nodes.values(), key=lambda n: n["started_ms"])[:max_nodes]
        nodes = {n["id"]: n for n in keep}
    for node in nodes.values():
        _finish(node, now)
        node["children"] = []
    root = nodes.get(root_id)
    if root is None:
        # The anchor was never recorded (a parent from before tracing): show it as a stub.
        first = min(n["started_ms"] for n in nodes.values())
        root = {
            "id": root_id, "parent": "", "kind": "unknown", "title": "", "status": "unknown",
            "started_ms": first, "ended_ms": None, "seat": {}, "cost_usd": None,
            "duration_ms": None, "_end_ms": first, "children": [],
        }
        nodes[root_id] = root
    for node in sorted(nodes.values(), key=lambda n: n["started_ms"]):
        if node is root:
            continue
        parent = nodes.get(node["parent"])
        # An orphan (its parent is gone or cut off) hangs from the root; so does a cycle.
        if parent is None or parent is node or _reaches(nodes, parent, node["id"]):
            parent = root
        parent["children"].append(node)
    _roll_up(root)
    root["truncated"] = truncated
    root["node_count"] = len(nodes)
    root["critical_path"] = _critical_path(root)
    return root


def _reaches(nodes: dict[str, dict[str, Any]], start: dict[str, Any], target_id: str) -> bool:
    seen: set[str] = set()
    cursor: dict[str, Any] | None = start
    while cursor is not None and cursor["id"] not in seen:
        if cursor["id"] == target_id:
            return True
        seen.add(cursor["id"])
        cursor = nodes.get(cursor["parent"])
    return False


def _roll_up(node: dict[str, Any]) -> tuple[float | None, int]:
    """Fill ``cost_total_usd`` / ``tokens_total`` bottom-up; return (cost, end_ms)."""
    total: float | None = None
    end = node["_end_ms"]
    tokens = 0
    for child in node["children"]:
        cost, child_end = _roll_up(child)
        end = max(end, child_end)
        if cost is not None:
            total = (total or 0.0) + cost
        tokens += child.get("tokens_total", 0)
    own = node.get("cost_usd")
    if own is not None and not (node["children"] and node["kind"] not in ("turn",)):
        total = (total or 0.0) + own
    own_tokens = node.get("tokens") or {}
    tokens += int(own_tokens.get("in") or 0) + int(own_tokens.get("out") or 0)
    node["cost_total_usd"] = None if total is None else round(total, 6)
    node["tokens_total"] = tokens
    node["span_ms"] = max(0, end - node["started_ms"])
    node["_end_ms"] = end
    return total, end


def _critical_path(root: dict[str, Any]) -> list[str]:
    path = [root["id"]]
    node = root
    while node["children"]:
        node = max(node["children"], key=lambda c: c["_end_ms"])
        path.append(node["id"])
    return path


def public(tree: dict[str, Any]) -> dict[str, Any]:
    """The tree without internal bookkeeping keys, children ordered by start."""

    def clean(node: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in node.items() if not k.startswith("_") and k != "children"}
        if not out.get("seat"):
            out.pop("seat", None)
        out["children"] = [
            clean(c) for c in sorted(node["children"], key=lambda c: c["started_ms"])
        ]
        return out

    return clean(tree)


def list_roots(session: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Trace roots a session started, newest first (turn roots and parentless jobs)."""
    from dodaios.orchestrator import jobs

    limit = min(max(int(limit), 1), MAX_ROOTS)
    store = get_store()
    ledger = jobs.get_ledger()
    rows: list[dict[str, Any]] = []
    for span in store.roots_for_session(session, limit=limit):
        rows.append(
            {
                "root": span["span_id"], "kind": span["kind"], "origin": span["origin"],
                "title": span["title"], "status": span["status"],
                "started_ms": span["started_ms"], "ended_ms": span["ended_ms"],
                "nodes": store.count_in_root(span["span_id"])
                + len(ledger.in_root(span["span_id"], limit=MAX_NODES)),
            }
        )
    for job in ledger.roots_for_session(session, limit=limit):
        rows.append(
            {
                "root": job.span_id or job.id, "kind": job.kind, "origin": "job",
                "title": job.title, "status": job.state, "started_ms": job.created_ms,
                "ended_ms": job.updated_ms if job.settled else None, "nodes": 1,
            }
        )
    rows.sort(key=lambda r: (r["started_ms"], r["root"]), reverse=True)
    return rows[:limit]


def _fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "?"
    seconds = ms // 1000
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m{seconds % 60:02d}s"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def _label(node: dict[str, Any]) -> str:
    seat = node.get("seat") or {}
    who = seat.get("model") or seat.get("target") or ""
    title = node.get("title") or node["kind"]
    return f"{_clip(title, 60)}" + (f" [{who}]" if who else "")


def explain(tree: dict[str, Any], focus_id: str = "") -> str:
    """A compact "what happened and where the time and cost went", from the tree alone."""
    flat: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        flat.append(node)
        for child in node["children"]:
            walk(child)

    walk(tree)
    by_id = {n["id"]: n for n in flat}
    cost = tree.get("cost_total_usd")
    lines = [
        f"Trace {tree['id']}: {_label(tree)} is {tree['status']}. "
        f"Span {_fmt_ms(tree.get('span_ms'))} across {len(flat)} step(s), "
        + (f"cost ${cost:.4f}." if cost is not None else "cost unknown.")
    ]
    path = [by_id[i] for i in tree.get("critical_path", []) if i in by_id]
    if len(path) > 1:
        lines.append(
            "Longest chain: "
            + " -> ".join(f"{_label(n)} {_fmt_ms(n.get('duration_ms'))} ({n['status']})"
                          for n in path[:6])
        )
    slowest = sorted(
        (n for n in flat if n.get("duration_ms") is not None and not n["children"]),
        key=lambda n: n["duration_ms"], reverse=True,
    )[:3]
    if slowest:
        lines.append(
            "Slowest steps: "
            + "; ".join(f"{_label(n)} {_fmt_ms(n['duration_ms'])}" for n in slowest)
        )
    priced = sorted(
        (n for n in flat if n.get("cost_usd")), key=lambda n: n["cost_usd"], reverse=True
    )[:3]
    if priced:
        lines.append(
            "Costliest steps: " + "; ".join(f"{_label(n)} ${n['cost_usd']:.4f}" for n in priced)
        )
    bad = [n for n in flat if n["status"] in ("failed", "error", "blocked", "interrupted")]
    if bad:
        lines.append(
            "Needs a look: "
            + "; ".join(
                f"{_label(n)} {n['status']}"
                + (f" ({_clip(n['error'], 80)})" if n.get("error") else "")
                for n in bad[:4]
            )
        )
    running = [n for n in flat if n["status"] in ("running", "queued")]
    if running:
        lines.append("Still running: " + "; ".join(_label(n) for n in running[:4]))
    if focus_id and focus_id in by_id and focus_id != tree["id"]:
        node = by_id[focus_id]
        lines.append(
            f"Asked about {focus_id}: {_label(node)} {node['status']}, "
            f"{_fmt_ms(node.get('duration_ms'))}"
            + (f", ${node['cost_total_usd']:.4f}" if node.get("cost_total_usd") is not None else "")
            + "."
        )
    if tree.get("truncated"):
        lines.append("The tree was cut at the node limit.")
    return "\n".join(lines)


__all__ = [
    "MAX_NODES", "SPAN_ID_RE", "TraceStore", "build_tree", "close_turn", "current_span",
    "explain", "get_store", "list_roots", "open_turn", "public", "resolve_root", "root_for",
    "set_store", "trace_prefix",
]

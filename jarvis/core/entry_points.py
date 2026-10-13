"""The installed plugin catalogue: one read per group, under every name it has.

``importlib.metadata.entry_points()`` is not a lookup — it is a filesystem
sweep. Every call re-walks ``sys.path``, enumerates every installed
distribution and opens each one's ``entry_points.txt``. On a full Jarvis
install that is 535 distributions; measured here it costs ~30 ms once the OS
file cache is warm and **624 ms cold**, and a cold sweep under disk load has
been seen to take seconds.

That would be merely wasteful if it happened once. It does not: plugin
resolution asks per candidate, so a single cross-family fallback chain pays for
it once per provider it probes, and the callers sit on the asyncio event loop —
the same loop that serves every WebSocket, HTTP route and terminal pane. A
16.5 s loop stall was captured with exactly this call at the bottom of the
stack (``_dictation_session`` → ``build_stt_from_config`` →
``_load_provider_class`` → ``entry_points()`` → ``read_text`` → ``io.open``),
which is why :func:`entry_points_for` exists.

Caching for the life of the process is correct rather than merely convenient:
the catalogue only changes when a distribution is installed or removed, and a
new entry-point does not take effect in an already-running interpreter anyway
(hence AGENTS.md §10's ``pip install -e . --no-deps`` followed by a restart).
:func:`invalidate` is provided for the one case that does need it — a test, or
an in-process install that wants the next read to see new plugins.

**Two names, one group.** A plugin slot is published as ``dodaios.<slot>`` and,
for every plugin written before the product was renamed, as ``jarvis.<slot>``.
Both spellings are one group here: :func:`entry_points` and
:func:`entry_points_for` accept either and answer with the union, so every
reader of a plugin group goes through this module and never asks
``importlib.metadata`` itself. The union costs **one** sweep, not one per
spelling — see :class:`_AnySpelling`.

When both spellings carry an entry of the same name, the ``dodaios.<slot>``
entry is the one that loads and the ``jarvis.<slot>`` entry is dropped: a
plugin that registers under both (so it also loads in an older host) is loaded
once, and a plugin that deliberately points the two names at different objects
gets the one written for this host. The second case is logged as a conflict.
"""

from __future__ import annotations

import logging
import threading
from importlib import metadata

from .branding import LEGACY_PLUGIN_GROUP_NAMESPACES, PLUGIN_GROUP_NAMESPACE

__all__ = ["entry_points", "entry_points_for", "group_spellings", "invalidate"]

log = logging.getLogger(__name__)

# Guards the fill, not the read. Without it, the several subsystems that resolve
# plugins concurrently during boot would each pay the cold sweep in parallel —
# the one moment the sweep is at its most expensive.
_LOCK = threading.Lock()
_CACHE: dict[str, tuple[metadata.EntryPoint, ...]] = {}

_NAMESPACES: tuple[str, ...] = (PLUGIN_GROUP_NAMESPACE, *LEGACY_PLUGIN_GROUP_NAMESPACES)


def group_spellings(group: str) -> tuple[str, ...]:
    """Every name ``group`` is published under, the current one first.

    ``"jarvis.tool"`` and ``"dodaios.tool"`` both answer
    ``("dodaios.tool", "jarvis.tool")``. A group outside the plugin namespaces
    (``"console_scripts"``) has one spelling: its own.
    """
    namespace, dot, slot = group.partition(".")
    if not dot or not slot or namespace not in _NAMESPACES:
        return (group,)
    return tuple(f"{candidate}.{slot}" for candidate in _NAMESPACES)


class _AnySpelling(str):
    """A group name that compares equal to each of the group's spellings.

    ``importlib.metadata`` selects entry points with ``group == <the value
    passed>``, so handing it this value selects every spelling during the one
    sweep the call makes anyway. Its text is the spelling the caller asked
    for. Whether the running interpreter really compares that way is checked
    once, by :func:`_selects_in_one_sweep`, never assumed.
    """

    __slots__ = ("_spellings",)
    _spellings: frozenset[str]

    def __new__(cls, asked: str, spellings: tuple[str, ...]) -> _AnySpelling:
        self = super().__new__(cls, asked)
        self._spellings = frozenset(spellings)
        return self

    def __eq__(self, other: object) -> bool:
        return isinstance(other, str) and str(other) in self._spellings

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    __hash__ = str.__hash__


_ONE_SWEEP: bool | None = None


def _selects_in_one_sweep() -> bool:
    """Whether this interpreter's entry-point selection honours :class:`_AnySpelling`.

    Asked of an in-memory entry point, so it costs nothing and touches no disk.
    An interpreter that selects some other way answers ``False`` and the caller
    reads each spelling separately: the result is the same, only slower.
    """
    global _ONE_SWEEP  # noqa: PLW0603 — a process-wide capability answer
    if _ONE_SWEEP is None:
        probe = metadata.EntryPoint(name="probe", value="probe:probe", group="b.slot")
        try:
            matched = probe.matches(group=_AnySpelling("a.slot", ("a.slot", "b.slot")))
            missed = probe.matches(group=_AnySpelling("a.slot", ("a.slot", "c.slot")))
            _ONE_SWEEP = bool(matched) and not missed
        except Exception:  # noqa: BLE001 — an unknown selection API means "not supported"
            log.debug("entry points: one-sweep selection is unavailable", exc_info=True)
            _ONE_SWEEP = False
    return _ONE_SWEEP


def _group_of(ep: metadata.EntryPoint) -> str:
    """The plain group name an entry point was declared in, ``""`` when it has none."""
    return str(getattr(ep, "group", "") or "")


def _prefer_current(
    found: list[metadata.EntryPoint], spellings: tuple[str, ...]
) -> tuple[metadata.EntryPoint, ...]:
    """Drop a legacy-group entry that the current group also declares by name."""
    current_group = spellings[0]
    current: dict[str, metadata.EntryPoint] = {}
    for ep in found:
        if _group_of(ep) == current_group:
            current.setdefault(ep.name, ep)
    if not current:
        return tuple(found)
    kept: list[metadata.EntryPoint] = []
    for ep in found:
        winner = current.get(ep.name)
        if winner is None or _group_of(ep) == current_group:
            kept.append(ep)
            continue
        if getattr(ep, "value", None) != winner.value:
            log.warning(
                "Plugin %r is registered twice with different targets: %s -> %s "
                "and %s -> %s. Loading the %s one.",
                ep.name,
                current_group,
                winner.value,
                _group_of(ep),
                getattr(ep, "value", "?"),
                current_group,
            )
    return tuple(kept)


def entry_points(*, group: str) -> tuple[metadata.EntryPoint, ...]:
    """Every entry point of ``group``, read fresh, under all of its spellings.

    The drop-in for ``importlib.metadata.entry_points(group=...)``: same
    keyword, same one sweep over the installed distributions, and the answer
    also holds what plugins registered under the group's other spelling. Use
    :func:`entry_points_for` on a path that asks repeatedly.
    """
    spellings = group_spellings(group)
    if len(spellings) == 1:
        return tuple(metadata.entry_points(group=group))
    if _selects_in_one_sweep():
        found = list(metadata.entry_points(group=_AnySpelling(group, spellings)))
    else:
        found = [ep for spelling in spellings for ep in metadata.entry_points(group=spelling)]
    return _prefer_current(found, spellings)


def entry_points_for(group: str) -> tuple[metadata.EntryPoint, ...]:
    """Every entry-point declared in ``group``, read from disk at most once.

    Args:
        group: An entry-point group name under either spelling, e.g.
            ``"dodaios.stt"`` or ``"jarvis.stt"``. Both share one cache entry.

    Returns:
        The group's entry-points as an immutable tuple. Empty when the group
        has no registered plugins — indistinguishable, deliberately, from a
        group nobody declared: both mean "nothing to load here".
    """
    key = group_spellings(group)[0]
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    with _LOCK:
        # A second caller may have filled it while this one waited.
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        resolved = entry_points(group=group)
        _CACHE[key] = resolved
        return resolved


def invalidate() -> None:
    """Drop the cache so the next read goes back to disk.

    For tests, and for the rare in-process install that adds plugins. Callers
    that merely want fresh *behaviour* from an existing plugin do not need
    this — the catalogue caches the entry-point declarations, never the loaded
    modules.
    """
    with _LOCK:
        _CACHE.clear()

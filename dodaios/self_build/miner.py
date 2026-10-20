"""Observe: count what the person keeps asking for, without asking a model.

Every finished turn of the person (voice, Jarvis chat, agent chat) and every
prompt they type to a coding agent in the IDE (channel ``pane``) arrives as an
:class:`Observation` that holds only the person's own words. Text from web
pages, tool results or other agents never gets here: the callers pass the
typed or spoken request and nothing else, and turns an agent or a routine
started are dropped before. The tool names the assistant used are kept as
context (which tools a skill would need), never as evidence of a need.

The miner groups requests by their content words (the skill matcher's own
multilingual tokenizer, folded to six-letter stems) into clusters, and after
each turn checks the touched cluster against fixed thresholds. A need that
crosses one becomes a :class:`Need`; the decide step then spends at most one
model call on it. The thresholds favour precision: proactive assistants are
wrong about a third of the time or worse, so a need must recur on different
days before anything is asked.

Cost: one small SQLite insert and a scan of the clusters seen in the last
four weeks per turn. No model, no timer.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from .ledger import now_ms
from .records import Kind
from .signals import Cluster, SignalStore, TurnRow

_DAY_MS: Final[int] = 86_400_000

#: Stems: the first letters of each content word, so "report", "reports" and
#: "reporting" are one word, and "Bericht" / "Berichte" too.
STEM_CHARS: Final[int] = 6
#: Shortest request worth counting ("weather?" has 8 characters).
MIN_CHARS: Final[int] = 8
#: Two requests are the same need when they share at least two stems and half
#: of all their stems, or, for one- or two-word requests, all of them.
MATCH_SHARED: Final[int] = 2
MATCH_JACCARD: Final[float] = 0.5

#: Everything is counted in this window.
WINDOW_DAYS: Final[int] = 28
#: Repeated request: three times on three different days. Asking twice is
#: chance; three times on one day is a retry, not a habit.
REPEAT_TIMES: Final[int] = 3
REPEAT_DAYS: Final[int] = 3
#: A repeated request is only a skill candidate when the assistant needed a
#: tool to answer it: a question it answers from knowledge needs no procedure.
#: Work handed to a coding agent in the IDE counts as done with a tool.
TOOL_SHARE: Final[float] = 0.5
#: The channel of a prompt the person typed to a coding agent in the IDE.
PANE: Final[str] = "pane"
#: Repeated correction: twice on two days within two weeks. A correction the
#: person has to repeat is a lesson the assistant did not learn.
CORRECTION_TIMES: Final[int] = 2
CORRECTION_DAYS: Final[int] = 2
CORRECTION_WINDOW_DAYS: Final[int] = 14
#: Recurring failure: three failed answers on two days.
FAILURE_TIMES: Final[int] = 3
FAILURE_DAYS: Final[int] = 2
#: Weekly habit: the same weekday in three different weeks, within three hours.
WEEKLY_WEEKS: Final[int] = 3
WEEKLY_SPREAD_MIN: Final[int] = 180
#: Daily habit: four different days within two weeks, within two hours.
DAILY_DAYS: Final[int] = 4
DAILY_WINDOW_DAYS: Final[int] = 14
DAILY_SPREAD_MIN: Final[int] = 120
#: A routine runs this long before the person usually asks.
SCHEDULE_LEAD_MIN: Final[int] = 15
#: Sequence: request B follows request A within 15 minutes in one
#: conversation, on three different days.
SEQUENCE_GAP_MS: Final[int] = 15 * 60_000
SEQUENCE_DAYS: Final[int] = 3
#: Domain (the only route to a new agent): at least three different needs,
#: each asked twice, that use one tool family, ten requests over two weeks.
DOMAIN_NEEDS: Final[int] = 3
DOMAIN_NEED_TIMES: Final[int] = 2
DOMAIN_TURNS: Final[int] = 10
DOMAIN_SPAN_DAYS: Final[int] = 14
#: Evidence turns kept per need (the newest).
MAX_EVIDENCE: Final[int] = 12


@dataclass(frozen=True, slots=True)
class Observation:
    """One finished turn, as far as the miner may see it.

    ``text`` is the person's own words and nothing else. ``tools`` are the
    tools the assistant used for its answer (context, never evidence).
    """

    text: str
    channel: str
    conversation: str
    ts_ms: int = 0
    tools: tuple[str, ...] = ()
    failed: bool = False
    agent_id: str = ""
    lang: str = ""
    ref: str = ""
    #: The assistant's answer, when the surface knows it. Never stored: it is
    #: read once to tell whether a self-built memory was relied on.
    answer: str = ""


@dataclass(frozen=True, slots=True)
class Need:
    """A need signature that crossed its threshold."""

    signature: str
    #: Why it crossed, e.g. ``("repeated", "weekly")``.
    reasons: tuple[str, ...]
    #: The kinds that may answer it, cheapest first.
    rungs: tuple[Kind, ...]
    turns: tuple[TurnRow, ...]
    occurrences: int
    days: int
    #: Tools the assistant used in at least half of the turns.
    tools: tuple[str, ...] = ()
    #: A calendar schedule hint for a routine (``{"kind": "calendar", ...}``).
    schedule: dict[str, object] | None = None
    cluster: int = 0
    #: For a domain: the clusters it spans.
    clusters: tuple[int, ...] = field(default_factory=tuple)

    @property
    def lang(self) -> str:
        langs = Counter(t.lang for t in self.turns if t.lang)
        return langs.most_common(1)[0][0] if langs else ""


def stems(text: str) -> frozenset[str]:
    """The content-word stems of a request (multilingual, accent-folded)."""
    from dodaios.skills.relevance import tokenize

    return frozenset(
        token[:STEM_CHARS]
        for token in tokenize(text)
        if len(token) >= 3 and not any(ch.isdigit() for ch in token)
    )


def same_need(left: frozenset[str], right: frozenset[str]) -> bool:
    if not left or not right:
        return False
    shared = len(left & right)
    if len(left) <= 2 or len(right) <= 2:
        return left == right
    return shared >= MATCH_SHARED and shared / len(left | right) >= MATCH_JACCARD


def signature_for(word_stems: Iterable[str]) -> str:
    return "need:" + "+".join(sorted(word_stems)[:8])


def tool_family(name: str) -> str:
    """``mcp:github/create_issue`` → ``mcp:github``; a bare tool is its own family."""
    head = name.split("/", 1)[0]
    return head.split(".", 1)[0].split("__", 1)[0]


class Miner:
    """Files observations and reports the needs they complete. Blocking."""

    def __init__(self, store: SignalStore) -> None:
        self.store = store
        self._clusters: dict[int, Cluster] | None = None

    # ------------------------------------------------------------ intake

    def observe(
        self, obs: Observation, *, correction: bool = False
    ) -> tuple[TurnRow | None, list[Need]]:
        """Store one request and return the needs it completes (often none)."""
        text = " ".join((obs.text or "").split())
        if len(text) < MIN_CHARS:
            return None, []
        word_stems = stems(text)
        if not word_stems:
            return None, []
        ts = obs.ts_ms or now_ms()
        cluster = self._assign(word_stems, ts)
        row = self.store.add_turn(
            ts_ms=ts,
            channel=obs.channel,
            conversation=obs.conversation,
            text=text,
            stems=word_stems,
            cluster=cluster.id,
            tools=obs.tools,
            failed=obs.failed,
            correction=correction,
            agent_id=obs.agent_id,
            lang=obs.lang,
            ref=obs.ref,
        )
        self._load(ts)[cluster.id] = Cluster(
            cluster.id, cluster.signature, cluster.stems, cluster.size + 1, cluster.first_ms, ts
        )
        needs = [n for n in (self.cluster_need(cluster.id, now=ts),) if n is not None]
        needs += self.sequence_needs(row)
        if row.tools:
            needs += self.domain_needs(row, now=ts)
        return row, needs

    def _load(self, now: int) -> dict[int, Cluster]:
        if self._clusters is None:
            since = now - WINDOW_DAYS * _DAY_MS
            self._clusters = {c.id: c for c in self.store.clusters_since(since)}
        return self._clusters

    def _assign(self, word_stems: frozenset[str], ts: int) -> Cluster:
        clusters = self._load(ts)
        cutoff = ts - WINDOW_DAYS * _DAY_MS
        best: Cluster | None = None
        best_score = 0.0
        for cluster in list(clusters.values()):
            if cluster.last_ms < cutoff:
                clusters.pop(cluster.id, None)
                continue
            if not same_need(word_stems, cluster.stems):
                continue
            score = len(word_stems & cluster.stems) / len(word_stems | cluster.stems)
            if score > best_score:
                best, best_score = cluster, score
        if best is not None:
            return best
        created = self.store.new_cluster(signature_for(word_stems), word_stems, ts)
        clusters[created.id] = created
        return created

    # ------------------------------------------------------------ thresholds

    def cluster_need(self, cluster_id: int, *, now: int | None = None) -> Need | None:
        """The need ``cluster_id`` has become, if any threshold is crossed."""
        stamp = now if now is not None else now_ms()
        cluster = self.store.cluster(cluster_id)
        if cluster is None:
            return None
        turns = self.store.turns_of(cluster_id, since_ms=stamp - WINDOW_DAYS * _DAY_MS)
        if not turns:
            return None
        reasons: list[str] = []
        rungs: list[Kind] = []
        evidence: list[TurnRow] = []
        tools = consistent_tools(turns)

        recent = [t for t in turns if t.ts_ms >= stamp - CORRECTION_WINDOW_DAYS * _DAY_MS]
        corrections = [t for t in recent if t.correction]
        if (
            len(corrections) >= CORRECTION_TIMES
            and len({t.day for t in corrections}) >= CORRECTION_DAYS
        ):
            reasons.append("correction")
            rungs.append(Kind.MEMORY)
            evidence += corrections

        failures = [t for t in turns if t.failed]
        if len(failures) >= FAILURE_TIMES and len({t.day for t in failures}) >= FAILURE_DAYS:
            reasons.append("failure")
            rungs += [Kind.MEMORY, Kind.SKILL]
            evidence += failures

        days = len({t.day for t in turns})
        delegated = sum(1 for t in turns if t.channel == PANE)
        if (
            len(turns) >= REPEAT_TIMES
            and days >= REPEAT_DAYS
            and (tools or delegated >= len(turns) * TOOL_SHARE)
        ):
            reasons.append("repeated")
            rungs.append(Kind.SKILL)
            evidence += turns

        schedule = habit(turns, now=stamp)
        if schedule is not None:
            reasons.append(str(schedule.pop("habit")))
            rungs += [Kind.SKILL, Kind.ROUTINE]
            evidence += turns

        if not reasons:
            return None
        return Need(
            signature=cluster.signature,
            reasons=tuple(reasons),
            rungs=_ladder(rungs),
            turns=_newest(evidence),
            occurrences=len(turns),
            days=days,
            tools=tools,
            schedule=schedule,
            cluster=cluster_id,
        )

    def sequence_needs(self, row: TurnRow) -> list[Need]:
        """Request B keeps following request A: a procedure the person runs by hand."""
        before = self.store.turns_in(
            row.conversation, since_ms=row.ts_ms - SEQUENCE_GAP_MS, until_ms=row.ts_ms - 1
        )
        needs: list[Need] = []
        for first in {t.cluster for t in before if t.cluster and t.cluster != row.cluster}:
            pairs = self._pairs(first, row.cluster, now=row.ts_ms)
            if len({second.day for _, second in pairs}) < SEQUENCE_DAYS:
                continue
            turns = [t for pair in pairs for t in pair]
            needs.append(
                Need(
                    signature=f"sequence:{first}>{row.cluster}",
                    reasons=("sequence",),
                    rungs=(Kind.SKILL,),
                    turns=_newest(turns),
                    occurrences=len(pairs),
                    days=len({second.day for _, second in pairs}),
                    tools=consistent_tools(turns),
                    cluster=row.cluster,
                    clusters=(first, row.cluster),
                )
            )
        return needs

    def _pairs(self, first: int, second: int, *, now: int) -> list[tuple[TurnRow, TurnRow]]:
        since = now - WINDOW_DAYS * _DAY_MS
        firsts = self.store.turns_of(first, since_ms=since)
        pairs: list[tuple[TurnRow, TurnRow]] = []
        for later in self.store.turns_of(second, since_ms=since):
            match = [
                t
                for t in firsts
                if t.conversation == later.conversation
                and 0 < later.ts_ms - t.ts_ms <= SEQUENCE_GAP_MS
            ]
            if match:
                pairs.append((match[-1], later))
        return pairs

    def domain_needs(self, row: TurnRow, *, now: int) -> list[Need]:
        """Several needs that share one tool family: the only road to a new agent.

        Turns in an agent's own chat do not count: that work already has an agent.
        """
        families = {tool_family(t) for t in row.tools if t}
        if not families or row.agent_id:
            return []
        recent = [
            t
            for t in self.store.recent_turns(since_ms=now - WINDOW_DAYS * _DAY_MS)
            if not t.agent_id
        ]
        needs: list[Need] = []
        for family in sorted(families):
            turns = [t for t in recent if any(tool_family(x) == family for x in t.tools)]
            per_cluster = Counter(t.cluster for t in turns)
            clusters = sorted(c for c, n in per_cluster.items() if n >= DOMAIN_NEED_TIMES)
            if len(clusters) < DOMAIN_NEEDS or len(turns) < DOMAIN_TURNS:
                continue
            span = (max(t.ts_ms for t in turns) - min(t.ts_ms for t in turns)) / _DAY_MS
            if span < DOMAIN_SPAN_DAYS:
                continue
            needs.append(
                Need(
                    signature=f"domain:{family}",
                    reasons=("domain",),
                    rungs=(Kind.AGENT,),
                    turns=_newest(turns),
                    occurrences=len(turns),
                    days=len({t.day for t in turns}),
                    tools=consistent_tools(turns, share=0.2),
                    cluster=row.cluster,
                    clusters=tuple(clusters),
                )
            )
        return needs


# ------------------------------------------------------------ helpers


def consistent_tools(turns: Iterable[TurnRow], *, share: float = TOOL_SHARE) -> tuple[str, ...]:
    """Tools the assistant used in at least ``share`` of the turns."""
    rows = list(turns)
    if not rows:
        return ()
    counts = Counter(tool for t in rows for tool in set(t.tools))
    need = max(2, int(len(rows) * share + 0.999))
    return tuple(sorted(tool for tool, n in counts.items() if n >= need))


def habit(turns: list[TurnRow], *, now: int) -> dict[str, object] | None:
    """A calendar schedule when the person asks at the same time of day or week.

    Returns ``{"habit": "weekly"|"daily", "kind": "calendar", "local_time":
    "HH:MM", "weekdays": [...]}``; the routine runs a little before the
    person usually asks.
    """
    turns = [t for t in turns if t.minute >= 0 and t.weekday >= 0]  # clock known
    by_weekday: dict[int, list[TurnRow]] = {}
    for turn in turns:
        by_weekday.setdefault(turn.weekday, []).append(turn)
    for weekday, rows in sorted(by_weekday.items(), key=lambda kv: -len(kv[1])):
        weeks = {_week(t) for t in rows}
        if len(weeks) < WEEKLY_WEEKS:
            continue
        window = _tight_window(rows, WEEKLY_SPREAD_MIN, key=_week)
        if window is not None and len({_week(t) for t in window}) >= WEEKLY_WEEKS:
            return {
                "habit": "weekly",
                "kind": "calendar",
                "local_time": _run_time(window),
                "weekdays": [weekday],
            }
    recent = [t for t in turns if t.ts_ms >= now - DAILY_WINDOW_DAYS * _DAY_MS]
    window = _tight_window(recent, DAILY_SPREAD_MIN, key=lambda t: t.day)
    if window is not None and len({t.day for t in window}) >= DAILY_DAYS:
        weekdays = sorted({t.weekday for t in window})
        schedule: dict[str, object] = {
            "habit": "daily",
            "kind": "calendar",
            "local_time": _run_time(window),
        }
        if max(weekdays) <= 4:  # only on working days: keep the weekend quiet
            schedule["weekdays"] = [0, 1, 2, 3, 4]
        return schedule
    return None


def _week(turn: TurnRow) -> int:
    return (turn.day - turn.weekday) // 7


def _tight_window(rows: list[TurnRow], spread: int, *, key: object) -> list[TurnRow] | None:
    """The largest set of turns (one per ``key``) whose times lie within ``spread`` minutes."""
    if not rows:
        return None
    ordered = sorted(rows, key=lambda t: t.minute)
    best: list[TurnRow] = []
    for start, first in enumerate(ordered):
        window: dict[int, TurnRow] = {}
        for turn in ordered[start:]:
            if turn.minute - first.minute > spread:
                break
            window.setdefault(key(turn), turn)  # type: ignore[operator]
        if len(window) > len(best):
            best = list(window.values())
    return best or None


def _run_time(rows: list[TurnRow]) -> str:
    minute = max(0, min(t.minute for t in rows) - SCHEDULE_LEAD_MIN)
    minute -= minute % 5
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _ladder(kinds: Iterable[Kind]) -> tuple[Kind, ...]:
    order = list(Kind)
    return tuple(sorted(set(kinds), key=order.index))


def _newest(turns: Iterable[TurnRow]) -> tuple[TurnRow, ...]:
    unique = {t.id: t for t in turns}
    return tuple(sorted(unique.values(), key=lambda t: t.ts_ms)[-MAX_EVIDENCE:])

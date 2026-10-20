"""The Dodaios Verse level system's rulebook: pure tables, no I/O.

The Verse is the interior of a fleet capital ship. Three kinds of subject
serve aboard and level up:

* ``person`` — the commanding officer, the person at the keyboard (one
  subject, id ``person``);
* ``agent`` — every agent on the society roster, an officer of the crew
  (``agent:<agent_id>``);
* ``pet`` — the person's pet from My Pets, the commander's companion drone
  (``pet:<pet_id>``; each pet keeps its own level, the active one earns). The
  lead agent is drawn as the companion, so the lead's work pays the pet.

XP only ever comes from a rule in :data:`RULES`. A rule names its source, the
subject kind it pays, a fixed amount, an optional cooldown and an optional
daily cap. Server rules are read off real bus events (a finished turn, a
finished task); world rules are small actions aboard the ship that the client
reports and the server still meters. Nothing here calls a model, so the
system works with any single key and costs no tokens.

The level curve is front-loaded the way long-running progression usually is:
level 2 arrives within the first few actions, level 10 after about a week of
ordinary use, level 50 after several months. Levels climb the fleet's rank
ladder (:data:`RANKS`) in four tiers, from recruit to fleet admiral, and open
the commander's uniforms and the ribbons of the service record
(:data:`REWARDS`). ``docs/agent-society/level-system.md`` is the readable
version of this file; parity tests pin the frontend's copies of the ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

SubjectKind = Literal["person", "agent", "pet"]
SUBJECT_KINDS: Final[tuple[SubjectKind, ...]] = ("person", "agent", "pet")

#: The id of the one person subject.
PERSON_ID: Final[str] = "person"

MAX_LEVEL: Final[int] = 50

#: Society roster id of the lead. The lead is drawn as the person's pet, so its
#: work pays the pet, never an ``agent:jarvis`` subject.
LEAD_AGENT_ID: Final[str] = "jarvis"

#: The ship's decks, top to bottom: the refs a ``deck_discovered`` or an
#: ``inspection`` report may name. The frontend's copy is
#: ``components/society/verse/decks.ts`` (``DECK_IDS``); a parity test holds
#: them together.
VERSE_DECKS: Final[tuple[str, ...]] = ("bridge", "ops", "engineering", "hangar")


def xp_to_next(level: int) -> int:
    """XP needed to climb from ``level`` to ``level + 1`` (0 at the cap).

    40 XP for the first step, then a gently super-linear rise, rounded to 5
    so the numbers read cleanly in the HUD.
    """
    if level >= MAX_LEVEL:
        return 0
    if level < 1:
        level = 1
    raw = 40 + 25 * (level - 1) ** 1.1
    return int(round(raw / 5.0) * 5)


def total_xp_for_level(level: int) -> int:
    """Total XP at which ``level`` is reached (level 1 = 0 XP)."""
    level = max(1, min(MAX_LEVEL, level))
    return sum(xp_to_next(step) for step in range(1, level))


def level_for_xp(total_xp: int) -> int:
    level = 1
    remaining = max(0, int(total_xp))
    while level < MAX_LEVEL:
        need = xp_to_next(level)
        if remaining < need:
            break
        remaining -= need
        level += 1
    return level


@dataclass(frozen=True, slots=True)
class LevelProgress:
    level: int
    xp: int
    #: XP gathered since the current level started.
    into_level: int
    #: XP the current level needs in total (0 at the cap).
    for_next: int


def progress_for_xp(total_xp: int) -> LevelProgress:
    total = max(0, int(total_xp))
    level = level_for_xp(total)
    into = total - total_xp_for_level(level)
    return LevelProgress(level=level, xp=total, into_level=into, for_next=xp_to_next(level))


# ------------------------------------------------------------------ XP rules

Trigger = Literal["server", "world"]


@dataclass(frozen=True, slots=True)
class XpRule:
    source: str
    kind: SubjectKind
    xp: int
    trigger: Trigger
    #: Minimum seconds between two awards of this rule to one subject.
    cooldown_s: int = 0
    #: Most XP one subject can earn from this rule per local day (0 = no cap).
    daily_cap: int = 0
    #: True: at most one award per ``ref`` ever (a deck is discovered once).
    once_per_ref: bool = False


RULES: Final[tuple[XpRule, ...]] = (
    # The commander: talking to the assistant, giving the crew work, growing the crew.
    XpRule("chat_turn", "person", 5, "server", daily_cap=100),
    XpRule("voice_turn", "person", 5, "server", daily_cap=100),
    XpRule("quest_posted", "person", 15, "server", daily_cap=75),
    XpRule("quest_completed", "person", 20, "server"),
    XpRule("agent_hired", "person", 50, "server"),
    XpRule("mission_completed", "person", 30, "server", daily_cap=150),
    # The commander, aboard the ship.
    XpRule("daily_visit", "person", 25, "world", once_per_ref=True),
    XpRule("deck_discovered", "person", 20, "world", once_per_ref=True),
    XpRule("simulator_round", "person", 8, "world", cooldown_s=45, daily_cap=80),
    XpRule("simulator_record", "person", 15, "world", cooldown_s=45, daily_cap=60),
    XpRule("team_briefing", "person", 10, "world", cooldown_s=600, daily_cap=40),
    XpRule("inspection", "person", 15, "world", once_per_ref=True, daily_cap=30),
    # The crew: finished work is what counts.
    XpRule("task_done", "agent", 40, "server"),
    XpRule("task_blocked", "agent", 8, "server", daily_cap=40),
    XpRule("quest_done", "agent", 60, "server"),
    XpRule("answered_teammate", "agent", 5, "server", daily_cap=50),
    # The companion drone carries the lead's work: every answer and every
    # hand-off it makes, and the walks it takes at the commander's heel.
    XpRule("jarvis_answered", "pet", 4, "server", daily_cap=120),
    XpRule("delegated", "pet", 10, "server", daily_cap=100),
    XpRule("walk_together", "pet", 3, "world", cooldown_s=20, daily_cap=60),
)

RULES_BY_SOURCE: Final[dict[str, XpRule]] = {rule.source: rule for rule in RULES}

#: Sources the client may report through ``POST /api/progression/actions``.
WORLD_ACTIONS: Final[frozenset[str]] = frozenset(r.source for r in RULES if r.trigger == "world")

#: Sources earlier builds paid that no rule pays any more. Ledger rows that
#: carry them still read and still count; they are only never paid again.
RETIRED_SOURCES: Final[frozenset[str]] = frozenset(
    {
        # The starship (2026-10): the holodeck became the simulator room, the
        # helm and its destinations are gone.
        "holodeck_round",
        "holodeck_record",
        "warp_jump",
        # The office tower.
        "floor_discovered",
        "dog_petted",
        "dog_treat",
        "arcade_round",
        "arcade_record",
        "team_meeting",
    }
)


# ------------------------------------------------------------------ ranks

RankTier = Literal["deck", "line", "command", "flag"]
#: Lowest first: enlisted deck ratings, line officers, command, flag officers.
RANK_TIERS: Final[tuple[RankTier, ...]] = ("deck", "line", "command", "flag")

#: The rank ladder everyone aboard climbs, lowest first: (first level, rank
#: id, tier). The commander, every officer and the companion drone share it,
#: so a rank means the same thing on every name plate. The frontend's copy is
#: ``components/society/verse/ranks/ranks.ts`` (with the rank plate's tile
#: pattern); its words are ``verse.ranks.rank.<id>``.
RANKS: Final[tuple[tuple[int, str, RankTier], ...]] = (
    (1, "recruit", "deck"),
    (3, "deckhand", "deck"),
    (5, "technician", "deck"),
    (8, "senior_technician", "deck"),
    (11, "ensign", "line"),
    (14, "lieutenant", "line"),
    (17, "senior_lieutenant", "line"),
    (21, "commander", "line"),
    (25, "captain", "line"),
    (29, "line_captain", "command"),
    (33, "commodore", "command"),
    (37, "rear_admiral", "flag"),
    (41, "vice_admiral", "flag"),
    (45, "admiral", "flag"),
    (50, "fleet_admiral", "flag"),
)

RANK_IDS: Final[tuple[str, ...]] = tuple(rank for _, rank, _ in RANKS)


def rank_for(level: int) -> tuple[int, str, RankTier]:
    """The rank a subject at ``level`` holds."""
    held = RANKS[0]
    for entry in RANKS:
        if level >= entry[0]:
            held = entry
    return held


def tier_start(tier: RankTier) -> int:
    """The first level of ``tier`` (the level its lowest rank opens at)."""
    return min(level for level, _, t in RANKS if t == tier)


# ------------------------------------------------------------------ rewards

Slot = Literal["uniform", "ribbon"]
SLOTS: Final[tuple[Slot, ...]] = ("uniform", "ribbon")


@dataclass(frozen=True, slots=True)
class Reward:
    #: ``<slot>_<name>``; a uniform's name is the rank tier it belongs to.
    reward_id: str
    slot: Slot
    #: The level each subject kind unlocks it at; ``None`` = not for that kind.
    person: int | None
    agent: int | None
    pet: int | None

    def level_for(self, kind: SubjectKind) -> int | None:
        return {"person": self.person, "agent": self.agent, "pet": self.pet}[kind]


#: What a level opens.
#:
#: Uniforms are the commander's: the quartermaster issues the work uniform on
#: day one and each higher tier's dress the day its first rank is reached; the
#: commander may wear any issued one. Officers wear their own tier's uniform
#: automatically, so they earn none. Ribbons are commendations for long,
#: steady service, worn on the service record by the commander and the crew.
#: The companion drone wears its rank only.
REWARDS: Final[tuple[Reward, ...]] = (
    Reward("uniform_deck", "uniform", person=1, agent=None, pet=None),
    Reward("uniform_line", "uniform", person=tier_start("line"), agent=None, pet=None),
    Reward("uniform_command", "uniform", person=tier_start("command"), agent=None, pet=None),
    Reward("uniform_flag", "uniform", person=tier_start("flag"), agent=None, pet=None),
    Reward("ribbon_good_conduct", "ribbon", person=6, agent=4, pet=None),
    Reward("ribbon_meritorious", "ribbon", person=19, agent=16, pet=None),
    Reward("ribbon_distinguished", "ribbon", person=31, agent=27, pet=None),
    Reward("ribbon_fleet_cross", "ribbon", person=47, agent=43, pet=None),
)


def unlocked_rewards(kind: SubjectKind, level: int) -> list[Reward]:
    return [r for r in REWARDS if (at := r.level_for(kind)) is not None and level >= at]


def rewards_between(kind: SubjectKind, before: int, after: int) -> list[Reward]:
    """Rewards newly unlocked when a subject climbs from ``before`` to ``after``."""
    return [
        r for r in REWARDS
        if (at := r.level_for(kind)) is not None and before < at <= after
    ]


# ------------------------------------------------------------------ agent looks

#: The agent level at which each wearable look unlocks
#: (``companion/accessories.json`` ids, the agent card's looks). The
#: maintainer opened every look from the start (2026-10-05); raise a value to
#: turn a look back into a level-up reward. A look an agent already wears is
#: never taken away.
LOOK_UNLOCKS: Final[dict[str, int]] = {
    "sunglasses": 1,
    "cap": 1,
    "headphones": 1,
    "hoodie": 1,
    "lab_coat": 1,
    "cigar": 1,
    "suit": 1,
    "top_hat": 1,
    "tuxedo": 1,
    "crown": 1,
}


def looks_between(before: int, after: int) -> list[str]:
    """Agent looks newly unlocked when an agent climbs from ``before`` to ``after``."""
    return [look for look, at in LOOK_UNLOCKS.items() if before < at <= after]


# ------------------------------------------------------------------ titles

_RANK_BANDS: Final[tuple[tuple[int, str], ...]] = tuple((level, rank) for level, rank, _ in RANKS)

#: Title bands per kind: (first level of the band, title id). Every kind wears
#: the rank ladder, so the bands are the same; the per-kind shape stays so the
#: API can give a kind its own ladder later without a contract change.
TITLES: Final[dict[SubjectKind, tuple[tuple[int, str], ...]]] = {
    "person": _RANK_BANDS,
    "agent": _RANK_BANDS,
    "pet": _RANK_BANDS,
}


def title_for(kind: SubjectKind, level: int) -> str:
    title = TITLES[kind][0][1]
    for start, name in TITLES[kind]:
        if level >= start:
            title = name
    return title


def subject_kind(subject_id: str) -> SubjectKind | None:
    if subject_id == PERSON_ID:
        return "person"
    prefix, sep, rest = subject_id.partition(":")
    if not sep or not rest:
        return None
    if prefix == "agent":
        return "agent"
    if prefix == "pet":
        return "pet"
    return None


def agent_subject(agent_id: str) -> str:
    return f"agent:{agent_id}"


def pet_subject(pet_id: str) -> str:
    return f"pet:{pet_id}"

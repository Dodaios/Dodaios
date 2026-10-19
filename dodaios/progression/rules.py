"""The Dodaios Verse level system's rulebook: pure tables, no I/O.

The Verse is a starship. Three kinds of subject serve aboard and level up:

* ``person`` — the captain, the person at the keyboard (one subject, id ``person``);
* ``agent`` — every Jarvis agent on the society roster, an android of the crew
  (``agent:<agent_id>``);
* ``pet`` — the person's pet from My Pets, the ship's companion, which IS
  Jarvis in the Verse (``pet:<pet_id>``; each pet keeps its own level, the
  active one earns).

XP only ever comes from a rule in :data:`RULES`. A rule names its source, the
subject kind it pays, a fixed amount, an optional cooldown and an optional
daily cap. Server rules are read off real bus events (a finished turn, a
finished task); world rules are small actions aboard the ship that the client
reports and the server still meters. Nothing here calls a model — the
system works with any single key and costs no tokens (AP-21).

The level curve is front-loaded the way long-running progression usually is:
level 2 arrives within the first few actions, level 10 after about a week of
ordinary use, level 50 after several months. Levels climb a naval rank ladder
(:data:`RANKS`) from cadet to admiral, and levels open the captain's suits,
the destinations the helm can set course for, and decorations
(:data:`REWARDS`). ``docs/agent-society/level-system.md`` is the readable
version of this file; the parity test pins the frontend's copy of the ids.
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
    # The captain: talking to Jarvis, giving the crew work, growing the crew.
    XpRule("chat_turn", "person", 5, "server", daily_cap=100),
    XpRule("voice_turn", "person", 5, "server", daily_cap=100),
    XpRule("quest_posted", "person", 15, "server", daily_cap=75),
    XpRule("quest_completed", "person", 20, "server"),
    XpRule("agent_hired", "person", 50, "server"),
    XpRule("mission_completed", "person", 30, "server", daily_cap=150),
    # The captain, aboard the ship.
    XpRule("daily_visit", "person", 25, "world", once_per_ref=True),
    XpRule("deck_discovered", "person", 20, "world", once_per_ref=True),
    XpRule("holodeck_round", "person", 8, "world", cooldown_s=45, daily_cap=80),
    XpRule("holodeck_record", "person", 15, "world", cooldown_s=45, daily_cap=60),
    XpRule("team_briefing", "person", 10, "world", cooldown_s=600, daily_cap=40),
    XpRule("warp_jump", "person", 5, "world", cooldown_s=600, daily_cap=30),
    # The crew: finished work is what counts.
    XpRule("task_done", "agent", 40, "server"),
    XpRule("task_blocked", "agent", 8, "server", daily_cap=40),
    XpRule("quest_done", "agent", 60, "server"),
    XpRule("answered_teammate", "agent", 5, "server", daily_cap=50),
    # The pet is Jarvis: every answer and every hand-off it makes, and the
    # walks it takes beside the captain.
    XpRule("jarvis_answered", "pet", 4, "server", daily_cap=120),
    XpRule("delegated", "pet", 10, "server", daily_cap=100),
    XpRule("walk_together", "pet", 3, "world", cooldown_s=20, daily_cap=60),
)

RULES_BY_SOURCE: Final[dict[str, XpRule]] = {rule.source: rule for rule in RULES}

#: Sources the client may report through ``POST /api/progression/actions``.
WORLD_ACTIONS: Final[frozenset[str]] = frozenset(r.source for r in RULES if r.trigger == "world")


# ------------------------------------------------------------------ ranks

RankTier = Literal["enlisted", "warrant", "officer", "flag"]
RANK_TIERS: Final[tuple[RankTier, ...]] = ("enlisted", "warrant", "officer", "flag")

#: The rank ladder everyone aboard climbs, lowest first: (first level, rank
#: id, tier). The captain, every android and the pet share it, so a rank means
#: the same thing on every name plate. The frontend's copy is
#: ``starship/levels/ranks.ts`` (with the insignia's pips); its names are
#: ``ship.rank.<id>``.
RANKS: Final[tuple[tuple[int, str, RankTier], ...]] = (
    (1, "cadet", "enlisted"),
    (3, "crewman", "enlisted"),
    (5, "specialist", "enlisted"),
    (7, "petty_officer", "enlisted"),
    (10, "chief_petty_officer", "enlisted"),
    (13, "warrant_officer", "warrant"),
    (16, "ensign", "officer"),
    (19, "lieutenant_junior_grade", "officer"),
    (22, "lieutenant", "officer"),
    (26, "lieutenant_commander", "officer"),
    (30, "commander", "officer"),
    (34, "captain", "officer"),
    (38, "commodore", "flag"),
    (42, "rear_admiral", "flag"),
    (46, "vice_admiral", "flag"),
    (50, "admiral", "flag"),
)


# ------------------------------------------------------------------ rewards

Slot = Literal["suit", "destination", "decoration"]
SLOTS: Final[tuple[Slot, ...]] = ("suit", "destination", "decoration")


@dataclass(frozen=True, slots=True)
class Reward:
    #: ``<slot>_<name>``; a destination's name is the helm's destination id.
    reward_id: str
    slot: Slot
    #: The level each subject kind unlocks it at; ``None`` = not for that kind.
    person: int | None
    agent: int | None
    pet: int | None

    def level_for(self, kind: SubjectKind) -> int | None:
        return {"person": self.person, "agent": self.agent, "pet": self.pet}[kind]


#: What a level opens. The captain earns suits for their figure, destinations
#: for the helm and decorations; androids keep the look their owner gave them
#: and earn decorations only; the pet wears its rank on its name plate.
REWARDS: Final[tuple[Reward, ...]] = (
    Reward("suit_field_armor", "suit", person=6, agent=None, pet=None),
    Reward("suit_command_coat", "suit", person=16, agent=None, pet=None),
    Reward("suit_dress_whites", "suit", person=26, agent=None, pet=None),
    Reward("suit_admiral_coat", "suit", person=42, agent=None, pet=None),
    Reward("destination_gas_giant", "destination", person=5, agent=None, pet=None),
    Reward("destination_crimson_nebula", "destination", person=10, agent=None, pet=None),
    Reward("destination_ice_moon", "destination", person=15, agent=None, pet=None),
    Reward("destination_twin_suns", "destination", person=20, agent=None, pet=None),
    Reward("destination_event_horizon", "destination", person=25, agent=None, pet=None),
    Reward("destination_aurora_world", "destination", person=30, agent=None, pet=None),
    Reward("destination_galactic_core", "destination", person=40, agent=None, pet=None),
    Reward("decoration_service_ribbon", "decoration", person=8, agent=3, pet=None),
    Reward("decoration_commendation", "decoration", person=18, agent=16, pet=None),
    Reward("decoration_star_medal", "decoration", person=36, agent=32, pet=None),
    Reward("decoration_legion_of_merit", "decoration", person=47, agent=44, pet=None),
)

#: Where the ship starts; every other destination is a ``destination`` reward.
HOME_DESTINATION: Final[str] = "home"

#: Every destination the helm knows, home first (a ``warp_jump`` names one).
DESTINATION_IDS: Final[tuple[str, ...]] = (HOME_DESTINATION,) + tuple(
    r.reward_id.removeprefix("destination_") for r in REWARDS if r.slot == "destination"
)


def destination_level(destination_id: str) -> int:
    """The captain's level a destination opens at (home is open from the start)."""
    for reward in REWARDS:
        if reward.slot == "destination" and reward.reward_id == f"destination_{destination_id}":
            return reward.person or 1
    return 1


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
#: (``companion/accessories.json`` ids). The maintainer opened every look
#: from the start (2026-10-05); raise a value to turn a look back into a
#: level-up reward. A look an agent already wears is never taken away.
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

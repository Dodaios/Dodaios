"""Prove: the checks a build must pass before it goes live. Pure and deterministic.

The builder proposes, this module decides. Nothing here asks a model, and
nothing the builder writes can change what is checked: every function takes
the finished artefact (or its spec) plus the person's own past turns and
returns a :class:`Proof`. Shadow runs (a routine's or an agent's answer to the
recorded requests) are produced by the builder on a subscription or local
seat, never delivered anywhere, and only their text is judged here.

What each kind must show (docs/self-build.md, "Prove"):

* memory: the learning loop's own evidence rules (a verbatim quote of the
  person, the guard against injection and secrets);
* skill: a replay of the person's past requests through the production skill
  router: it must catch at least two thirds of them and fire on none of the
  person's other recent requests, pass the skill validator, the pre-promote
  lint and the duplicate check, and need only tools the assistant used;
* routine: a calendar schedule that would have run before most of the past
  requests, a prompt grounded in them that asks for nothing outbound, and a
  shadow run that produced an answer;
* agent: a free name, standing instructions without injection or outbound
  duties, a focus made of tools the person's turns used, and shadow answers to
  the recorded requests.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

#: A skill must catch this share of the requests it was built from.
SKILL_RECALL: Final[float] = 2 / 3
#: A routine must have run before this share of the past requests.
ROUTINE_COVER: Final[float] = 2 / 3
#: A routine run counts for a request made within this long after it.
ROUTINE_REACH_MIN: Final[int] = 6 * 60
#: Shortest shadow answer that counts as an answer.
MIN_SHADOW_CHARS: Final[int] = 20

JUDGE: Final[str] = "self_build.judge"

#: Phrases that would make a routine or an agent act outside the computer on
#: the loop's initiative (rule 7). The unattended approval ceiling stops such
#: actions anyway; this keeps them out of a self-built prompt in the first place.
_OUTBOUND: Final = re.compile(
    r"\b(?:send|post|tweet|publish|forward|reply|email|e-mail|text|dm|message|pay|buy|order)"
    r"\b.{0,40}\b(?:e-?mails?|mails?|messages?|tweets?|posts?|slack|whatsapp|telegram|sms"
    r"|customers?|clients?|everyone|contacts?|payment|money)\b"
    r"|\b(?:schick|sende|versende|poste|antworte|kaufe|bezahle|überweise)\w*\b"  # i18n-allow
    r".{0,40}\b(?:e-?mails?|mails?|nachrichten?|kunden|zahlung|geld)\b"  # i18n-allow
    r"|\b(?:env[ií]a|publica|responde|compra|paga)\w*\b.{0,40}\b(?:correos?|mensajes?"  # i18n-allow
    r"|clientes?|pagos?)\b"  # i18n-allow
    r"|\b(?:envi[ae]|publique|responda|compre|pague)\w*\b.{0,40}"  # i18n-allow
    r"\b(?:e-?mails?|mensagens?|clientes?|pagamentos?)\b",  # i18n-allow
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Proof:
    passed: bool
    judge: str
    detail: str

    @classmethod
    def ok(cls, kind: str, detail: str) -> Proof:
        return cls(True, f"{JUDGE}/{kind}", detail)

    @classmethod
    def fail(cls, kind: str, detail: str) -> Proof:
        return cls(False, f"{JUDGE}/{kind}", detail)


def _unsafe(text: str) -> str | None:
    from dodaios.memory.learning.guard import (
        contains_secret,
        hidden_characters,
        instruction_like,
    )

    if hidden_characters(text):
        return "invisible or unassigned characters"
    if instruction_like(text):
        return "instruction-like content"
    if contains_secret(text):
        return "credential-shaped content"
    return None


def outbound(text: str) -> bool:
    return bool(_OUTBOUND.search(text or ""))


def _needed(total: int, share: float) -> int:
    return max(2, math.ceil(total * share)) if total >= 2 else total


# ------------------------------------------------------------------ memory


def memory(spec: dict[str, Any], *, said: list[str], entries: dict[str, list[Any]]) -> Proof:
    """The learning review's own evidence check, applied to one proposed entry."""
    from dodaios.memory.learning.review import validate

    item = {
        "target": spec.get("target") or "memory",
        "operation": "add",
        "text": spec.get("text") or "",
        "evidence": spec.get("evidence") or "",
        "importance": spec.get("importance", 7),
    }
    accepted, rejected = validate([item], user_texts=said, entries=entries)
    if not accepted:
        return Proof.fail("memory", "; ".join(rejected) or "the entry was not accepted")
    return Proof.ok("memory", f"quoted the person: {accepted[0].evidence[:120]!r}")


# ------------------------------------------------------------------ skill


def skill(
    candidate: Any,
    *,
    said: list[str],
    others: list[str],
    installed: list[Any],
    tools_seen: Iterable[str],
) -> Proof:
    """Replay the person's requests through the real router with the skill added."""
    from dodaios.skills.authoring.draft_writer import safe_lint_skill_body
    from dodaios.skills.authoring.service import body_has_instructions
    from dodaios.skills.deduplicator import find_duplicates
    from dodaios.skills.eval_harness import static_registry

    if getattr(candidate, "frontmatter", None) is None:
        return Proof.fail("skill", "the skill file does not parse")
    body = str(getattr(candidate, "body", "") or "")
    if not body_has_instructions(body):
        return Proof.fail("skill", "the body has no instructions")
    findings = safe_lint_skill_body(body)
    if findings:
        return Proof.fail("skill", f"pre-promote lint: {findings[:3]}")
    reason = _unsafe(body + "\n" + str(candidate.frontmatter.description or ""))
    if reason:
        return Proof.fail("skill", reason)
    seen = set(tools_seen)
    stray = [t for t in candidate.frontmatter.requires_tools if t not in seen]
    if stray:
        return Proof.fail("skill", f"needs tools the assistant never used here: {stray[:3]}")
    for left, right, score in find_duplicates([candidate, *installed]):
        if candidate in (left, right):
            other = right if left is candidate else left
            return Proof.fail("skill", f"duplicates the skill {other.name!r} ({score:.2f})")
    registry = static_registry([*installed, candidate])
    # A hit is a request the skill would really capture, not a suggestion
    # the guards veto or a narrow-band hint the model may ignore.
    hits = sum(1 for text in said if _fires(registry, text, candidate.name))
    needed = _needed(len(said), SKILL_RECALL)
    if hits < needed:
        return Proof.fail("skill", f"replay caught {hits} of {len(said)} past requests")
    false_fires = [text for text in others if _fires(registry, text, candidate.name)]
    if false_fires:
        example = false_fires[0][:80]
        return Proof.fail(
            "skill", f"fires on {len(false_fires)} unrelated request(s), e.g. {example!r}"
        )
    return Proof.ok(
        "skill",
        f"replay caught {hits} of {len(said)} past requests and fired on none of "
        f"{len(others)} other ones",
    )


def _fires(registry: Any, text: str, name: str) -> bool:
    from dodaios.skills.eval_harness import route

    decision = route(registry, text)
    return decision.fired and decision.winner == name


def served_by(installed: list[Any], said: list[str]) -> str | None:
    """The installed skill that already catches most of these requests, if any."""
    from collections import Counter

    from dodaios.skills.eval_harness import route, static_registry

    if not installed or not said:
        return None
    registry = static_registry(list(installed))
    routes = [route(registry, text) for text in said]
    winners = Counter(r.winner for r in routes if r.fired)
    winners.pop("", None)
    if not winners:
        return None
    name, count = winners.most_common(1)[0]
    return name if count >= _needed(len(said), SKILL_RECALL) else None


# ------------------------------------------------------------------ routine


def routine(
    spec: dict[str, Any],
    *,
    asked: list[tuple[int, int]],
    stems: frozenset[str],
    shadow: str,
) -> Proof:
    """A calendar routine that would have come before the requests it replaces.

    ``asked`` holds ``(weekday, minute of day)`` of each past request; ``stems``
    the content stems of those requests.
    """
    from dodaios.self_build.miner import stems as stems_of

    schedule = spec.get("schedule")
    if not isinstance(schedule, dict) or str(schedule.get("kind") or "") != "calendar":
        return Proof.fail("routine", "a self-built routine needs a calendar schedule")
    try:
        from dodaios.society.routines import _trigger

        trigger = _trigger(dict(schedule))
    except (ValueError, KeyError, TypeError) as exc:  # the reason is the failed proof
        return Proof.fail("routine", f"invalid schedule: {exc}")
    hour, minute = (int(x) for x in trigger.local_time.split(":"))
    run_at = hour * 60 + minute
    weekdays = set(trigger.weekdays or range(7))
    covered = sum(
        1 for weekday, at in asked if weekday in weekdays and 0 <= at - run_at <= ROUTINE_REACH_MIN
    )
    needed = _needed(len(asked), ROUTINE_COVER)
    if covered < needed:
        return Proof.fail(
            "routine", f"the schedule comes before {covered} of {len(asked)} requests"
        )
    prompt = str(spec.get("prompt") or "")
    if len(prompt.strip()) < 12:
        return Proof.fail("routine", "the prompt is empty")
    reason = _unsafe(prompt)
    if reason:
        return Proof.fail("routine", reason)
    if outbound(prompt):
        return Proof.fail("routine", "the prompt asks to act outside the computer")
    if stems and not (stems_of(prompt) & stems):
        return Proof.fail("routine", "the prompt is not about what the person asked")
    answer = " ".join((shadow or "").split())
    if len(answer) < MIN_SHADOW_CHARS:
        return Proof.fail("routine", "the shadow run produced no answer")
    return Proof.ok(
        "routine",
        f"runs before {covered} of {len(asked)} past requests; shadow answer: {answer[:300]}",
    )


# ------------------------------------------------------------------ agent


def agent(
    spec: dict[str, Any],
    *,
    taken: Iterable[str],
    tools_seen: Iterable[str],
    shadows: list[str],
) -> Proof:
    """A new teammate with a free name, clean instructions and a grounded focus."""
    from dodaios.society.roster import RosterError, _validate_name

    try:
        name = _validate_name(str(spec.get("name") or ""))
    except RosterError as exc:  # the reason is the failed proof
        return Proof.fail("agent", f"invalid name: {exc}")
    if name.casefold() in {str(n).casefold() for n in taken}:
        return Proof.fail("agent", f"the name {name!r} is taken")
    description = str(spec.get("description") or "").strip()
    if not 40 <= len(description) <= 4_000:
        return Proof.fail("agent", "the standing instructions are too short or too long")
    reason = _unsafe(description + "\n" + str(spec.get("title") or ""))
    if reason:
        return Proof.fail("agent", reason)
    if outbound(description):
        return Proof.fail("agent", "the instructions ask to act outside the computer")
    seen = set(tools_seen)
    focus = [str(t) for t in spec.get("focus") or [] if str(t) in seen]
    if not focus:
        return Proof.fail("agent", "the focus names no tool the person's requests used")
    answered = [s for s in shadows if len(" ".join((s or "").split())) >= MIN_SHADOW_CHARS]
    if len(answered) < max(1, len(shadows)):
        return Proof.fail("agent", f"answered {len(answered)} of {len(shadows)} shadow requests")
    return Proof.ok("agent", f"focus {focus}; answered {len(answered)} recorded requests in shadow")


__all__ = ["JUDGE", "Proof", "agent", "memory", "outbound", "routine", "served_by", "skill"]

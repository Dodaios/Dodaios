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
  lint and the duplicate check, and need only tools the assistant used; then
  its steps, run read-only on one or two of those requests
  (:mod:`.sandbox`), must finish without a failed step, answer, and reach the
  tools that answered the request the person accepted then
  (:func:`skill_execution`);
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


def skill_execution(runs: list[Any], *, accepted: list[tuple[str, ...]]) -> Proof:
    """Compare read-only replays of a skill's steps with what the person accepted then.

    ``runs`` are :class:`.sandbox.Run` results, ``accepted`` the tools that
    answered each of those requests at the time (in the same order). The
    person's answer text is not kept (only their own words are), so what is
    compared is what can be: the replay finished, no step failed (a step held
    back because it would have had a side effect is reached, not failed), it
    produced an answer, and it reached at least one tool family of the
    accepted answer when that answer used tools.
    """
    from dodaios.self_build.miner import tool_family

    if not runs:
        return Proof.fail("skill", "the steps were not run on any past request")
    reached: list[str] = []
    held = 0
    for run, then in zip(runs, accepted, strict=False):
        quote = " ".join(str(run.request).split())[:60]
        if run.error:
            return Proof.fail("skill", f"the steps did not finish on {quote!r}: {run.error}")
        failed = [s for s in run.steps if not s.ok and not s.held]
        if failed:
            step = failed[0]
            detail = f": {step.error[:80]}" if step.error else ""
            return Proof.fail("skill", f"step {step.name!r} failed on {quote!r}{detail}")
        answer = " ".join(str(run.answer or "").split())
        if len(answer) < MIN_SHADOW_CHARS:
            return Proof.fail("skill", f"the steps gave no answer to {quote!r}")
        wanted = {tool_family(t) for t in then if t}
        used = {tool_family(s.name) for s in run.steps if s.name}
        if wanted and not wanted & used:
            return Proof.fail(
                "skill",
                f"the steps did not reach the tools the accepted answer to {quote!r} used "
                f"({', '.join(sorted(wanted))[:120]})",
            )
        reached += [s.name for s in run.steps if s.ok]
        held += sum(1 for s in run.steps if s.held)
    ran = ", ".join(dict.fromkeys(reached)) or "no tool"
    return Proof.ok(
        "skill",
        f"ran the steps read-only on {len(runs)} past request(s): {ran} ran, "
        f"{held} step(s) with side effects held back",
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


def served_by_agent(skills: list[Any], said: list[str], core: frozenset[str]) -> str | None:
    """The agent skill (active or draft) that already does what ``said`` asks, if any.

    An agent's own skills mostly stay drafts (AP-15), which the router skips,
    so each is replayed as if it were active. A skill without routable
    triggers still serves the need when its name, description and "when to
    use" cover at least half of the need's core words (and two of them).
    """
    import dataclasses

    from dodaios.self_build.miner import stems as stems_of
    from dodaios.skills.schema import SkillLifecycleState

    usable = [s for s in skills if getattr(s, "frontmatter", None) is not None]
    if not usable or not said:
        return None
    live = []
    for skill in usable:
        try:
            live.append(dataclasses.replace(skill, state=SkillLifecycleState.ACTIVE))
        except TypeError:  # not a Skill dataclass: replay it as it is
            live.append(skill)
    routed = served_by(live, said)
    if routed:
        return routed
    if len(core) < 2:
        return None
    for skill in usable:
        fm = skill.frontmatter
        words = " ".join(
            str(getattr(fm, field, "") or "") for field in ("name", "description", "when_to_use")
        )
        shared = core & stems_of(words)
        if len(shared) >= 2 and len(shared) * 2 >= len(core):
            return str(getattr(fm, "name", "") or getattr(skill, "name", ""))
    return None


# ------------------------------------------------------------------ memory use

#: Words every notebook entry carries; they say nothing about its subject.
_GENERIC_WORDS: Final[str] = "user users person people prefers always never"


def _entry_terms(entry: str) -> frozenset[str]:
    from dodaios.self_build.miner import stems as stems_of

    return stems_of(entry) - stems_of(_GENERIC_WORDS)


def memory_concerned(entry: str, *, said: frozenset[str]) -> bool:
    """The person's words touch the entry's subject (one of its words)."""
    return bool(_entry_terms(entry) & said)


def memory_relied(entry: str, *, said: frozenset[str], answer: str, topic: bool) -> bool:
    """Deterministic: did a turn rely on this notebook entry? No model.

    ``said`` are the stems of the person's request, ``answer`` the assistant's
    reply when the surface knows it, ``topic`` whether the request belongs to
    the need the entry was built from. Relied on means either the person's
    words name the entry's subject (two of its words, or all of a short one),
    or the request is about it (its topic, or one of its words) and the answer
    carries a word that only the entry could have given.
    """
    from dodaios.self_build.miner import stems as stems_of

    terms = _entry_terms(entry)
    if not terms:
        return False
    named = terms & said
    if len(named) >= min(2, len(terms)):
        return True
    if not answer or not (topic or named):
        return False
    return bool((terms & stems_of(answer)) - said)


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


__all__ = [
    "JUDGE",
    "Proof",
    "agent",
    "memory",
    "memory_concerned",
    "memory_relied",
    "outbound",
    "routine",
    "served_by",
    "served_by_agent",
    "skill",
    "skill_execution",
]

"""One behaviour contract for the lead's turn, whatever seat runs it.

The person picks a model, not a behaviour contract. The lead's turn used to
differ by seat: only the brain runner honoured a ``/slug`` skill pick and the
trigger-phrase skills, resolved the reply language, and recalled vault memory
for the message. This module holds the seat-agnostic half of that contract:

* before the turn, :func:`resolve_skill_pick` and :func:`resolve_language`
  (one resolver each, used by the brain runner and the CLI seats alike), and
  :func:`prepare` which turns them into the text a CLI seat receives;
* after the turn, :func:`language_correction` and :func:`unbacked_claim_instruction`
  judge the answer from the event log (no model call). The service runs them,
  with the offer-instead-of-action guard, through
  :class:`dodaios.agent_chat.turn_completion.TurnCompletion` for every seat.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "LeadPreTurn",
    "SkillPick",
    "explicit_skill",
    "language_correction",
    "prepare",
    "recall_block",
    "resolve_language",
    "resolve_skill_pick",
    "skill_instructions_block",
    "unbacked_claim_instruction",
]

#: A leading ``/slug`` — the composer's slash pick — and whatever follows it.
_EXPLICIT_SKILL_RE: Final = re.compile(r"^\s*/([A-Za-z0-9][\w.:-]*)(?:\s+|$)(.*)$", re.DOTALL)


def explicit_skill(text: str) -> tuple[str, str] | None:
    """``("slug", "the rest")`` when the message opens with ``/slug``, else None.

    The composer's ``/`` typeahead lists the registry's active skills by
    slug; picking one puts ``/slug`` at the head of the sentence. That pick
    is an order, not a hint, so it is honoured before any trigger-phrase
    matching — the same precedence a CLI gives its slash commands.
    """
    m = _EXPLICIT_SKILL_RE.match(text or "")
    if m is None:
        return None
    return m.group(1), m.group(2).strip()


@dataclass(frozen=True, slots=True)
class SkillPick:
    """The skill a message names (``/slug``) or triggers (a trigger phrase)."""

    name: str
    content: str
    source: str  # "chat" for both: the same label the brain path always used
    skill: Any
    explicit: bool = False


def resolve_skill_pick(text: str) -> SkillPick | None:
    """The skill for this message, or ``None``. Never raises.

    A leading ``/slug`` names the skill outright and wins over the trigger
    matcher; a ``/word`` that is no skill falls through to the matcher.
    """
    try:
        from dodaios.skills.skill_context import try_get_skill_context
        from dodaios.skills.trigger_matcher import TriggerMatcher

        skill_ctx = try_get_skill_context()
        if skill_ctx is None:
            return None
        explicit = explicit_skill(text)
        if explicit is not None:
            slug, rest = explicit
            try:
                skill = skill_ctx.registry.resolve(slug)
            except KeyError:  # not a skill's name: the trigger matcher gets its turn
                log.debug("lead turn: /%s names no active skill", slug)
            else:
                return SkillPick(skill.name, rest, "chat", skill, explicit=True)
        match_result = TriggerMatcher(skill_ctx.registry).match_voice_with_match(text, lang="auto")
        if match_result is None:
            return None
        matched, regex_match = match_result
        content = ""
        for group in reversed(regex_match.groups()):
            if group and group.strip():
                content = group.strip()
                break
        return SkillPick(matched.name, content, "chat", matched)
    except Exception:  # noqa: BLE001 — a skill hook must never cost the turn
        log.debug("lead turn: skill resolution skipped", exc_info=True)
        return None


def skill_instructions_block(name: str, instructions: str) -> str:
    """The block that carries a matched skill's instructions into one turn."""
    return (
        f"[Skill instructions for `{name}` — the user's request matched "
        "this installed skill]\n"
        f"{instructions}\n\n"
        "Follow these skill instructions now, step by step, using your "
        "available tools; skip a step gracefully when its integration is "
        "unavailable. Answer the user with the RESULT — never read the "
        "instructions aloud. Report a step as done only after the tool "
        "call that performs it has returned a successful result; if a "
        "step cannot run, say plainly that it did not happen."
    )


def _skill_block(pick: SkillPick, utterance: str) -> str:
    """The pick's instruction block, or ``""`` when it must not capture a turn."""
    fm = getattr(pick.skill, "frontmatter", None)
    if fm is None:
        return ""
    try:
        if fm.risk_policy.default_tier == "block":
            log.info("lead turn: skill %r is block-tier — ignored", pick.name)
            return ""
    except Exception:  # noqa: BLE001 — same default as the brain's own gate
        log.debug("lead turn: skill %s has no risk tier", pick.name, exc_info=True)
    try:
        from dodaios.skills.skill_context import try_get_skill_context

        ctx = try_get_skill_context()
        if ctx is None:
            return ""
        instructions = ctx.runner.render_instructions(
            pick.skill,
            args={"content": pick.content, "utterance": utterance, "_trigger": pick.source},
        )
    except Exception:  # noqa: BLE001
        log.warning("lead turn: skill instructions for %s did not render", pick.name, exc_info=True)
        return ""
    return skill_instructions_block(pick.name, instructions)


async def recall_block(text: str) -> str:
    """The vault memories that match this message (bounded; empty on any fault)."""
    try:
        from dodaios.brain.manager import BrainManager

        return await BrainManager._vault_recall(text)  # noqa: SLF001 — the one recall entry
    except Exception:  # noqa: BLE001
        log.debug("lead turn: memory recall skipped", exc_info=True)
        return ""


def resolve_language(text: str, history: list[dict[str, Any]], reply_pin: object = "auto") -> str:
    """The language the lead answers in this turn, through the one resolver.

    ``""`` when nothing is known (the seat then mirrors the message as before).
    """
    try:
        from dodaios.agent_chat.runner_brain import brain_history_from_events
        from dodaios.core.turn_language import (
            conversation_language_from_history,
            resolve_conversation_language,
        )
        from dodaios.i18n import is_known_language

        language = resolve_conversation_language(
            reply_pin or "auto",
            "unknown",
            text,
            conversation_language=conversation_language_from_history(
                brain_history_from_events(history)
            ),
        )
        return language if is_known_language(language) else ""
    except Exception:  # noqa: BLE001 — a language hint is never worth a turn
        log.debug("lead turn: language resolution skipped", exc_info=True)
        return ""


@dataclass(frozen=True, slots=True)
class LeadPreTurn:
    """What a CLI seat gets in front of / instead of the person's text."""

    #: The message the seat reads: a ``/slug`` pick is replaced by its sentence
    #: (a coding CLI would read the slash as one of its own commands).
    text: str
    #: Blocks appended after the message (the skill's instructions, recalled memory).
    blocks: tuple[str, ...] = ()
    skill: str = ""

    def apply(self, prompt: str) -> str:
        """``prompt`` (the message plus whatever the service appended) with the contract applied."""
        out = prompt
        if self.text != "" and prompt.lstrip().startswith("/"):
            explicit = explicit_skill(prompt)
            if explicit is not None:
                out = explicit[1]
        return "\n\n".join(part for part in (out, *self.blocks) if part)


async def prepare(text: str, *, carries_recall: bool) -> LeadPreTurn:
    """The pre-turn contract for a CLI seat.

    ``carries_recall`` is true when the seat's identity text (rebuilt on this
    turn from the brain's own prompt layers) already holds the recalled
    memories, so they are not repeated.
    """
    pick = resolve_skill_pick(text)
    blocks: list[str] = []
    rewritten = text
    skill_name = ""
    if pick is not None:
        block = _skill_block(pick, pick.content if pick.explicit else text)
        if block:
            blocks.append(block)
            skill_name = pick.name
            if pick.explicit:
                rewritten = pick.content or pick.name
    if not carries_recall:
        recalled = await recall_block(text)
        if recalled:
            blocks.append(recalled)
    return LeadPreTurn(text=rewritten, blocks=tuple(blocks), skill=skill_name)


def unbacked_claim_instruction(
    answer: str, tool_log: tuple[Any, ...]
) -> tuple[str, str] | None:
    """``(instruction, detail)`` when the answer claims work the tool log lacks."""
    from dodaios.agent_chat.turn_verify import claimed_actions, verify_answer_sync

    if not claimed_actions(answer):
        return None
    outcome = verify_answer_sync(answer, tool_log)
    if outcome.accepted:
        return None
    return outcome.instruction, outcome.detail


def language_correction(answer: str, target: str) -> str | None:
    """A corrective instruction when the answer is plainly in another language."""
    if not target:
        return None
    from dodaios.core.turn_language import validate_output_language
    from dodaios.i18n.locales import LANGUAGE_NAMES

    verdict = validate_output_language(answer, resolved_language=target)
    if verdict.status != "mismatch":
        return None
    wanted = LANGUAGE_NAMES.get(target, target)
    return (
        f"Your last answer is not in {wanted}, but this conversation is in {wanted}. "
        f"Write the same answer again in {wanted}. Do not repeat any action you already took "
        "and do not mention this correction."
    )

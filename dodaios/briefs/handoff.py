"""The pipeline as a hand-off calls it.

The places that hand a brief on (the workspace orchestrator for threads and
panes, the society's coding threads, the voice composer) differ in what they
know about the recipient and in how they deliver. This module is the part
they share: build the order from what the hand-off knows, run the pass off the
event loop, and work out per recipient what it actually receives (the
assembled text, the effort, the ticket that travels to the job's record).

It reads who is asking from the running chat turn. A turn the person started
gives their own words; a continuation or a background turn carries composed
text, which is nobody's words and is not used as such.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from dodaios.briefs import assemble as assemble_module
from dodaios.briefs import effort as effort_module
from dodaios.briefs import gate, glossary
from dodaios.briefs import log as log_module
from dodaios.briefs import settings as settings_module
from dodaios.briefs.model import (
    WRITER_COMPOSER,
    WRITER_LEAD,
    WRITER_VOICE,
    BriefDraft,
    Order,
    Recipient,
)
from dodaios.briefs.profiles import Profile, profile_for
from dodaios.rsi import domains

__all__ = [
    "PARTS_KEY",
    "WORDS_KEY",
    "Delivery",
    "check",
    "composed",
    "delivery_for",
    "effort_for",
    "enabled",
    "kit_for",
    "learn_words",
    "note_delivery",
    "order_from",
    "receipt",
    "who_asks",
]

log = logging.getLogger(__name__)

#: The argument a hand-off tool uses to pass a brief's parts on unjoined.
PARTS_KEY: Final[str] = "_brief_parts"
#: The argument a tool without a chat turn (a voice call) passes the person's words in.
WORDS_KEY: Final[str] = "_person_words"
#: The longest a hand-off waits for the look-up and the check. Everything
#: inside has its own, shorter limit; this one holds when the machine itself
#: is slow.
PASS_DEADLINE_S: Final[float] = 10.0
#: CLIs whose threads take standing text in a system prompt (``runner_cli``).
_SYSTEM_PROMPT_CLIS: Final[frozenset[str]] = frozenset({"claude", "glm"})


@dataclass(frozen=True, slots=True)
class Delivery:
    """What one agent receives for an order that was let through."""

    text: str
    ticket: gate.Ticket
    cli: str = ""
    model: str = ""
    family: str = ""
    effort: str = ""
    effort_source: str = ""
    job_size: str = ""


def enabled() -> bool:
    """Whether hand-offs pass the pipeline at all.

    With ``[briefs] check = "off"`` a brief goes out exactly as it was
    written: nothing is looked up, checked, assembled or recorded.
    """
    return settings_module.current().check != gate.MODE_OFF


def has_system_prompt(cli: str) -> bool:
    """Whether the app can give this CLI's threads standing text outside the message."""
    return (cli or "").strip().lower() in _SYSTEM_PROMPT_CLIS


def who_asks(args: dict[str, Any]) -> tuple[str, str, str]:
    """``(writer, writer's conversation, the person's own words)`` for a hand-off."""
    from dodaios.core.chat_turn import current_chat_turn

    turn = current_chat_turn.get()
    if turn is not None:
        words = str(turn.user_text or "") if turn.direct_user else ""
        return WRITER_LEAD, str(turn.session_id or ""), words
    return (
        WRITER_VOICE,
        str(args.get("_dispatch_scope") or ""),
        str(args.get(WORDS_KEY) or ""),
    )


def _draft(args: dict[str, Any]) -> BriefDraft:
    parts = args.get(PARTS_KEY)
    if isinstance(parts, dict) and str(parts.get("task") or "").strip():
        return BriefDraft(
            task=str(parts.get("task") or ""),
            context=str(parts.get("context") or ""),
            criteria=str(parts.get("criteria") or ""),
        )
    return BriefDraft(task=str(args.get("prompt") or ""))


def _wishes() -> str:
    try:
        from dodaios.core.brief_wishes import read_wishes

        return read_wishes()
    except Exception:  # noqa: BLE001 - without the wishes the default rules apply
        log.warning("brief hand-off: brief wishes unavailable", exc_info=True)
        return ""


def order_from(
    args: dict[str, Any], recipient: Recipient, *, writer: str = "", session: str = ""
) -> Order:
    """The order a hand-off's arguments describe, for one recipient."""
    asked_by, conversation, words = who_asks(args)
    return Order(
        writer=writer or asked_by,
        draft=_draft(args),
        recipient=recipient,
        person_words=words,
        wishes=_wishes(),
        writer_session=session or conversation,
    )


def _profiles(recipients: Sequence[Recipient]) -> list[Profile]:
    seen: list[Profile] = []
    for recipient in recipients:
        profile = profile_for(recipient.cli, recipient.model)
        if profile not in seen:
            seen.append(profile)
    return seen


async def check(
    args: dict[str, Any],
    recipients: Sequence[Recipient],
    *,
    writer: str = "",
    session: str = "",
) -> gate.Decision:
    """Run the pass for a hand-off; the decision says send or send back.

    ``recipients`` are the agents that would receive the brief; the first one
    stands for the order in the record. Never raises.
    """
    config = settings_module.current()
    first = recipients[0] if recipients else Recipient()
    order = order_from(args, first, writer=writer, session=session)

    gave_up = threading.Event()

    def run(read_repository: bool) -> gate.Decision:
        return gate.review(
            order,
            profiles=_profiles(recipients),
            mode=config.check,
            auto_effort=config.auto_effort,
            standing=config.standing_rules,
            record=config.record,
            read_repository=read_repository,
            abandoned=gave_up if read_repository else None,
        )

    try:
        return await asyncio.wait_for(asyncio.to_thread(run, True), PASS_DEADLINE_S)
    except TimeoutError:
        # The repository could not be read in time (a huge folder, a machine
        # under load). The hand-off does not wait: the brief is checked on its
        # wording alone, and the slow pass, when it ends, counts for nothing.
        gave_up.set()
        log.warning("brief hand-off: repository look-up took too long; checking wording only")
        return await asyncio.to_thread(run, False)


async def kit_for(args: dict[str, Any], recipients: Sequence[Recipient]) -> dict[str, Any]:
    """The kit for a request whose brief is not written yet."""
    first = recipients[0] if recipients else Recipient()
    order = order_from(args, first)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                gate.prepare,
                order,
                profiles=_profiles(recipients),
                auto_effort=settings_module.current().auto_effort,
            ),
            PASS_DEADLINE_S,
        )
    except TimeoutError:
        log.warning("brief hand-off: the kit took too long; the writer briefs without it")
        return {
            "status": "prepared",
            "nothing_sent": True,
            "brief_kit": {},
            "next": "The repository could not be read in time. Write the brief from what "
                    "you know and make the call again without options.prepare.",
        }


def effort_for(
    decision: gate.Decision, cli: str, model: str, *, named: str = ""
) -> effort_module.EffortChoice:
    """The effort one recipient of a decided order starts on."""
    order = decision.order
    draft = order.draft.text()
    return effort_module.choose(
        profile_for(cli, model),
        f"{order.person_words}\n{draft}",
        kind=decision.kind,
        files_named=len(domains.paths_in_text(draft)),
        named=named,
        enabled=settings_module.current().auto_effort,
    )


def delivery_for(
    decision: gate.Decision,
    *,
    cli: str = "",
    model: str = "",
    effort: effort_module.EffortChoice | None = None,
    rules_in_message: bool = False,
    max_chars: int = 0,
) -> Delivery:
    """What one recipient receives: the brief assembled for its model.

    ``rules_in_message`` asks for the standing rules in the text (a
    conversation that gets them no other way). ``max_chars`` is a transport
    limit: what was added around the brief is dropped, rules first, before the
    limit cuts the brief itself.
    """
    profile = profile_for(cli, model)
    rules = rules_in_message and settings_module.current().standing_rules
    text = assemble_module.assemble(
        decision.order, profile, kind=decision.kind, rules_in_message=rules
    )
    if max_chars and len(text) > max_chars and rules:
        text = assemble_module.assemble(decision.order, profile, kind=decision.kind)
    if max_chars and len(text) > max_chars:
        text = decision.order.draft.text()
    choice = effort or decision.kit.effort
    return Delivery(
        text=text,
        ticket=decision.ticket(),
        cli=cli,
        model=model,
        family=profile.key,
        effort=choice.level if choice else "",
        effort_source=choice.source if choice else "",
        job_size=choice.size if choice else "",
    )


def composed(
    text: str,
    *,
    utterance: str,
    folder: str = "",
    recipient_name: str = "",
    session: str = "",
    max_chars: int = 0,
) -> str:
    """A voice composer's brief as it is sent: checked on its wording, then assembled.

    The composer writes on a spoken turn's clock and types into a pane the
    person is looking at, so nothing is sent back and the repository is not
    read here (the composer picked its files itself). The brief is checked and
    recorded like every other, and the person's own sentence is added to it.
    Blocking only for the record; never raises, and an empty brief stays empty.
    """
    if not (text or "").strip() or not enabled():
        return text
    try:
        config = settings_module.current()
        recipient = Recipient(kind="pane", cli=recipient_name, folder=folder)
        order = Order(
            writer=WRITER_COMPOSER,
            draft=BriefDraft(task=text),
            recipient=recipient,
            person_words=utterance,
            wishes=_wishes(),
            writer_session=session,
        )
        decision = gate.review(
            order,
            mode=gate.MODE_NOTE,
            auto_effort=False,
            standing=False,
            record=config.record,
            read_repository=False,
        )
        return delivery_for(decision, cli=recipient_name, max_chars=max_chars).text
    except Exception:  # noqa: BLE001 - the composed brief goes out as it was written
        log.warning("brief hand-off: composed brief not checked", exc_info=True)
        return text


def note_delivery(delivery: Delivery | None, job_id: str, *, thread_id: str = "") -> None:
    """Record that a delivery went out under ``job_id``; never raises."""
    if delivery is None or not job_id or not settings_module.current().record:
        return
    store = log_module.get_log()
    if store is None:
        return
    try:
        store.note_delivery(
            delivery.ticket.brief_id,
            job_id,
            thread_id=thread_id,
            cli=delivery.cli,
            model=delivery.model,
            family=delivery.family,
            effort=delivery.effort,
            effort_source=delivery.effort_source,
            job_size=delivery.job_size,
            sent_chars=len(delivery.text),
        )
    except Exception:  # noqa: BLE001 - the record never holds a hand-off back
        log.warning("brief hand-off: delivery not recorded", exc_info=True)


def receipt(decision: gate.Decision, deliveries: Sequence[Delivery] = ()) -> dict[str, Any]:
    """What a hand-off's result says about the brief it sent."""
    out: dict[str, Any] = {"brief_id": decision.brief_id}
    remarks = decision.remarks()
    if remarks:
        out["check_found"] = remarks
        if decision.revised:
            out["note"] = "Sent as revised; these points were still found."
    efforts = sorted({d.effort for d in deliveries if d.effort and d.effort_source == "job_size"})
    if efforts and decision.kit.effort is not None:
        out["effort"] = {
            "level": ", ".join(efforts),
            "why": decision.kit.effort.reason,
            "chosen_by": "job size, because none was named",
        }
    return out


def learn_words(folder: str, resolved: Any) -> int:
    """Store what the writer says the person's words stand for; the number stored."""
    if not folder or not isinstance(resolved, list):
        return 0
    stored = 0
    for row in resolved[:12]:
        if not isinstance(row, dict):
            continue
        try:
            if glossary.learn(folder, str(row.get("said") or ""), str(row.get("means") or "")):
                stored += 1
        except Exception:  # noqa: BLE001 - a word that cannot be stored is only not remembered
            log.warning("brief hand-off: glossary entry not stored", exc_info=True)
    return stored

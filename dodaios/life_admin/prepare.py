"""Preparation: the next step for an item, written down and never taken.

A draft is a stored proposal: a reply or booking mail, a shopping list, a
calendar hold, a gift idea list. This module has no way to send, book, buy or
change anything. A draft only ever leaves the ledger when the owner asks the
assistant to act on it, and that action goes through the normal approval
card with its exact preview. Nothing here calls a model.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from .model import Item, clean

#: ``Draft.kind`` values.
MAIL: Final[str] = "mail"
LIST: Final[str] = "list"
HOLD: Final[str] = "calendar_hold"
IDEAS: Final[str] = "gift_ideas"

_HOW: Final[str] = (
    "Nothing has been sent or booked. Ask the assistant to act on this draft and you will see "
    "the exact message or entry first; it only goes ahead after your yes."
)

_TEXT: Final[dict[str, dict[str, str]]] = {
    "en": {
        "book_subject": "Appointment request",
        "book_body": (
            "Hello,\n\nI would like to book an appointment ({what}). Could you offer me a few "
            "possible times?\n\nThank you and best regards"
        ),
        "renew_subject": "Question about my renewal: {what}",
        "renew_body": (
            "Hello,\n\nregarding \"{what}\": could you confirm the current terms, the renewal "
            "date and until when I can still cancel or change the plan?\n\nThank you and best "
            "regards"
        ),
        "follow_subject": "Following up: {what}",
        "follow_body": (
            "Hello,\n\nI am following up on \"{what}\". Is there anything you still need from "
            "me?\n\nBest regards"
        ),
        "greeting": "Happy birthday, {who}! Wishing you a wonderful day.",
        "hold_title": "{what}",
        "no_ideas": "No saved likes for {who} yet. Tell me what they enjoy and I will remember it.",
        "likes": "Known likes and notes about {who}",
    },
    "de": {
        "book_subject": "Terminanfrage",
        "book_body": (
            "Guten Tag,\n\nich möchte gern einen Termin vereinbaren ({what}). Könnten Sie mir "
            "ein paar mögliche Zeiten nennen?\n\nVielen Dank und freundliche Grüße"
        ),
        "renew_subject": "Frage zu meiner Verlängerung: {what}",
        "renew_body": (
            "Guten Tag,\n\nzu \"{what}\": Könnten Sie mir die aktuellen Bedingungen, das "
            "Verlängerungsdatum und die letzte Kündigungs- oder Änderungsmöglichkeit "
            "bestätigen?\n\nVielen Dank und freundliche Grüße"
        ),
        "follow_subject": "Nachfrage: {what}",
        "follow_body": (
            "Guten Tag,\n\nich melde mich zu \"{what}\". Fehlt Ihnen noch etwas von mir?\n\n"
            "Freundliche Grüße"
        ),
        "greeting": "Alles Gute zum Geburtstag, {who}! Einen wunderschönen Tag!",
        "hold_title": "{what}",
        "no_ideas": "Zu {who} sind noch keine Vorlieben gespeichert. Sag mir, was die Person "
        "mag, dann merke ich es mir.",
        "likes": "Bekannte Vorlieben und Notizen zu {who}",
    },
}


def _t(lang: str) -> dict[str, str]:
    return _TEXT.get(lang, _TEXT["en"])


def _recipient(item: Item) -> str:
    """Where a reply would go: the sender of the mail the item came from."""
    sender = str(item.evidence.get("sender") or "")
    if "<" in sender and ">" in sender:
        return sender[sender.index("<") + 1:sender.index(">")].strip()
    return sender.strip() if "@" in sender else ""


def _hold(item: Item, days_before: int = 0) -> dict[str, Any]:
    return {"title": clean(item.title), "date": item.due.isoformat() if item.due else None,
            "days_before": days_before}


def build_draft(
    item: Item,
    *,
    lang: str = "en",
    preferences: Callable[[str], list[str]] | None = None,
) -> dict[str, Any]:
    """The prepared next step for ``item``. ``preferences(name)`` returns saved likes."""
    words = _t(lang)
    what = clean(item.title, 80)
    draft: dict[str, Any] = {"requires_approval": True, "sent": False, "how": _HOW, "lang": lang}
    kind = item.kind
    if kind == "birthday":
        who = clean(item.subject or item.title, 60)
        likes = [clean(x, 160) for x in (preferences(who) if preferences else [])]
        lines = likes or [words["no_ideas"].format(who=who)]
        draft.update(
            kind=IDEAS, title=words["likes"].format(who=who), lines=lines,
            message=words["greeting"].format(who=who),
        )
    elif kind == "appointment":
        draft.update(
            kind=MAIL, to=_recipient(item), subject=words["book_subject"],
            body=words["book_body"].format(what=what), hold=_hold(item),
        )
    elif kind == "renewal":
        draft.update(
            kind=MAIL, to=_recipient(item), subject=words["renew_subject"].format(what=what),
            body=words["renew_body"].format(what=what), hold=_hold(item, days_before=3),
        )
    elif kind == "follow_up" and item.evidence.get("type") == "mail":
        draft.update(
            kind=MAIL, to=_recipient(item), subject=words["follow_subject"].format(what=what),
            body=words["follow_body"].format(what=what),
        )
    elif kind == "shopping":
        draft.update(kind=LIST, title=what, lines=[what])
    else:  # a bill, a document deadline, an open loop: a hold in the calendar
        draft.update(kind=HOLD, hold=_hold(item, days_before=2 if kind == "bill" else 3))
    return draft


def summary(draft: dict[str, Any], limit: int = 600) -> str:
    """The draft in a few lines for the digest and the list."""
    kind = draft.get("kind")
    if kind == MAIL:
        to = f" to {draft['to']}" if draft.get("to") else ""
        return clean(f"mail draft{to}: {draft.get('subject', '')} | {draft.get('body', '')}", limit)
    if kind == IDEAS:
        return clean(f"gift ideas: {'; '.join(draft.get('lines', []))}", limit)
    if kind == LIST:
        return clean(f"shopping list: {'; '.join(draft.get('lines', []))}", limit)
    hold = draft.get("hold") or {}
    when = hold.get("date") or "no date"
    return clean(f"calendar hold: {hold.get('title', '')} on {when}", limit)

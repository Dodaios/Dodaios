"""The one browser step a person confirms: the click that commits something.

Reading, searching, navigating and filling a form run without a card. What
asks is the control that finally cancels, buys, books, sends, deletes or
publishes: the browser works up to it, the person sees what exactly is about
to be clicked and where, and a yes runs exactly that click.

The decision is made from the control itself (its own label, its tag, the
dialog or form around it), which the browser worker reads from the page
(``commit_target.py``). It is never made from the wording of the task: a task
that says "do not book anything" is a read, and a keyword in it used to gate
the whole run before it started.

Pure functions, no IO: the action bridge (``bridge.py``) asks them once per
proposed action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

__all__ = [
    "COMMIT_VERB",
    "CommitMemory",
    "CommitStep",
    "PAYMENT_KIND",
    "blocker_hint",
    "commit_step",
    "payment_step",
]

#: The verb the agent's approval rules see for a committing click
#: (``core:browser:commit`` in ``always_allow`` / ``require_approval``).
COMMIT_VERB: Final[str] = "commit"

#: The label the worker gives an Enter key in a message box (``commit_target.py``).
KEY_LABEL: Final[str] = "Enter"
#: The kind of step that types a card or bank account into a page (``payment_step``).
PAYMENT_KIND: Final[str] = "payment_details"
#: Actions that type text into a field.
_INPUTS: Final[frozenset[str]] = frozenset({"input", "input_text"})

#: Browser actions that press a control or submit what is focused.
_CLICKS: Final[frozenset[str]] = frozenset(
    {"click", "click_element_by_index", "browser_window_click"}
)
_KEYS: Final[frozenset[str]] = frozenset({"send_keys", "browser_window_key"})

#: Labels that back out of something; never a commit, whatever surrounds them.
_DISMISS: Final[re.Pattern[str]] = re.compile(
    r"^(cancel|close|back|no|not now|never mind|dismiss|skip|go back|keep (my )?"
    r"(subscription|membership|plan)|"
    r"abbrechen|schließen|zurück|nein|nicht jetzt|später|überspringen|"  # i18n-allow
    r"abo behalten|mitgliedschaft behalten)$",  # i18n-allow: page labels
    re.I,
)

#: What a committing control says, by kind. English verbs must open the label
#: ("Send", "Buy now"); a phrase or a German verb may stand anywhere in it
#: ("Abo kündigen"), because German puts the verb last.  # i18n-allow
_KINDS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        # Before "delete" and "cancel": ending the account itself always asks
        # (``action_policy.commit_severity``).
        "close_account",
        re.compile(
            r"\b(close|delete|deactivate|terminate|cancel) (my |your |the )?account\b|"
            r"\b(konto|account) (löschen|schließen|kündigen|deaktivieren)\b",  # i18n-allow
            re.I,
        ),
    ),
    (
        # Granting a site or app access to the person's account (an OAuth
        # consent screen) always asks.
        "authorize",
        re.compile(
            r"^(authorize|authorise|grant access|allow access)\b|"
            r"\b(autorisieren|zugriff (erlauben|gewähren))\b",  # i18n-allow: page labels
            re.I,
        ),
    ),
    (
        # Before "send": a money transfer always asks, a message by mode.
        "transfer",
        re.compile(
            r"^(transfer|wire)\b|\bsend (money|payment|funds)\b|"
            r"\bconfirm (the )?(transfer|payment)\b|"
            r"\b(überweisen|überweisung (ausführen|bestätigen|absenden)|"  # i18n-allow
            r"geld senden)\b",  # i18n-allow: page labels
            re.I,
        ),
    ),
    (
        "cancel",
        re.compile(
            r"\b(cancel|end|terminate|stop)\b.{0,30}\b(subscription|membership|plan|trial|"
            r"order|booking|reservation|contract|renewal|auto-?renew\w*)\b|^unsubscribe\b|"
            r"\b(kündigen|kündigung|abbestellen|stornieren|abo beenden|"  # i18n-allow
            r"mitgliedschaft beenden)\b",  # i18n-allow: page labels
            re.I,
        ),
    ),
    (
        "buy",
        re.compile(
            r"^(buy|purchase|pay|subscribe|upgrade|donate|checkout|order)\b|"
            r"\b(place (your |the |my )?order|complete (your |the |my )?(purchase|order)|"
            r"buy now|pay now|order now|start (your |my )?(free )?trial)\b|"
            r"\b(kaufen|bezahlen|zahlungspflichtig|kostenpflichtig|bestellen|"  # i18n-allow
            r"abonnieren|spenden)\b",  # i18n-allow: page labels
            re.I,
        ),
    ),
    (
        "book",
        re.compile(r"^(book|reserve)\b|\b(buchen|reservieren)\b", re.I),  # i18n-allow
    ),
    (
        "send",
        re.compile(
            r"^(send|submit|reply)\b|"
            r"\b(senden|absenden|abschicken|antworten)\b",  # i18n-allow
            re.I,
        ),
    ),
    (
        "publish",
        re.compile(
            r"^(post|publish|tweet|share)\b|\b(posten|veröffentlichen|teilen)\b",  # i18n-allow
            re.I,
        ),
    ),
    (
        "delete",
        re.compile(
            r"^(delete|remove|erase|deactivate)\b|"
            r"\b(löschen|entfernen|deaktivieren)\b",  # i18n-allow
            re.I,
        ),
    ),
    (
        "accept",
        re.compile(
            r"^(accept|agree|i agree|sign up|register|create (an |my )?account)\b|"
            r"\b(akzeptieren|zustimmen|registrieren|konto erstellen)\b",  # i18n-allow
            re.I,
        ),
    ),
)

#: A plain yes: it commits only what the dialog around it is about. "Next" and
#: "Continue" are steps of a form and never ask; its last step has a label of
#: its own.
_AFFIRM: Final[re.Pattern[str]] = re.compile(r"^(yes|ok|okay|ja)\b", re.I)  # i18n-allow
#: "Confirm" is a commit by its own meaning, with or without a dialog.
_CONFIRM: Final[re.Pattern[str]] = re.compile(
    r"^(confirm|bestätigen)\b|\bbestätigen$", re.I  # i18n-allow
)
#: A cookie or consent banner is answered by the worker itself (``consent_walls.py``).
_CONSENT: Final[re.Pattern[str]] = re.compile(
    r"cookie|consent|datenschutz|privacy", re.I  # i18n-allow
)
#: A search field's Enter looks something up; it commits nothing.
_SEARCH: Final[re.Pattern[str]] = re.compile(
    r"search|such|find|filter|query|\bq\b", re.I  # i18n-allow
)

_LABEL_CHARS: Final[int] = 80
_CONTEXT_CHARS: Final[int] = 280


@dataclass(frozen=True, slots=True)
class CommitStep:
    """One committing control, as the approval card names it."""

    kind: str
    label: str
    host: str
    url: str
    context: str

    @property
    def is_key(self) -> bool:
        """The step is an Enter key in a message box, not a click on a control."""
        return self.label == KEY_LABEL

    @property
    def severity(self) -> str:
        """``ask`` (by mode) or ``confirm`` (every mode, Bypass too): ``action_policy``."""
        from dodaios.safety.action_policy import commit_severity

        return str(commit_severity(self.kind))

    @property
    def summary(self) -> str:
        """What is about to be clicked, where, and what the page says about it."""
        where = f" on {self.host}" if self.host else ""
        # A key press has no button to name (``KEY_LABEL``).
        if self.kind == PAYMENT_KIND:
            line = f'Enter payment details into "{self.label}"{where}'
        elif self.is_key:
            line = f"Press Enter{where}"
        else:
            line = f'Click "{self.label}"{where}'
        if self.context and self.context.lower() != self.label.lower():
            line += f": {self.context}"
        return line

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "label": self.label,
            "host": self.host,
            "url": self.url,
            "context": self.context,
            "summary": self.summary,
            "severity": self.severity,
        }


def _clean(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _kind_of(text: str) -> str:
    for kind, pattern in _KINDS:
        if pattern.search(text):
            return kind
    return ""


def _is_plain_link(target: dict[str, Any]) -> bool:
    """A link that only opens another page: by convention it changes nothing."""
    if str(target.get("tag") or "").lower() != "a":
        return False
    if str(target.get("role") or "").lower() in {"button", "menuitem"}:
        return False
    href = str(target.get("href") or "").strip().lower()
    return bool(href) and not href.startswith(("#", "javascript:"))


def commit_step(
    name: str, parameters: dict[str, Any], target: Any, url: str = ""
) -> CommitStep | None:
    """The commit this action is, or ``None`` for ordinary page work.

    ``target`` is what the worker read about the control the action presses:
    ``{tag, type, role, href, label, context, field, in_dialog}``. Without it (an older
    worker, a control that is gone) nothing can be said about the click and it
    runs as page work, as every click did before.
    """
    if not isinstance(target, dict):
        return None
    if name in _KEYS:
        keys = str(parameters.get("keys") or parameters.get("key") or "")
        if "enter" not in keys.lower():
            return None
        # Enter presses the form's own submit control; a search box has none
        # worth asking about.
        if _SEARCH.search(" ".join(str(target.get(k) or "") for k in ("field", "type", "role"))):
            return None
    elif name not in _CLICKS:
        return None
    label = _clean(target.get("label"), _LABEL_CHARS)
    if not label or _DISMISS.match(label) or _is_plain_link(target):
        return None
    context = _clean(target.get("context"), _CONTEXT_CHARS)
    kind = _kind_of(label)
    if not kind and name in _KEYS and str(target.get("type") or "") == "composer":
        # Enter in a message box with text in it sends that text.
        kind = "send"
    if not kind and _CONFIRM.search(label):
        kind = _kind_of(context) or "confirm"
    if not kind and _AFFIRM.match(label) and target.get("in_dialog"):
        kind = _kind_of(context)
    if not kind:
        return None
    if kind == "accept" and _CONSENT.search(f"{label} {context}"):
        return None
    # The card quotes what the page says about the step: a dialog's question,
    # or the message an Enter key is about to send. A form's text is only its
    # field labels ("Name: Phone: E-mail:"), which says nothing about it.
    quoted = bool(target.get("in_dialog")) or str(target.get("type") or "") == "composer"
    return CommitStep(
        kind=kind,
        label=label,
        host=(urlsplit(url).hostname or "").removeprefix("www."),
        url=url,
        context=context if quoted else "",
    )


def payment_step(
    name: str, parameters: dict[str, Any], target: Any, url: str = ""
) -> CommitStep | None:
    """Typing a card or bank account into a page, or ``None`` for any other typing.

    Read from the field (its autocomplete, name and label, ``commit_target``)
    and from what is typed (13 to 19 digits is a card number on any field).
    The card never quotes what is typed.
    """
    if name not in _INPUTS:
        return None
    from dodaios.safety.action_policy import input_risk

    if input_risk(target, str(parameters.get("text") or "")) is None:
        return None
    described = target if isinstance(target, dict) else {}
    label = _clean(described.get("label") or described.get("field"), _LABEL_CHARS)
    return CommitStep(
        kind=PAYMENT_KIND,
        label=label or "payment field",
        host=(urlsplit(url).hostname or "").removeprefix("www."),
        url=url,
        context="",
    )


class CommitMemory:
    """What the person already answered in this run.

    One cancellation is often two clicks on one page ("Cancel subscription",
    then "Yes, cancel" in the dialog it opens). The person's yes covers the
    same kind of step on the same page for a short while, so one action is one
    card; another page, another kind, or a later moment asks again.
    """

    def __init__(self, *, window_s: float = 120.0) -> None:
        self._window = window_s
        self._approved: dict[tuple[str, str], float] = {}
        self.record: list[dict[str, str]] = []

    @staticmethod
    def _key(step: CommitStep) -> tuple[str, str]:
        parts = urlsplit(step.url)
        return step.kind, f"{parts.hostname or ''}{parts.path}"

    def covers(self, step: CommitStep, now: float) -> bool:
        at = self._approved.get(self._key(step))
        return at is not None and now - at <= self._window

    def note(self, step: CommitStep, *, approved: bool, now: float, by: str = "user") -> None:
        if approved:
            self._approved[self._key(step)] = now
        self.record.append(
            {**step.to_dict(), "decision": "approved" if approved else "declined", "by": by}
        )


#: Why a run that did not finish needs the person, read from its own report.
_BLOCKERS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "human_verification",
        re.compile(r"captcha|human verification|verify (that )?you are (a )?human|robot", re.I),
    ),
    (
        "two_factor",
        re.compile(
            r"\b2fa\b|two[- ]factor|two[- ]step|verification code|authenticat(or|ion) (app|code)|"
            r"one[- ]time (code|password)|\botp\b|security code|passkey",
            re.I,
        ),
    ),
    (
        "login",
        re.compile(
            r"sign[- ]?in|log[- ]?in|logged out|not logged in|not signed in|password|"
            r"credentials|authenticate",
            re.I,
        ),
    ),
)


def blocker_hint(
    result: dict[str, Any], *, takeover_tool: str, login_tool: str
) -> dict[str, str] | None:
    """The next step for a run that stopped at something only the person can pass.

    A run that ends at a login, a second factor or a human check is not a dead
    end: the browser stays on that page, and the person either takes it over
    or stores a login. The hint names the tool for that, so the caller acts on
    it instead of handing the person a link.
    """
    if result.get("ok"):
        return None
    report = " ".join(
        str(part or "")
        for part in (result.get("final_result"), result.get("error"), *(result.get("errors") or []))
    )
    for blocker, pattern in _BLOCKERS:
        if not pattern.search(report):
            continue
        urls = result.get("urls") or []
        page = str(urls[-1]) if urls else ""
        if blocker == "login":
            do = (
                f"The browser is waiting on the sign-in page. Call {takeover_tool} so the "
                f"person signs in there themselves, or {login_tool} to store a login for "
                "this site; then call society_browser again to continue from that page."
            )
        else:
            do = (
                f"The browser is waiting at this check. Call {takeover_tool} and say what "
                "the person has to do on the page (enter the code, solve the check); "
                "then call society_browser again to continue from that page."
            )
        return {"blocked_on": blocker, "page": page, "next_action": do}
    return None

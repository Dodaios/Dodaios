"""Deterministic navigational oracle for follow-a-link missions (M5 regression).

The v2 completion judge is LLM-driven: it looks at one screenshot and answers
``{"done": bool, "proof": str}``. For a mission whose GOAL explicitly asks to
follow a link and finish on the DESTINATION page, a screenshot-only judge has
a systematic blind spot: the source page and the destination page look alike
enough that "not example.com anymore" reads as failure, while "still on the
source with the link visible" reads as progress. The M5 run
(OPR-20261114-01) hit exactly that: after ``click_element("Learn more")`` the
browser visibly reached ``iana.org/help/example-domains`` and the independent
judge still rejected ``done`` because the page "was not example.com and had
no Learn more link".

This module adds a small, auditable, deterministic corroboration layer for
that ONE named regression. It never invents success:

* It only applies when the goal is the M5 shape (source ``example.com`` +
  a "Learn more" link step + finishing on the destination page). Every other
  goal returns ``applicable=False`` and the LLM judge stays the sole gate, so
  this cannot become a generic "any external page counts as done" shortcut.
* ``done=True`` requires BOTH links of the evidence chain: the action history
  must show the link click actually executed, AND the current observation
  (foreground window title + clickable labels) must verifiably show the
  expected destination (``iana.org/help/example-domains`` cues). One side
  alone is never enough.
* Intermediate states (still on the source with the link visible), wrong
  destinations, navigation failures and spoofed pages all return
  ``done=False`` with a reason, preserving the strict gate's rejection of
  premature finish, wrong destination and navigation failure.

No screenshots, secrets or tokens are read or logged here — only the goal
text, the engine's action history lines and the already-collected
accessibility labels / window title.
"""

from __future__ import annotations


#: The one named regression this oracle covers. Kept as module constants so
#: the scope is visible at a glance; this is intentionally NOT a generic
#: "source -> any destination" rule.
M5_SOURCE_HOST = "example.com"
M5_LINK_LABEL = "learn more"
M5_DEST_HOST = "iana.org"
M5_DEST_PATH = "/help/example-domains"

#: Destination cues that must appear in the CURRENT observation before the
#: oracle confirms arrival. A verifiable arrival requires the full
#: ``iana.org`` host (normally from the address-bar field value) AND a
#: destination content cue. A bare ``iana`` string without the host (for
#: example a page TITLE that merely mentions IANA while the URL is
#: elsewhere) is weak evidence and never confirms arrival on its own —
#: this closes the title-spoof hole where a same-title page could credit a
#: wrong destination.
_STRONG_HOST_CUE = "iana.org"
_WEAK_HOST_CUE = "iana"
_DEST_CONTENT_CUES = (
    "example domains",
    "help/example-domains",
    "example-domains",
)

#: Source cues meaning "still on the intermediate page, link not yet
#: followed". Used to distinguish intermediate from final states.
_SOURCE_CUES = ("example domain", "example.com")


def _norm(text: str) -> str:
    return (text or "").strip().casefold()


def is_m5_navigation_goal(goal: str) -> bool:
    """Whether ``goal`` is the M5 follow-the-link shape.

    Requires all three: the source host, the link label and a
    destination-page expectation ("destination" / "finish once ... shown").
    A goal that only says "open example.com" without a link step is NOT a
    navigation goal and stays entirely with the LLM judge.
    """
    g = _norm(goal)
    if M5_SOURCE_HOST not in g or M5_LINK_LABEL not in g:
        return False
    return (
        "destination" in g
        or ("finish" in g and "shown" in g)
        or ("click" in g and "link" in g)
    )


def history_shows_link_click(history: list[str] | tuple[str, ...]) -> bool:
    """Whether the engine history shows the M5 link click executed OK.

    Matches the engine's own history line shape
    (``step N: click_element('Learn more') -> OK ...``), case-insensitively.
    A FAILED or REFUSED line does not count — the link was not followed.
    """
    for line in history or ():
        low = _norm(str(line))
        if "click_element" in low and M5_LINK_LABEL in low and "-> ok" in low:
            return True
    return False


def _combined_text(
    labels: list[str] | tuple[str, ...] | None,
    window_title: str | None,
    field_hint: str | None = None,
) -> str:
    return (
        _norm(window_title or "")
        + "\n"
        + "\n".join(_norm(str(label)) for label in (labels or []))
        + "\n"
        + _norm(field_hint or "")
    )


def destination_evidence(
    labels: list[str] | tuple[str, ...] | None,
    window_title: str | None,
    field_hint: str | None = None,
) -> str:
    """Destination proof string, or ``""`` when the destination is absent.

    Requires the verifiable ``iana.org`` host AND a destination content cue
    across the combined observation text (title + clickable labels +
    address-bar field values). A bare ``iana`` mention without ``iana.org``
    returns ``""`` so a spoofed title alone never counts as arrival.
    Returns the matched evidence snippet for the caller's proof line; empty
    means "destination not verifiable".
    """
    combined = _combined_text(labels, window_title, field_hint)
    has_host = _STRONG_HOST_CUE in combined
    has_content = any(cue in combined for cue in _DEST_CONTENT_CUES)
    if has_host and has_content:
        return "IANA Example Domains destination (iana.org/help/example-domains cues)"
    return ""


def has_weak_destination_cues(
    labels: list[str] | tuple[str, ...] | None,
    window_title: str | None,
    field_hint: str | None = None,
) -> bool:
    """Whether only weak destination cues are present (spoof-sensitive).

    True when the observation mentions ``iana`` and destination content but
    the verifiable ``iana.org`` host is absent — for example a page title
    that contains IANA while the address bar points elsewhere.
    """
    combined = _combined_text(labels, window_title, field_hint)
    if _STRONG_HOST_CUE in combined:
        return False
    has_weak_host = _WEAK_HOST_CUE in combined
    has_content = any(cue in combined for cue in _DEST_CONTENT_CUES)
    return bool(has_weak_host and has_content)


def still_on_source(
    labels: list[str] | tuple[str, ...] | None,
    window_title: str | None,
) -> bool:
    """Whether the observation still shows the intermediate source page."""
    combined = _norm(window_title or "") + "\n" + "\n".join(
        _norm(str(label)) for label in (labels or [])
    )
    if M5_LINK_LABEL in combined and any(cue in combined for cue in _SOURCE_CUES):
        return True
    return False


def navigation_oracle_verdict(
    goal: str,
    history: list[str] | tuple[str, ...],
    labels: list[str] | tuple[str, ...] | None,
    window_title: str | None,
    field_hint: str | None = None,
) -> tuple[bool, bool, str]:
    """Deterministic verdict for the M5 navigation regression.

    Returns ``(applicable, done, proof)``:

    * ``(False, False, "")`` — not the M5 shape; the LLM judge decides alone.
    * ``(True, True, proof)`` — link click observed AND the verifiable
      ``iana.org`` destination evidenced: the mission reached the expected
      destination.
    * ``(True, False, reason)`` — the M5 shape but the chain is incomplete:
      still on the source, wrong destination, navigation failure or spoofed
      success. The reason names which link of the chain is missing.
    """
    if not is_m5_navigation_goal(goal or ""):
        return (False, False, "")
    link_clicked = history_shows_link_click(history or [])
    dest_proof = destination_evidence(labels, window_title, field_hint)
    if link_clicked and dest_proof:
        return (
            True,
            True,
            dest_proof + " after observed click on 'Learn more'",
        )
    if not link_clicked:
        if still_on_source(labels, window_title):
            return (
                True,
                False,
                "still on the Example Domain source page with the 'Learn more' "
                "link visible and no observed click on it; the destination "
                "page is not shown",
            )
        return (
            True,
            False,
            "no observed click on the 'Learn more' link; "
            "destination arrival cannot be credited",
        )
    if still_on_source(labels, window_title):
        return (
            True,
            False,
            "still on the Example Domain source page with the 'Learn more' "
            "link visible; the destination page is not shown",
        )
    if link_clicked and has_weak_destination_cues(labels, window_title, field_hint):
        return (
            True,
            False,
            "destination cues without verifiable iana.org address "
            "(title/labels mention IANA but the address bar does not show "
            "iana.org); URL not confirmed, keeping the strict gate",
        )
    return (
        True,
        False,
        "destination iana.org/help/example-domains not verifiable in the "
        "current observation (missing host/content cues)",
    )

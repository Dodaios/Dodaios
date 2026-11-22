"""How Dodaios hands work to a coding agent: one pipeline for every writer.

A brief is the only thing a coding agent gets from the conversation it came out
of. Four places write one (the lead, the live voice model, the voice composer,
a society agent), and each used to follow its own copy of a text rule. This
package is what they share instead, in the order an order passes through it:

1. **Before the brief is written** (``kit``): what the repository says about
   the request (``repo_facts``), what the person's words stand for
   (``glossary``) and where they leave a fact open (``terms``), which facts
   make a brief precise in this field of work (``lenses``), and what is still
   unanswered (``gaps``).
2. **The brief itself**: a checkable end (``done``), the receiving model's way
   of being written to (``profiles``), the effort the job calls for
   (``effort``), and the rules that hold for every order, given once
   (``standing``).
3. **Before it leaves** (``gate``): the check (``lint``); a brief with a fault
   goes back to its writer once. Then the last assembly (``assemble``).
4. **After the agent reports** (``acceptance``): each done-when point held
   against what the run left behind.
5. **Throughout** (``log``): every order and its outcome, so a change to any
   of the above can be measured on real orders.

``docs/agent-briefs.md`` describes it for people.
"""

from __future__ import annotations

from dodaios.briefs.model import (
    WRITER_COMPOSER,
    WRITER_LEAD,
    WRITER_SOCIETY,
    WRITER_VOICE,
    BriefDraft,
    Finding,
    Order,
    Recipient,
)

__all__ = [
    "WRITER_COMPOSER",
    "WRITER_LEAD",
    "WRITER_SOCIETY",
    "WRITER_VOICE",
    "BriefDraft",
    "Finding",
    "Order",
    "Recipient",
]

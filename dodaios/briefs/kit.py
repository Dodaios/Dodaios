"""Everything a brief writer should know before it writes, gathered in one read.

"Look it up first, then brief": the kit is that look. For one request and one
recipient it holds what the repository says (files that fit, the project's own
checks), what the person's words stand for (their glossary) and where they
leave a fact open, which facts make a brief precise in this field of work,
what is still unanswered, how the receiving model wants to be written to, and
the effort the job calls for.

A writer gets the kit in two ways: by asking for it before it writes
(``delegate`` with ``options.prepare``), or with the findings when its brief
is sent back once (``dodaios.briefs.gate``). Either way it is facts and
questions for the writer. None of it is sent to the agent.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from dodaios.briefs import gaps as gaps_module
from dodaios.briefs import glossary, lenses, repo_facts, terms
from dodaios.briefs.effort import EffortChoice, choose
from dodaios.briefs.lint import kind_of
from dodaios.briefs.model import Order
from dodaios.briefs.profiles import NEUTRAL, Profile, profile_for
from dodaios.rsi import domains

__all__ = ["ALREADY_KNOWN", "Kit", "build"]

log = logging.getLogger(__name__)

#: What a writer is told about the standing rules, so the brief stays lean.
ALREADY_KNOWN: Final[str] = (
    "The agent already has these as standing rules, so leave them out of the brief: nobody "
    "is watching the run, the order sets the scope, it finishes the work instead of "
    "announcing it, it backs each claim with a result, and it reports the outcome first in "
    "the person's language. The person's own words are added to the brief verbatim. It "
    "also knows how to ask: a question that blocks it, or one the brief tells it to ask "
    "first, reaches you as a question on its job, and you answer it with "
    "workspace-orchestrate, action respond. So write what it should ask and when, not how "
    "to ask, and do not tell it to end its turn on the question."
)


@dataclass(slots=True)
class Kit:
    """The facts for one request; see the module text."""

    kind: str = ""
    facts: repo_facts.RepoFacts = field(default_factory=repo_facts.RepoFacts)
    lenses: list[lenses.Lens] = field(default_factory=list)
    open_phrases: list[terms.OpenPhrase] = field(default_factory=list)
    glossary: list[glossary.Entry] = field(default_factory=list)
    gaps: list[gaps_module.Gap] = field(default_factory=list)
    profiles: list[Profile] = field(default_factory=list)
    effort: EffortChoice | None = None

    @property
    def profile(self) -> Profile:
        return self.profiles[0] if self.profiles else NEUTRAL

    def as_dict(self) -> dict[str, Any]:
        """The kit as the writer reads it: only the parts that hold something."""
        out: dict[str, Any] = {}
        if self.kind:
            out["kind_of_work"] = self.kind
        out.update(self.facts.as_dict())
        if self.glossary:
            out["their_words_mean"] = [entry.as_dict() for entry in self.glossary]
        if self.open_phrases:
            out["their_words_leave_open"] = [phrase.as_dict() for phrase in self.open_phrases]
        if self.lenses:
            out["make_precise"] = [lens.as_dict() for lens in self.lenses]
        if self.gaps:
            out["open_points"] = [gap.as_dict() for gap in self.gaps]
            out["how_to_settle_open_points"] = gaps_module.HOW_TO_SETTLE
        recipients = [profile.as_dict() for profile in self.profiles if profile is not NEUTRAL]
        if recipients:
            out["recipient"] = recipients[0] if len(recipients) == 1 else recipients
        if self.effort is not None:
            out["effort"] = self.effort.as_dict()
        out["agent_already_knows"] = ALREADY_KNOWN
        return out


def build(
    order: Order,
    *,
    profiles: Sequence[Profile] = (),
    auto_effort: bool = True,
    with_draft: bool = True,
) -> Kit:
    """Gather the kit for ``order``. Blocking file work: run it off the event loop.

    ``profiles`` are the model families that will receive the brief (the
    order's own recipient when empty). ``with_draft`` says the order carries a
    written brief; a request for the kit alone carries only what the person
    wants, and an open point is then never counted as settled by it.
    """
    kit = Kit(kind=kind_of(order))
    kit.profiles = list(profiles) or [
        profile_for(order.recipient.cli, order.recipient.model)
    ]
    said = order.person_words.strip()
    draft = order.draft.text() if with_draft else ""
    request = "\n".join(part for part in (said, order.draft.task.strip()) if part)
    folder = order.recipient.folder

    if folder:
        try:
            kit.glossary = glossary.lookup(folder, request)
        except Exception:  # noqa: BLE001 - a glossary fault never holds a brief back
            log.warning("brief kit: glossary lookup failed", exc_info=True)
    means = " ".join(entry.means for entry in kit.glossary)
    # The search runs on the writer's wording, which is in the language of the
    # code. Of the person's own words only the names they spelled out join it.
    names = " ".join(f"`{name}`" for name in terms.spelled_out(said))
    search = "\n".join(part for part in (order.draft.task.strip(), means, names) if part)
    kit.facts = repo_facts.lookup(folder, search, kind=kit.kind)

    named = domains.paths_in_text(draft) or [p.path for p in kit.facts.starting_points[:3]]
    kit.lenses = lenses.pick(
        request, kind=kit.kind, paths=named, frontend_roots=kit.facts.frontend_roots
    )
    kit.open_phrases = terms.open_phrases(said)
    kit.gaps = gaps_module.find(
        said,
        kind=kit.kind,
        lenses=kit.lenses,
        open_phrases=kit.open_phrases,
        facts=kit.facts,
        brief=draft,
    )
    kit.effort = choose(
        kit.profile,
        request if not draft else f"{said}\n{draft}",
        kind=kit.kind,
        files_named=len(domains.paths_in_text(draft)),
        named=order.recipient.effort,
        enabled=auto_effort,
    )
    return kit

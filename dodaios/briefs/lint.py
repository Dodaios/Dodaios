"""The check every brief passes before it leaves.

The rules for a good brief were in the writers' prompts all along, and the
briefs still carried step lists, suspected causes stated as facts and a "done"
that named no check: a rule in a prompt is a wish. This check is the same
rules as code. It reads a finished brief and returns findings; a finding of
severity ``revise`` goes back to the writer once before the brief is sent
(``dodaios.briefs.gate``), a ``note`` is only recorded.

Each check is deliberately narrow. A false finding costs the writer one
revision; a missed fault costs an agent run, which is the case the prompts
already failed to prevent. Nothing here reads meaning: a check fires on a
shape (a numbered list of commands, a path that is not on disk, capitals), and
the message says what to do about it.

The German words below are speech input vocabulary and words a brief may
carry over from the person, matching data and not prose.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from dodaios.agentic_ide.task_kind import (
    KIND_IMPLEMENT,
    KIND_INVESTIGATE,
    KIND_NEUTRAL,
    KIND_QUESTION,
    KIND_REVIEW,
    classify,
)
from dodaios.briefs import done, lenses, terms
from dodaios.briefs.model import SEVERITY_NOTE, SEVERITY_REVISE, Finding, Order
from dodaios.briefs.profiles import Profile
from dodaios.briefs.repo_facts import RepoFacts, nearest, path_exists
from dodaios.rsi import domains

__all__ = ["check", "kind_of"]

#: A brief longer than this is more context than most jobs need.
_LONG_BRIEF_CHARS: Final[int] = 4_500

_POINTER = re.compile(
    r"(?i)\b(?:as (?:we )?(?:discussed|agreed|talked about)|as (?:i|you) (?:said|mentioned|wrote)"
    r"|as mentioned (?:earlier|before)|(?:see|from|in) (?:the|our) (?:chat|conversation|discussion)"
    r"|like (?:yesterday|last time)|(?:same|other) (?:one|thing) as (?:before|yesterday)"
    r"|(?:the|that) (?:bug|issue|problem|thing|idea) (?:from (?:earlier|before|yesterday)"
    r"|we (?:talked|spoke) about)"
    r"|wie besprochen|wie (?:vorhin|gestern|eben) (?:gesagt|besprochen)"  # i18n-allow: input vocab
    r"|siehe oben)\b"  # i18n-allow: input vocab
)
_ORDINAL_POINTER = re.compile(
    r"(?i)\b(?:points?|options?|items?) (?:\d|one|two|three|four)(?: (?:and|to|through) "
    r"(?:\d|two|three|four))?\b|\bthe (?:first|second|third|last) (?:option|point|suggestion)\b"
)
_OWN_LIST = re.compile(r"(?m)^[ \t]*(?:\d+[.)]|[a-e][.)]|option [a-e1-5]\b)", re.IGNORECASE)

_NUMBERED = re.compile(r"(?m)^[ \t]*\d+[.)][ \t]+(.+)$")
_PROCEDURE_START = re.compile(
    r"(?i)^(?:first|then|next|after that|afterwards|finally|now|open|run|execute|cd|go to"
    r"|navigate|read|look at|check ?out|clone|install|create (?:a|an|your|the) (?:own |new )?"
    r"(?:\w+ )?(?:branch|worktree)|switch to|start by|begin by|grep|search for|edit|commit|push)\b"
)
_SHELL = re.compile(
    r"`(?:git|cd|npm|pnpm|yarn|pytest|python3?|make|cargo|gh|bash|sh|docker|pip|uv)\b[^`\n]*`"
)
_SEQUENCE = re.compile(r"(?i)(?:^|[.!?]\s+)(?:first|then|next|after that|afterwards|finally)\b,?")

_SHOUT = re.compile(
    r"\b(?:CRITICAL|IMPORTANT|MUST(?: NOT)?|NEVER|ALWAYS|DO NOT|DON'T|MANDATORY|REQUIRED"
    r"|WICHTIG|NIEMALS|ACHTUNG|UNBEDINGT)\b"  # i18n-allow: input vocab
)
_REASONING = re.compile(
    r"(?i)\b(?:(?:show|explain|write out|reproduce|share|include|output) (?:me )?(?:all )?"
    r"(?:of )?(?:your|its|the) (?:full |complete |internal |step[- ]by[- ]step )?"
    r"(?:reasoning|thinking|thought process|chain of thought)"
    r"|think (?:out loud|step[- ]by[- ]step)|step[- ]by[- ]step reasoning"
    r"|denke? schritt f[uü]r schritt)\b"  # i18n-allow: input vocab
)
_GIT_BRAKE = re.compile(
    r"(?i)\b(?:(?:do not|don'?t|never|no) (?:push|merge|commit|land|open (?:a|the) "
    r"(?:pr|pull request))\b|without (?:pushing|merging|committing)\b|needs?[- ]human\b"
    r"|hold label\b|leave (?:it|the pr|the pull request) (?:open|as (?:a )?draft)\b"
    r"|(?:only|just) open (?:a|the) (?:draft )?(?:pr|pull request)\b|do not prune\b"
    r"|change nothing in the (?:main|primary) (?:folder|checkout))"
)
_READ_ONLY = re.compile(
    r"(?i)\b(?:read[- ]only|change nothing|do not change (?:any|the) (?:code|files?)"
    r"|report only|analysis only|make no changes|no (?:code )?changes)\b"
)
# What in the person's words or wishes makes a limit theirs.
_PERSON_LIMIT = re.compile(
    r"(?i)\b(?:don'?t|do not|no|never|without|not yet) (?:\w+ ){0,3}"
    r"(?:push\w*|merg\w*|commit\w*|land\w*|publish\w*|chang\w*|touch\w*|fix\w*)\b"
    r"|\b(?:only|just) (?:\w+ ){0,2}(?:analy\w+|look\w*|review\w*|report\w*|read\w*|check\w*)\b"
    r"|\bread[- ]only\b|\bi (?:\w+ ){0,3}(?:myself|approve)\b|\bapprove\w*\b"
    r"|\b(?:nicht|kein\w*|nichts|ohne|noch nicht) (?:\w+ ){0,3}"  # i18n-allow: input vocab
    r"(?:push\w*|merg\w*|commit\w*|[aä]nder\w*|anfass\w*|fix\w*"  # i18n-allow: input vocab
    r"|ver[oö]ffentlich\w*)\b"  # i18n-allow: input vocab
    r"|\b(?:nur|blo[sß]) (?:\w+ ){0,2}(?:analys\w+|anschau\w*|pr[uü]f\w*"  # i18n-allow: input vocab
    r"|bericht\w*|lesen|review\w*)\b"  # i18n-allow: input vocab
    r"|\b(?:selbst|selber) (?:\w+ ){0,2}"  # i18n-allow: input vocab
    r"(?:merg\w*|freigeb\w*|absegn\w*)\b"  # i18n-allow: input vocab
    r"|\bfreigeb\w*\b|\bfreigabe\b"  # i18n-allow: input vocab
)
_PRESSURE = re.compile(
    r"(?i)\b(?:you (?:only )?have \d+ (?:minutes|tokens|steps)|running out of (?:time|context|room)"
    r"|stop at the first error|as fast as (?:possible|you can)|hurry|time is short)\b"
)
_COSTUME = re.compile(
    r"(?i)^\W*you are (?:a|an|the) (?:world[- ]class|expert|senior|seasoned|brilliant|10x|"
    r"highly skilled|principal|staff)\b"
)
_PLAN_REQUEST = re.compile(
    r"(?i)\b(?:(?:first|start by|begin by) (?:writ\w+|shar\w+|post\w*|outlin\w+|present\w*) "
    r"(?:me )?(?:a|an|your|the) (?:\w+ )?plan|(?:share|post|send|give) (?:me )?"
    r"(?:regular |frequent |a |your )?(?:status|progress) updates?"
    r"|before you start,? (?:tell|say|write))\b"
)
_STANDING_REPEAT = re.compile(
    r"(?i)\b(?:report back in (?:short,? )?(?:plain )?\w+|the person is not watching"
    r"|you are (?:working|operating) autonomously|lead with the outcome)\b"
)
_NO_START = re.compile(r"(?i)\bstarting point (?:is )?(?:unknown|not known)\b")
_CREATES = re.compile(
    r"(?i)\b(?:creat\w+|add\w*|new|writ\w+|sav\w+|generat\w+|produc\w+|output|deliver\w*"
    r"|exists?|in place)\b"
)
# A brief that tells the agent to change something, as its own instruction.
_ORDERS_A_CHANGE = re.compile(
    r"(?im)(?:^|[.!?]\s+|\band\s+)(?:please\s+)?(?:fix|repair|implement|change|rewrite|add|remove"
    r"|replace|merge|commit|push|land|ship)\b"
)
_BACKTICK_PATH = re.compile(r"`@?((?:[\w.\-]+/)+[\w.\-]+(?:\.\w{1,8})?)`")
# Words that ask for a change, whatever verb the sentence opens with.
_CHANGE_WORDS = re.compile(
    r"(?i)\b(?:fix\w*|improv\w+|chang\w+|add\w*|build\w*|implement\w*|updat\w+|rewrit\w+"
    r"|redesign\w*|repair\w*|make (?:it|them|this|that|sure)|remov\w+|replac\w+"
    r"|verbesser\w*|[aä]nder\w*|reparier\w*|behe\w+|[uü]berarbeit\w*"  # i18n-allow: input vocab
    r"|umbau\w*|bau\w*|erstell\w*|einbau\w*|anpass\w*|fixe?n|fixs?en"  # i18n-allow: input vocab
    r"|mach\w* (?:das|es|die|den|dass|mal)"  # i18n-allow: input vocab
    r"|(?:das|es|ihn|sie|den|die|dies) \w+ mach\w*"  # i18n-allow: input vocab
    r"|robust\w*|stabil\w*|zuverl[aä]ssig\w*|korrigier\w*)\b"  # i18n-allow: input vocab
)
_URLISH = re.compile(r"(?i)^(?:https?:|www\.|[\w.-]+\.(?:com|org|io|dev|net|app)/)")


# The small words of German, as a share of a text's words: a brief written in
# German has many, an English one that quotes a German sentence has few.
_GERMAN_SMALL_WORDS: Final[frozenset[str]] = frozenset(
    (
        "der die das und nicht ist mit für wenn dass eine einen einem wird "  # i18n-allow
        "auf den dem sich auch noch nach bei oder aber muss soll kann "  # i18n-allow
        "wurde werden sind von zu im"  # i18n-allow
    ).split()
)
_WORD_OF_A_BRIEF = re.compile(r"[^\W\d_]+", re.UNICODE)
_QUOTED_PART = re.compile(r'"[^"\n]{0,600}"|“[^”\n]{0,600}”|„[^“\n]{0,600}“|`[^`\n]{0,400}`')
#: A standing wish that names the language briefs are written in.
_WISHED_LANGUAGE = re.compile(
    r"(?i)\b(?:deutsch|german|auf deutsch|in german|spanish|french|portuguese"
    r"|espa[nñ]ol|fran[cç]ais|portugu[eê]s)\b"
)


def _reads_german(brief: str) -> bool:
    """Whether a brief is written in German (quotes of what the person said aside)."""
    words = [w.lower() for w in _WORD_OF_A_BRIEF.findall(_QUOTED_PART.sub(" ", brief or ""))]
    if len(words) < 12:
        return False
    small = sum(1 for word in words if word in _GERMAN_SMALL_WORDS)
    return small / len(words) >= 0.12


def kind_of(order: Order) -> str:
    """The kind of work an order asks for: from the person's words, else the draft.

    The classifier goes by the first verb, so "look into it and fix it" reads
    as an investigation. For a hand-off that is the wrong default: looking
    into something includes the fix unless the person asked for analysis
    only. A request that also names a change, and no such limit, is a change.
    """
    said = order.person_words.strip()
    if not said:
        # Without the person's words the draft's own opening verb is all there is.
        return classify(order.draft.task)
    kind = classify(said)
    if kind == KIND_NEUTRAL:
        kind = classify(order.draft.task)
    if (
        kind != KIND_IMPLEMENT
        and _CHANGE_WORDS.search(said)
        and not _PERSON_LIMIT.search(f"{said} {order.wishes or ''}")
    ):
        return KIND_IMPLEMENT
    return kind


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    stops = [i for i in (text.find(".", end), text.find("\n", end)) if i != -1]
    right = min(stops) if stops else len(text)
    return " ".join(text[left:right].split())


def _named_paths(brief: str) -> list[tuple[str, str]]:
    """``(path, sentence it stands in)`` for every path a brief names."""
    found: dict[str, str] = {}
    for token in domains.paths_in_text(brief):
        at = brief.find(token)
        found.setdefault(token, _sentence_around(brief, at, at + len(token)))
    for match in _BACKTICK_PATH.finditer(brief):
        found.setdefault(match.group(1), _sentence_around(brief, match.start(), match.end()))
    return list(found.items())


def _within_folder(text: str, folder: str) -> str:
    """``text`` with absolute paths into ``folder`` made relative to it.

    A path is read up to the first space, so a project folder whose name has
    one ("Personal Notes") would split each absolute path into it into a
    fragment that exists nowhere. The folder is taken as written, resolved and
    with or without macOS' ``/private`` in front.
    """
    if not folder:
        return text
    forms = {folder.rstrip("/\\")}
    try:
        forms.add(str(Path(folder).resolve()).rstrip("/\\"))
    except OSError:  # an unreadable folder keeps the form it was given in
        pass
    for form in list(forms):
        if form.startswith("/private/"):
            forms.add(form.removeprefix("/private"))
        elif form.split("/", 2)[1:2] in (["var"], ["tmp"]):
            forms.add("/private" + form)
    for form in sorted((f for f in forms if f), key=len, reverse=True):
        text = text.replace(form + "/", "").replace(form + "\\", "")
    return text


def _missing_paths(brief: str, facts: RepoFacts) -> list[tuple[str, list[str]]]:
    missing: list[tuple[str, list[str]]] = []
    for token, sentence in _named_paths(_within_folder(brief, facts.folder)):
        if _URLISH.match(token) or "*" in token or "<" in token or token.startswith("~"):
            continue
        if _CREATES.search(sentence):
            continue  # a file the agent is asked to make does not exist yet
        if not path_exists(facts, token):
            missing.append((token, nearest(facts, token)))
    return missing


def _names_a_start(brief: str, facts: RepoFacts) -> bool:
    if _NO_START.search(brief):
        return True
    return any(
        path_exists(facts, token) for token, _ in _named_paths(_within_folder(brief, facts.folder))
    )


def _step_script(brief: str) -> str:
    """The first lines of a procedure in a brief, or ``""``."""
    steps = [m.group(1).strip() for m in _NUMBERED.finditer(brief)]
    procedural = [s for s in steps if _PROCEDURE_START.match(s) or _SHELL.search(s)]
    if len(steps) >= 3 and len(procedural) >= 2:
        return " / ".join(step[:70] for step in procedural[:3])
    chain = _SEQUENCE.findall(brief)
    if len(chain) >= 3:
        return ", ".join(word.strip(" .,!?\n").lower() for word in chain[:4]) + " ..."
    return ""


def check(
    order: Order,
    *,
    facts: RepoFacts | None = None,
    profiles: Sequence[Profile] = (),
    standing: bool = False,
) -> list[Finding]:
    """Every finding for one order's brief, the ones to revise first.

    ``facts`` are the repository facts for the recipient's folder (``None``
    when no folder is known: the path checks are skipped), ``profiles`` the
    model families that will receive the brief, and ``standing`` says the
    recipient has the standing rules, so the brief need not repeat them.
    """
    brief = order.draft.text()
    kind = kind_of(order)
    person = " ".join((order.person_words or "").split())
    theirs = f"{person} {order.wishes or ''}"
    revise: list[Finding] = []
    notes: list[Finding] = []

    def add(code: str, message: str, evidence: str = "", *, note: bool = False) -> None:
        (notes if note else revise).append(Finding(
            code=code,
            severity=SEVERITY_NOTE if note else SEVERITY_REVISE,
            message=message,
            evidence=" ".join(evidence.split())[:260],
        ))

    # A follow-up into a conversation the agent already works in may point back
    # into it, needs no new starting point and no "done" of its own: only an
    # agent's first order is held to those.
    follow_up = not order.recipient.first_order
    if _reads_german(brief) and not _WISHED_LANGUAGE.search(order.wishes or ""):
        add(
            "not_english",
            "Write the brief in English: the repository's code, comments and commits are "
            "English, and a brief in another language pulls them after it. The agent "
            "answers the person in their language by itself, and their own words are "
            "added verbatim.",
        )

    pointer = None if follow_up else _POINTER.search(brief)
    if pointer is None and not follow_up and not _OWN_LIST.search(brief):
        pointer = _ORDINAL_POINTER.search(brief)
    if pointer is not None:
        add(
            "conversation_pointer",
            "The agent cannot see this conversation: replace the reference with the thing "
            "it stands for.",
            _sentence_around(brief, pointer.start(), pointer.end()),
        )

    if facts is not None and facts.known:
        for token, close in _missing_paths(brief, facts)[:4]:
            hint = f" Nearest real path: {', '.join(close)}." if close else ""
            add(
                "path_not_found",
                f"'{token}' does not exist in {facts.folder}.{hint} Name the real path, or "
                "say that the file is to be created.",
                token,
            )
        # Where to start is said in the task, not by the script a check command names.
        body = f"{order.draft.task}\n{order.draft.context}"
        inline_done = "" if order.draft.criteria.strip() else done.done_part(body)
        if inline_done:
            body = body.replace(inline_done, " ")
        if (
            not follow_up
            and kind in (KIND_IMPLEMENT, KIND_INVESTIGATE)
            and facts.content_match
            and not _names_a_start(body, facts)
        ):
            shown = ", ".join(p.path for p in facts.starting_points[:3])
            # Work on what exists (a defect, a speed problem, a restructuring, a
            # cause to find) starts somewhere in the code. A new feature may not.
            about_existing = kind == KIND_INVESTIGATE or any(
                lens.key in ("defect", "speed", "restructure")
                for lens in lenses.pick(f"{person}\n{order.draft.task}", kind=kind)
            )
            add(
                "no_starting_point",
                "The brief names no file to start from, and the repository has files that "
                f"fit the request: {shown}. Name the ones that fit, with the symbol when you "
                "know it, or write 'Starting point unknown'.",
                note=not about_existing,
            )

    script = "" if follow_up else _step_script(brief)
    if script:
        add(
            "step_script",
            "This reads as a procedure. Say what must be true at the end and let the agent "
            "choose the route; keep an order of steps only where the order itself is a "
            "requirement, and say so.",
            script,
        )

    for sentence in terms.unlabelled_guesses(brief)[:2]:
        add(
            "guess_as_fact",
            "A suspected cause or fix reads as a fact here, and an agent follows a wrong "
            "direction it is handed. Give the symptom, and mark the suspicion as an "
            "unverified hypothesis or leave it out.",
            sentence,
        )

    passage = done.done_part(order.draft.task + "\n\n" + order.draft.context, order.draft.criteria)
    own_check = ""
    if facts is not None and facts.checks:
        own_check = f" The project's own check: {facts.checks[0]}."
    if follow_up:
        pass  # the order it continues named the end
    elif kind == KIND_IMPLEMENT and not passage:
        # A change must say how its end is checked; a question or a review ends in a report.
        add(
            "no_done",
            "The brief does not say when the work is done. Name what the agent can check "
            "itself: the failing case that must pass, the behaviour that must be visible, "
            f"a command and what it shows.{own_check}",
        )
    elif passage and kind in (KIND_IMPLEMENT, KIND_NEUTRAL) and done.is_generic(passage):
        add(
            "generic_done",
            "This 'done' is true of every change. Add the point that belongs to this task: "
            "the case that fails today and must pass, or what must be visible in the "
            f"running app.{own_check}",
            passage,
        )

    shouted = _SHOUT.findall(brief)
    if len(shouted) >= 2:
        add(
            "shouting",
            "Capital-letter rules make current models over-apply them. Write each as a "
            "plain sentence with its reason.",
            ", ".join(dict.fromkeys(shouted)),
        )

    reasoning = _REASONING.search(brief)
    if reasoning is not None:
        add(
            "reasoning_request",
            "Asking a model to show its reasoning can make it refuse or fall back to a "
            "weaker model. Ask for the findings and the evidence for them.",
            reasoning.group(0),
        )

    brake = _GIT_BRAKE.search(brief)
    if brake is not None and not _PERSON_LIMIT.search(theirs):
        add(
            "git_brake",
            "This holds the agent back from shipping, and neither the person's words nor "
            "their brief wishes ask for it. Leave it out, or quote where they asked for it.",
            _sentence_around(brief, brake.start(), brake.end()),
            note=not person,
        )

    read_only = _READ_ONLY.search(brief)
    if (
        read_only is not None
        and person
        and classify(person) == KIND_IMPLEMENT
        and not _PERSON_LIMIT.search(theirs)
    ):
        add(
            "read_only_added",
            "The person asked for a change, and the brief limits the agent to reading. "
            "'Check' and 'look into' include the fix unless they asked for analysis only.",
            _sentence_around(brief, read_only.start(), read_only.end()),
        )

    if (
        person
        and kind in (KIND_INVESTIGATE, KIND_REVIEW, KIND_QUESTION)
        and _PERSON_LIMIT.search(theirs)
        and read_only is None
        and (ordered := _ORDERS_A_CHANGE.search(order.draft.task))
    ):
        add(
            "change_not_asked",
            "The person asked for an analysis and no change; the brief orders one. Ask for "
            "the cause or the findings, and say that nothing is to be changed.",
            _sentence_around(order.draft.task, ordered.start(), ordered.end()),
        )

    if any(profile.no_plan_requests for profile in profiles):
        plan = _PLAN_REQUEST.search(brief)
        if plan is not None:
            add(
                "plan_request",
                "The receiving model can stop early when it is asked for a plan or status "
                "updates first. Leave the request out.",
                plan.group(0),
            )

    vague = terms.vague_left(brief)
    strong = [phrase for phrase in vague if phrase not in {"etc", "etc.", "and so on"}]
    if strong:
        add(
            "left_open",
            "These words leave the agent to guess what is meant: say the fact instead "
            "(which fault, which property, which value).",
            ", ".join(strong[:5]),
            note=follow_up,
        )
    elif vague:
        add("left_open", "Say what the list continues with.", ", ".join(vague), note=True)

    if kind in (KIND_REVIEW, KIND_QUESTION) and _READ_ONLY.search(brief) is None and (
        re.search(r"(?i)\b(?:fix|change|implement|merge)\b", order.draft.task[:200])
    ):
        add(
            "kind_mismatch",
            "The person asked a question or for a review; the brief opens with a change. "
            "Say which one is wanted.",
            order.draft.task[:160],
            note=True,
        )
    pressure = _PRESSURE.search(brief)
    if pressure is not None:
        add(
            "pressure",
            "Time and budget pressure makes an agent cut its own work short. Leave it out.",
            pressure.group(0),
            note=True,
        )
    if _COSTUME.search(brief):
        add("role_costume", "The role line adds nothing; start with the outcome.", note=True)
    if standing:
        repeat = _STANDING_REPEAT.search(brief)
        if repeat is not None:
            add(
                "standing_repeated",
                "The agent has this as a standing rule; the brief need not carry it.",
                repeat.group(0),
                note=True,
            )
    if len(brief) > _LONG_BRIEF_CHARS:
        add(
            "long_brief",
            f"The brief is {len(brief)} characters. Leave out what the agent can read in "
            "the repository in a minute.",
            note=True,
        )
    return revise + notes

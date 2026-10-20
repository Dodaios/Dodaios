"""What a composed prompt looks like, and what it is allowed to say.

Every rule here is traceable to the vendors' own prompting documentation,
because the thing this module replaces was a plausible-sounding prompt that
made the receiving agent behave *worse*:

* **Goal and constraints, never the implementation.** The single most
  load-bearing rule, and the one the first version got backwards. Measured
  live 2026-07-27: asked to make composition faster, the composer wrote "use
  non-blocking background tasks for writer resolution" — it handed the agent a
  solution that was *already implemented*, so the agent's task became
  re-doing finished work. Every current frontier guide converges here: state
  what good looks like and the bounds, and let the model choose the route.
  Enumerated steps measurably REDUCE output quality on Fable 5, and leaner
  system prompts score higher on agentic coding evaluations while costing a
  fraction of the tokens.
* **The handover is not the work.** The instruction arrives as speech aimed at
  Jarvis, so it names the handover as well as the task: "prompt T2 and T3 to
  …", "write Alex the prompt for …", "tell Nova it should …". THIS BRIEF IS
  THAT PROMPT. Measured live 2026-07-29, on an order that translates as "write
  the prompt for T2 and T3, and make sure that …": the brief's ``## Task`` read
  "Create or update the system prompts for terminals T2 and T3" — two coding
  agents were sent off to write prompts for themselves, and the analysis the
  user actually asked for reached nobody. The work is what follows the
  handover; writing a prompt is the task only when the user is talking about
  prompt TEXT that lives in the repository.
* **Resolve what the agent cannot see.** A spoken instruction refers back into
  the conversation it came out of — "points two and three", "the second one",
  "do that for the wake path too" — and the agent receives the brief alone.
  The same live composition wrote "Ensure that points 2 and 3 from the current
  context are specifically incorporated": a pointer to something the recipient
  can never open, which is worth exactly as much as writing nothing. The
  recent turns travel with the instruction (``conversation``) so the reference
  can be replaced by what it stands for.
* **A lean brief, not a map of the code.** Complete means the agent has the
  task and the starting ``@files``, not that the writer narrated how those
  files work. The agent opens them. A 1400-2400 character specification
  (2026-07-27) cost 10-30 s of thinking and then made the agent re-read the
  same files; the 2026-08-18 mandate is 1-5 s, cleaned speech plus key files.
  Since 2026-10-01 the writer also sees short excerpts of the top files, and
  may pass on up to three facts from them in ``## Context`` - the symbol or
  value the agent would otherwise spend its first searches finding.
* **Scope lives in the task, not in a prohibition list.** The first version
  listed what the agent must not do (no surrounding cleanup, no unrequested
  refactors, no speculative abstractions). Anthropic's own measured
  replacement is an intent instruction — deliver what was asked at the
  scope intended — which cut scope drift without extra clarifying questions.
* **No verification ritual.** "If your prompt contains explicit verification
  instructions … remove them: instructions like these cause over-verification
  … and removing them reduces wasted tokens with no loss in quality." Success
  *criteria* stay; "double-check afterwards" is banned.
* **No reasoning echo.** Asking an agent to reproduce its internal reasoning
  can trigger the ``reasoning_extraction`` refusal category on Fable 5.
* **Say each thing exactly once.** A rule repeated in two sections is not
  twice as followed; it is noise that dilutes the rules that matter, and it is
  paid for on every composition in latency the user waits through.
* **Per-kind guardrails.** The clearest case: on a review, "only report
  high-severity issues" is followed literally and suppresses real findings. On
  an investigation the opposite steer is right — report, do not fix. One
  coherent rule set per kind beats one long contradictory one, so ``task_kind``
  picks the set and only that set is injected.

The composed prompt is always English. The recipient is a coding agent working
in a repository whose artifacts are English; a prompt in the
spoken language pulls same-language commit messages and comments after it. The
*spoken readback* to the user is unaffected — that stays in the turn's
resolved output language.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from . import conversation as conversation_module
from .task_kind import (
    KIND_IMPLEMENT,
    KIND_INVESTIGATE,
    KIND_NEUTRAL,
    KIND_QUESTION,
    KIND_REVIEW,
)

# The hard ceiling for the deterministic fallback; MAX_PROMPT_CHARS is the
# transport cap above it.
MAX_BODY_CHARS = 2200

# What a good brief weighs; the only length the writer is told.
TARGET_MAX_CHARS = 1200

# The writer sees excerpts, the agent sees the code: the brief carries the
# goal and its constraints, never a guessed implementation. ``@path`` hygiene
# (no invented paths, never ending on a reference) is enforced by the composer.
_SHARED_RULES = f"""\
You write the prompt Dodaios sends to a coding agent (Claude Code or Codex) \
running in the user's repository. Words that address the agent ("tell T2 \
to ...") are the handover, not its task. The agent sees only your text: \
replace references to the conversation with what they stand for, and state \
the user's goal and constraints, not an implementation.

English Markdown, no preamble or code fence, at most {TARGET_MAX_CHARS} \
characters. `## Task` is required; optional: `## Key files` (`@path` from the \
workspace tree, one reason each), `## Context` (up to three facts the excerpts \
show, symbol and file), `## Done when` (only outcomes the user stated or the \
repository defines)."""

_KIND_RULES: dict[str, str] = {
    KIND_IMPLEMENT: "Kind: implementation.",
    KIND_REVIEW: (
        "Kind: review. Ask for every finding with severity and file:line; "
        "findings are filtered later. No fixes."
    ),
    KIND_INVESTIGATE: (
        "Kind: investigation. The deliverable is the cause and its evidence, "
        "no fix. Quote the user's symptoms verbatim."
    ),
    KIND_QUESTION: (
        "Kind: question. The deliverable is an answer from the code; nothing is changed."
    ),
    KIND_NEUTRAL: "Kind: unclear. Keep the user's framing and scope.",
}


def system_prompt(kind: str) -> str:
    """The composer's system prompt for one task kind."""
    return f"{_SHARED_RULES}\n\n{_KIND_RULES.get(kind, _KIND_RULES[KIND_NEUTRAL])}"


def attachment_block(attachments: list) -> str:
    """The dropped files' contents, laid out for the writer. ``""`` when none.

    Each entry is a ``drop_analysis.DropAnalysis``. The description of a
    screenshot and the text of a document are the whole reason the drop was
    analysed: without them the writer can only say "the file the user dropped",
    which is exactly the empty prompt this feature exists to prevent.

    The reference travels WITH the content so the writer can cite the file the
    agent will open, rather than inventing a path for a picture that only exists
    as a description.
    """
    usable = [a for a in attachments or [] if getattr(a, "name", "")]
    if not usable:
        return ""
    parts: list[str] = []
    for item in usable:
        kind = getattr(item, "kind", "") or "file"
        header = f'<attachment name="{item.name}" kind="{kind}" reference="{item.reference}">'
        if item.detail and getattr(item, "described_by", "") == "vision":
            body = f"Description of what this image shows:\n{item.detail}"
        elif item.detail:
            body = f"Contents:\n{item.detail}"
        else:
            body = item.note or "No content could be read from this file."
        parts.append(f"{header}\n{body}\n</attachment>")
    return "\n\n".join(parts)


# Appended only when the user dropped a file.
_ATTACHMENT_RULES = """\
The agent may not see images: put what an attachment shows into `## Task`, \
quote its error text, labels and code verbatim, and cite it by the reference \
in its tag."""


def user_block(
    *,
    utterance: str,
    instruction: str,
    terminal_name: str,
    agent_display: str,
    profile_lines: list[str],
    candidates: list[str],
    skeletons: dict[str, str],
    house_rules: str,
    attachments: list | None = None,
    conversation: Sequence[tuple[str, str]] | None = None,
    tree: str = "",
) -> str:
    """Everything the composer knows, laid out for one model call.

    Longform data first, the request last: the documentation measures up to a
    30 % quality gain from putting the query at the end for multi-document
    inputs, and the file outlines are exactly that.

    ``conversation`` is the handful of turns the instruction came out of, and it
    sits directly in front of the instruction rather than with the longform
    data: it is not reference material, it is what the sentence's pronouns and
    ordinals point AT. Without it "above all points two and three" is
    unresolvable and travels into the brief as a pointer the agent cannot
    follow (live 2026-07-29).
    """
    parts: list[str] = []

    if profile_lines:
        parts.append("WORKSPACE\n" + "\n".join(profile_lines))
    if house_rules:
        parts.append("HOUSE RULES\n" + house_rules)

    dropped = attachment_block(attachments or [])
    if dropped:
        parts.append(
            "DROPPED FILES (saved in the workspace; images described by a vision model)\n"
            + dropped
        )
        parts.append(_ATTACHMENT_RULES)

    if tree:
        parts.append(
            "WORKSPACE TREE (directory header, then its files; @path = header + name)\n" + tree
        )

    if skeletons:
        outlines = "\n\n".join(
            f'<file path="{path}">\n{text}\n</file>' for path, text in skeletons.items()
        )
        parts.append("FILE OUTLINES AND TASK-RELEVANT LINES (partial excerpts)\n" + outlines)

    if tree:
        if candidates:
            parts.append(
                "SPOKEN WORDS ALREADY POINTED AT (hints, not a limit)\n"
                + "\n".join(f"- {c}" for c in candidates)
            )
    else:
        candidate_block = (
            "\n".join(f"- {c}" for c in candidates) if candidates else "(none - omit Key files)"
        )
        parts.append("CANDIDATE FILES (use only these in @references)\n" + candidate_block)

    spoken = conversation_module.render(conversation or ())
    if spoken:
        parts.append(
            "THE CONVERSATION THIS CAME OUT OF (oldest first; the agent will never "
            "see any of it)\n" + spoken
        )

    parts.append(f"Target: {agent_display} in terminal {terminal_name}.")
    parts.append(f"WHAT THE USER SAID (speech transcript)\n{utterance}")
    if instruction and instruction != utterance:
        parts.append("INSTRUCTION WITHOUT THE ADDRESSING\n" + instruction)
    parts.append("Write the prompt now.")

    return "\n\n".join(parts)


def render_fallback(
    instruction: str,
    files: list[str],
    attachments: list | None = None,
) -> str:
    """The deterministic prompt: same skeleton, no model involved.

    Used whenever no writer model is reachable. It is always better than the
    raw transcript, so the feature never depends on a provider being up.

    Dropped files are carried here as well, and that is the load-bearing half
    for a downloader with no writing model: the screenshot was still described
    (vision and prompt-writing are separate providers, and having one without
    the other is ordinary), so the description belongs in the prompt whether or
    not a model wrote the prose around it.
    """
    task = " ".join((instruction or "").split())
    usable = [a for a in attachments or [] if getattr(a, "name", "")]
    if not task and not usable:
        return ""
    out = [f"## Task\n{task}"] if task else []

    if usable:
        blocks: list[str] = []
        for item in usable:
            head = f"### {item.name}"
            if item.reference:
                # Plain hyphen, like the rest of the agent-facing text here: this
                # string is TYPED into a terminal, and a pane's encoding is not
                # ours to assume.
                head += f" - {item.reference}"
            if item.detail and getattr(item, "described_by", "") == "vision":
                blocks.append(f"{head}\nWhat this image shows:\n\n{item.detail}")
            elif item.detail:
                blocks.append(f"{head}\nContents:\n\n```\n{item.detail}\n```")
            else:
                blocks.append(f"{head}\n{item.note or 'No content could be read.'}")
        out.append("## Dropped files\n" + "\n\n".join(blocks))

    if files:
        listed = "\n".join(f"- `@{f}`" for f in files)
        out.append(f"## Key files\n{listed}")
        # Never end on a reference: a trailing @path holds the completion popup
        # open, and the Enter that follows picks a suggestion instead of
        # submitting the prompt.
        out.append("Starting points, not a limit.")
    return "\n\n".join(out)[:MAX_BODY_CHARS]


_TRAILING_TOKEN_RE = re.compile(r"[@/][\w./\\-]*$")


def ends_on_reference(text: str) -> bool:
    """True when ``text`` ends on an ``@path`` or ``/command`` token."""
    return bool(_TRAILING_TOKEN_RE.search((text or "").rstrip()))


# Punctuation a finished sentence ends on.
_SENTENCE_ENDINGS = (".", "!", "?", ":", ";", "`", ")", "]", '"', "'", "…")
# Line shapes that legitimately end without punctuation: list items, headings,
# table rows, fenced-block delimiters.
_STRUCTURAL_PREFIXES = ("-", "*", "+", "#", ">", "|", "```")


def looks_truncated(text: str) -> bool:
    """True when a composed prompt stopped mid-sentence.

    On a thinking model the token budget covers the reasoning as well as the
    answer, so an under-provisioned budget produces a brief that simply stops —
    measured live, one ended on "...to find" and was still handed over as a
    finished prompt. That is worse than the plain deterministic prompt, because
    it READS as complete: the agent starts work on an instruction whose second
    half was never written.

    Deliberately narrow. It only fires when the last line is running prose that
    ends without punctuation. A list item ("- `@a.py` - the ranking pipeline")
    and a heading are complete lines that happen to carry no full stop, and
    treating them as damage would degrade good briefs. A false positive costs
    one rougher prompt; a missed truncation sends an agent off with half a task.
    """
    body = (text or "").strip()
    if not body:
        return True
    last = body.splitlines()[-1].strip()
    if not last or last.startswith(_STRUCTURAL_PREFIXES):
        return False
    return not last.endswith(_SENTENCE_ENDINGS)


def looks_like_brief(text: str) -> bool:
    """True when ``text`` has the shape of a brief rather than of an accident.

    The writer can be a subscription CLI, and a CLI answers on stdout whether it
    understood the request or not. Measured live 2026-07-26: one returned
    ``Error: invalid model selection (--model "..." --effort ""): ... requires
    --effort`` — 146 characters, exit path unknown to us, and the composer
    reported it as a successfully composed prompt. That string would then have
    been typed at a coding agent as its task.

    So the test is structural, not semantic: every brief the blueprint asks for
    carries at least one markdown heading (``## Task`` at minimum), and no
    single-line tool error does. Deliberately loose — this rejects debris, it
    does not grade quality. A false positive costs one rougher prompt; a missed
    one sends an agent off with a diagnostic string for a task.
    """
    body = (text or "").strip()
    if not body:
        return False
    return any(line.lstrip().startswith("#") for line in body.splitlines())


__all__ = [
    "MAX_BODY_CHARS",
    "TARGET_MAX_CHARS",
    "attachment_block",
    "ends_on_reference",
    "looks_like_brief",
    "looks_truncated",
    "render_fallback",
    "system_prompt",
    "user_block",
]

"""How a brief is shaped for the model that receives it.

The vendors' own prompting guides agree on the core of a brief (the outcome, a
checkable end, only what the agent cannot see) and differ in a few places that
matter. One rule set for every model gets those places wrong for someone:

* asking the agent to verify its work: OpenAI asks for it in so many words,
  Anthropic's guide for the Opus line warns that such lines cause
  over-verification and says to give a runnable check instead;
* asking for a plan or status updates first: the guide for the Codex-tuned
  models says to remove such requests because they can make the model stop
  early, Google's agent template asks for a plan;
* order: Google puts long context first and the task last, the others lead
  with the outcome;
* how hard to think for a job of a given size (``dodaios.briefs.effort``).

A profile holds those differences for one model family. It shapes three things
and nothing else: the notes the brief writer reads, the checks that apply only
to this family, and the last assembly step of the text. The brief's content is
always the writer's.

Every rule carries the page it came from and the day it was read, because
these pages change with each model release. When a new model family arrives,
it gets the neutral profile until someone has read its guide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "CLAUDE",
    "CLAUDE_FABLE",
    "CODEX",
    "GEMINI",
    "GPT",
    "GROK",
    "NEUTRAL",
    "PROFILES",
    "Profile",
    "Source",
    "family_of",
    "profile_for",
]

#: The day the vendor pages below were read.
CHECKED: Final[str] = "2026-11-22"


@dataclass(frozen=True, slots=True)
class Source:
    """A vendor page a profile rule rests on."""

    url: str
    checked: str = CHECKED


@dataclass(frozen=True, slots=True)
class Profile:
    """What differs for one model family."""

    key: str
    label: str
    #: What the writer of a brief should know about this recipient.
    writer_notes: tuple[str, ...]
    #: Long context goes first and the task last.
    task_last: bool = False
    #: A request for a plan, a preamble or status updates is a fault in the brief.
    no_plan_requests: bool = False
    #: The line the assembly adds at the end of a change order (``""`` for none).
    closing: str = ""
    #: The effort for a light, a usual and a hard job (``""`` leaves the CLI's default).
    effort_light: str = ""
    effort_usual: str = ""
    effort_hard: str = ""
    sources: tuple[Source, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {"recipient": self.label, "write_for_it": list(self.writer_notes)}


_ANTHROPIC_FABLE = Source(
    "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/"
    "prompting-claude-fable-5-2"
)
_ANTHROPIC_OPUS = Source(
    "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/"
    "prompting-claude-opus-5"
)
_CLAUDE_CODE = Source("https://code.claude.com/docs/en/best-practices")
_OPENAI = Source("https://developers.openai.com/api/docs/guides/prompt-guidance")
_OPENAI_CODEX = Source(
    "https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide"
)
_GOOGLE = Source("https://aistudio.google.com/docs/prompting-strategies")
_XAI = Source("https://docs.x.ai/build/modes-and-commands")

CLAUDE_FABLE: Final[Profile] = Profile(
    key="claude_fable",
    label="Claude Fable or Mythos",
    writer_notes=(
        "It follows the brief to the letter: state the goal and the limits, not a route.",
        "Write a limit as a condition with its reason ('ask before you delete files'); it "
        "takes 'never' as absolute.",
        "It adds to the existing structure unless told the design is its to change. Say so "
        "only when the person wants broad change.",
    ),
    effort_light="medium",
    effort_usual="high",
    effort_hard="high",
    sources=(_ANTHROPIC_FABLE, _CLAUDE_CODE),
)
CLAUDE: Final[Profile] = Profile(
    key="claude",
    label="Claude Opus, Sonnet or Haiku",
    writer_notes=(
        "State the goal and the limits, not a route.",
        "Give it something it can run that comes back pass or fail. Leave out lines such "
        "as 'double-check everything': they make it verify far more than the job needs.",
        "It reads a request narrowly and builds the smallest thing that fits: name the "
        "full extent when the person wants more than a minimal change.",
    ),
    effort_light="medium",
    effort_usual="high",
    effort_hard="high",
    sources=(_ANTHROPIC_OPUS, _CLAUDE_CODE),
)
GPT: Final[Profile] = Profile(
    key="gpt",
    label="an OpenAI GPT model",
    writer_notes=(
        "Describe the destination and what will be checked, not every step.",
        "Say which decisions need the person and that it may make reasonable assumptions "
        "for the rest; without that it tends to propose a next step and wait.",
        "Use 'always', 'never' and 'must' only for a true invariant.",
    ),
    closing=(
        "Before you report, verify that the requested work is complete, and say what you "
        "checked and what it showed."
    ),
    effort_light="medium",
    effort_usual="medium",
    effort_hard="high",
    sources=(_OPENAI,),
)
CODEX: Final[Profile] = Profile(
    key="codex",
    label="an OpenAI Codex model",
    writer_notes=(
        "Keep the brief lean: the outcome, the context it cannot infer, the limits, and "
        "what must be true before the task is complete.",
        "Do not ask for a plan first, for a preamble or for status updates: such requests "
        "can make it stop before the work is done.",
        "Say what the person will look at when they check the result.",
    ),
    no_plan_requests=True,
    closing=(
        "Before you report, verify that the requested work is complete, and say what you "
        "checked and what it showed."
    ),
    effort_light="medium",
    effort_usual="medium",
    effort_hard="high",
    sources=(_OPENAI_CODEX, _OPENAI),
)
GEMINI: Final[Profile] = Profile(
    key="gemini",
    label="a Google Gemini model",
    writer_notes=(
        "State the goal plainly, without persuasion; explain any term that could be read "
        "two ways.",
        "It answers tersely unless asked: say so when the person wants a detailed report.",
        "Say when it may assume and when it has to stop and ask.",
    ),
    task_last=True,
    effort_light="medium",
    effort_usual="medium",
    effort_hard="high",
    sources=(_GOOGLE,),
)
GROK: Final[Profile] = Profile(
    key="grok",
    label="an xAI Grok model",
    writer_notes=(
        "Say what done looks like, so there is something concrete to check.",
        "Name the files and the context it needs; short, specific instructions are "
        "followed more reliably than long ones.",
    ),
    effort_light="high",
    effort_usual="high",
    effort_hard="high",
    sources=(_XAI,),
)
NEUTRAL: Final[Profile] = Profile(
    key="neutral",
    label="a coding agent",
    writer_notes=(
        "Lead with the outcome, give what it cannot see and a check it can run.",
    ),
)

PROFILES: Final[dict[str, Profile]] = {
    p.key: p for p in (CLAUDE_FABLE, CLAUDE, GPT, CODEX, GEMINI, GROK, NEUTRAL)
}


def family_of(cli: str = "", model: str = "") -> str:
    """The profile key for a coding CLI and the model it runs on.

    The model decides when it is known, because one CLI can run several
    vendors' models; the CLI decides otherwise. Anything unknown is neutral.
    """
    name = (model or "").strip().lower()
    tool = (cli or "").strip().lower()
    if "fable" in name or "mythos" in name:
        return CLAUDE_FABLE.key
    if "claude" in name or any(word in name for word in ("opus", "sonnet", "haiku")):
        return CLAUDE.key
    if "codex" in name:
        return CODEX.key
    if name.startswith(("gpt", "o1", "o3", "o4")) or "gpt-" in name:
        return CODEX.key if tool.startswith("codex") else GPT.key
    if "gemini" in name:
        return GEMINI.key
    if "grok" in name:
        return GROK.key
    if name:
        return NEUTRAL.key
    if tool.startswith("claude"):
        return CLAUDE.key
    if tool.startswith("codex"):
        return CODEX.key
    if tool.startswith(("gemini", "agy", "antigravity")):
        return GEMINI.key
    if tool.startswith("grok"):
        return GROK.key
    return NEUTRAL.key


def profile_for(cli: str = "", model: str = "") -> Profile:
    """The profile of a recipient; never raises."""
    return PROFILES[family_of(cli, model)]

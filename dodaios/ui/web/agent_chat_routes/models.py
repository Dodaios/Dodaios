"""Request and response bodies of the agent-chat routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from dodaios.agent_chat.plan_review import PlanReview, review_from

#: The Pydantic twin of ``dodaios.agent_chat.store.SURFACES`` (AP-4; the parity
#: test in tests/unit/agent_chat/test_agent_chat_surface_parity.py pins it).
SurfaceName = Literal["jarvis", "agent", "local-models", "society", "side"]


class ChatSelectionBody(BaseModel):
    provider: str = Field(min_length=1)
    model: str = ""
    effort: str = ""
    account_id: str = ""


class VoiceChatBody(BaseModel):
    #: The Jarvis chat on stage; ``None`` = a blank page (the next call opens a new chat).
    session_id: str | None = None
    #: An archived voice chat on stage instead (``sessions.db``): calls are
    #: recorded into it and start with its history. Only with ``session_id`` unset.
    voice_session_id: str | None = None


class VoiceChatResponse(BaseModel):
    session_id: str | None
    fresh: bool
    voice_session_id: str | None = None


# ------------------------------------------------------------------ bodies


class CreateSessionBody(BaseModel):
    provider: str
    account_id: str = ""
    model: str = ""
    effort: str | None = None
    #: The coding CLI's speed tier ("" = standard; dodaios/agent_chat/speed.py).
    speed: str = Field(default="", max_length=32)
    cwd: str | None = None
    #: "" = the runner's default mode (dodaios/agent_chat/permissions.py).
    permission_mode: str = ""
    #: With ``permission_mode`` "plan": the mode the permission pill shows,
    #: which the session goes back to once its plan is approved.
    build_mode: str = Field(default="", max_length=64)
    title: str = ""
    #: Which chat the session belongs to — the front page ("jarvis"), the
    #: Agentic IDE's chat mode ("agent"), or the Local models section's setup
    #: assistant ("local-models"). Fixed for the session's life.
    surface: SurfaceName = "agent"
    #: A coding thread's placement: a connected computer id; "" = this computer.
    computer_id: str = ""
    #: Continue an existing Claude Code / Codex session (a grid pane's): the
    #: thread's next turn resumes it. Empty = a fresh conversation.
    vendor_session: str = ""


class ForkSessionBody(BaseModel):
    #: Run the copy in a new git worktree on its own branch.
    worktree: bool = False
    #: Branch / worktree name (worktree forks only); suggested when empty.
    name: str = Field(default="", max_length=120)
    #: The copy's title (the client words it in the person's language).
    title: str = Field(default="", max_length=120)


class FromTerminalBody(BaseModel):
    #: The grid pane's call-sign and workspace.
    name: str = Field(min_length=1, max_length=120)
    workspace_id: str | None = None


class PatchSessionBody(BaseModel):
    title: str | None = None
    provider: str | None = None
    model: str | None = None
    effort: str | None = None
    speed: str | None = Field(default=None, max_length=32)
    cwd: str | None = None
    permission_mode: str | None = None
    #: A pick on the permission pill while Plan is on: the mode an approved
    #: plan builds in. Ignored for a session that is not in Plan.
    build_mode: str | None = Field(default=None, max_length=64)
    computer_id: str | None = None


class MessageBody(BaseModel):
    timezone: str | None = Field(default=None, max_length=100)
    #: May be empty when files are attached — dropping a screenshot and
    #: pressing Enter is a complete gesture. The service refuses a message
    #: that carries neither.
    text: str = Field(default="", max_length=200_000)
    #: What ``POST /attachments`` returned for the files going in with this
    #: message; the wire shape of ``drop_analysis.DropAnalysis``.
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    tool_choices: list[str] = Field(default_factory=list, max_length=24)
    #: A message typed while a coding thread's turn runs: ``now`` goes into the
    #: running turn when its CLI takes one (ahead of waiting messages),
    #: ``after`` waits and starts as the next turn, ``auto`` steers when it can.
    delivery: Literal["auto", "now", "after"] = "auto"


class PlanCommentBody(BaseModel):
    #: The passage of the plan the comment is about; empty for none.
    quote: str = Field(default="", max_length=4000)
    text: str = Field(default="", max_length=20000)


class PlanReviewBody(BaseModel):
    """What the person did in a plan's review window (``agent_chat/plan_review.py``)."""

    #: The plan as the person left it; absent when they did not change its text.
    plan: str | None = None
    comments: list[PlanCommentBody] = Field(default_factory=list, max_length=500)
    #: A remark on the whole plan.
    note: str = Field(default="", max_length=20000)

    def to_review(self) -> PlanReview:
        return review_from(plan=self.plan, comments=self.comments, note=self.note)


class ApprovalBody(BaseModel):
    decision: str
    #: Where an "Always allow" lives (the card's rule chooser); empty = as before.
    scope: str = ""
    breadth: str = ""
    #: A narrower chat rule: ``folder`` (only this folder) or ``command``
    #: (only this exact command); empty = the whole tool.
    narrow: str = ""
    #: Why a card was declined, handed to the agent as the deny message.
    feedback: str = ""
    #: Inline edits of the action's text fields (preview field key -> new text),
    #: applied before it runs; the action allows only plain text fields.
    edits: dict[str, str] = Field(default_factory=dict)
    #: The person's review of a plan, on a plan's card only.
    review: PlanReviewBody | None = None


class ApprovalRuleBody(BaseModel):
    kind: str
    scope: str
    breadth: str = "action"
    narrow: str = ""


class CredentialBody(BaseModel):
    #: The secret the person pasted. It goes to the agent's vault and nowhere
    #: else: never logged, never echoed, never part of a chat event. No length
    #: constraint here on purpose: a validation error would echo the value in
    #: its 422 body; the vault refuses a bad value with a 400 that names none.
    value: Any = Field(default=None, repr=False)


class QuestionAnswerBody(BaseModel):
    #: Which question of the card's series this answers.
    index: int = 0
    #: The picked option (0 is the agent's recommendation) ...
    option_index: int | None = None
    #: ... the picked options of a multi-select question ...
    option_indices: list[int] | None = None
    #: ... or the person's own typed answer (next to the picks of a multi-select).
    text: str | None = None


class QuestionSubmitBody(BaseModel):
    #: One entry per question: ``{option_index | option_indices | text | skip}``.
    answers: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


class QuestionSkipBody(BaseModel):
    #: Skip only this question of the series; absent closes the whole card.
    index: int | None = None


class QuestionReplyBody(BaseModel):
    #: The chat message the person sent while a question card was open.
    text: str = Field(default="", max_length=20000)


class PlanBody(BaseModel):
    #: The turn whose plan card this answers.
    turn_id: str
    #: ``build`` (switch to the build mode and go) or ``keep`` (keep planning).
    decision: str
    #: The mode the permission pill shows: where ``build`` goes on. Empty
    #: leaves it to the mode the session recorded.
    build_mode: str = Field(default="", max_length=64)
    #: The person's edits and comments from the plan's review window.
    review: PlanReviewBody | None = None


class PickFolderBody(BaseModel):
    start: str | None = None


# ------------------------------------------------------------- health


class ProviderHealthRow(BaseModel):
    """One row's live state, in the API-Keys screen's own vocabulary."""

    provider: str
    #: ok | needs_setup | error | unknown (dodaios.brain.section_health).
    status: str = "unknown"
    #: Machine-readable cause — "bad_key", "no_credits", "not_configured",
    #: "timeout", … The UI turns it into a sentence; it is never shown raw.
    reason: str = "unknown"
    #: The provider's own words, for the tooltip and the log.
    detail: str = ""


class ProviderHealthResponse(BaseModel):
    providers: list[ProviderHealthRow]
    checked_at: float = 0.0
    cached: bool = False


class LeadBriefBody(BaseModel):
    enabled: bool
    #: Local wall-clock time, ``HH:MM``.
    time: str = "08:00"
    #: IANA zone of the person, e.g. ``Europe/Berlin``.
    timezone: str = ""


class LeadProactiveBody(BaseModel):
    #: ``off`` | ``important`` | ``everything``.
    level: str = "off"
    #: Any of ``mail``, ``calendar``, ``agents``, ``deadlines``.
    topics: list[str] = Field(default_factory=lambda: ["mail", "calendar", "agents", "deadlines"])
    #: Hours between two checks: 1, 3 or 6.
    interval_hours: int = 3
    #: IANA zone of the person, e.g. ``Europe/Berlin``.
    timezone: str = ""


class LeadCheckinBody(BaseModel):
    minutes: int = Field(ge=1, le=12 * 60)
    #: What the person is doing meanwhile, if they said.
    doing: str = Field(default="", max_length=160)


class LeadLifeAdminBody(BaseModel):
    enabled: bool = False
    #: ``off`` or ``mon`` .. ``sun``: the weekly written digest.
    digest_day: str = "off"
    #: Local wall-clock time, ``HH:MM``.
    digest_time: str = "09:00"
    in_brief: bool = True
    categories: dict[str, bool] = Field(default_factory=dict)
    timezone: str = ""


class LeadStandingBody(BaseModel):
    """A standing task the owner writes by hand; the service checks lengths and bounds."""

    title: str
    goal: str
    how: str = ""
    #: ``watch`` | ``prepare`` | ``act``.
    autonomy: str = "prepare"
    #: What ``act`` may change without asking, in the owner's words.
    limits: str = ""
    #: Minutes between two runs to start with; each run adjusts it.
    interval_min: int | None = None
    #: IANA zone of the person, e.g. ``Europe/Berlin``.
    timezone: str = ""


class LeadStandingPatchBody(BaseModel):
    """Only the fields that are sent change."""

    title: str | None = None
    goal: str | None = None
    how: str | None = None
    autonomy: str | None = None
    limits: str | None = None
    interval_min: int | None = None


class LeadTriggerEventBody(BaseModel):
    #: ``mail`` | ``calendar`` | ``github`` | ``automation`` | ``channel``.
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)


class PreloadBody(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(default="", max_length=256)


class QueuedEditBody(BaseModel):
    text: str = Field(max_length=200_000)

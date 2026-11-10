"""Permission modes per agent-chat runner.

Every runner has its own idea of "how much may the agent do without asking":
Claude Code has ``--permission-mode`` (default / acceptEdits / plan /
bypassPermissions / dontAsk), the Codex CLI pairs a sandbox with an approval
policy (the TUI's Read-only / Auto / Full-access presets, plus headless
``--approve-for-me`` where its own reviewer model answers the prompts),
Antigravity's ``agy`` knows accept-edits, plan and a skip-permissions
switch, OpenCode's ``run`` has its own rules plus ``--auto`` and a read-only
plan agent, Kimi's print mode is autonomous by design, the DeepSeek harness
keeps its policy in its own settings, and the in-process API runner gates
its own tools. The composer
shows exactly the ladder of the runner in use — the same words the vendor's
own CLI uses, so a person who knows Claude Code's "Auto-accept edits" finds
it here — and
:func:`normalize_permission` folds a mode onto the nearest one another runner
offers when a session moves between providers.

``plan`` is special: every ladder that has it maps it onto "read and plan,
change nothing" (Claude Code's plan mode; a read-only sandbox on Codex; the
read-only tool set on the API runner). The composer draws it as the
Build | Plan switch next to the permission pill.

The **Jarvis surface** (the front page's chat — Jarvis with a keyboard, see
``dodaios.agent_chat.store.SURFACES``) shows ONE ladder whatever answers:
``ask`` / ``accept-edits`` / ``bypass`` plus ``plan``, the three stances
Claude Code's own modes express, in Claude Code's words (maintainer,
2026-08-25). A CLI seat folds them onto its vendor spelling through
:func:`normalize_permission`; the brain runner reads them as stances (see
``dodaios.agent_chat.approval_bridge``). ``bypass`` never overrides the
blacklist — ``RiskTierEvaluator.evaluate`` raises for a blacklisted call
before any approval logic runs, in every stance.

Single source of truth: the frontend receives the ladders through
``GET /api/agent-chat/catalog`` and never mirrors them (AP-4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class PermissionMode:
    id: str
    label: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "description": self.description}


# ----------------------------------------------------------------- ladders

_CLAUDE: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "default",
        "Ask before acting",
        "Edits and commands wait for an approval card here in the chat.",
    ),
    PermissionMode(
        "acceptEdits",
        "Auto-accept edits",
        "File edits in the working folder run. Shell commands still ask.",
    ),
    PermissionMode(
        "plan",
        "Plan",
        "Reads and plans, changes nothing. Asks before building.",
    ),
    PermissionMode(
        "auto",
        "Auto",
        "Approves routine actions itself, asks only for risky ones.",
    ),
    PermissionMode(
        "dontAsk",
        "Don't ask",
        "Never asks. Anything that would need approval is declined.",
    ),
    PermissionMode(
        "bypassPermissions",
        "Bypass permissions",
        "Nothing asks. Use it on a folder you can afford to lose.",
    ),
)

_CODEX: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "read-only",
        "Read only",
        "The agent can read. Edits and commands that write are blocked.",
    ),
    PermissionMode(
        "approve-for-me",
        "Ask (auto-review)",
        "Codex's own reviewer approves or declines what would have asked you.",
    ),
    PermissionMode(
        "auto",
        "Auto",
        "Edits and commands run inside the working folder. Other folders and the "
        "network are blocked.",
    ),
    PermissionMode(
        "plan",
        "Plan",
        "Reads and plans in a read-only sandbox. Nothing is changed.",
    ),
    PermissionMode(
        "full-access",
        "Full access",
        "No sandbox and no approvals. The agent may touch anything on this machine.",
    ),
)

_AGY: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "accept-edits",
        "Auto-accept edits",
        "Edits run on their own. Commands run too, because this CLI cannot ask back in a chat.",
    ),
    PermissionMode(
        "plan",
        "Plan",
        "Reads and plans, changes nothing.",
    ),
    PermissionMode(
        "skip-permissions",
        "Skip permissions",
        "Everything runs without asking.",
    ),
)

_GROK: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "default",
        "Ask before acting",
        "Grok cannot ask back in a chat, so tools run. Plan is the read-only stance.",
    ),
    PermissionMode(
        "acceptEdits",
        "Auto-accept edits",
        "Edits and commands run without asking.",
    ),
    PermissionMode(
        "plan",
        "Plan",
        "Reads and plans, changes nothing.",
    ),
    PermissionMode(
        "bypassPermissions",
        "Bypass permissions",
        "Everything runs without asking.",
    ),
)

_OPENCODE: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "default",
        "Ask before acting",
        "OpenCode's own rules decide. Anything they would ask about is declined.",
    ),
    PermissionMode(
        "plan",
        "Plan",
        "OpenCode's plan agent. Reads and plans, changes nothing.",
    ),
    PermissionMode(
        "auto",
        "Full access",
        "Grants every permission that OpenCode's rules do not deny outright.",
    ),
)

_KIMI: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "auto",
        "Full access",
        "Kimi runs on its own. Tools run without asking.",
    ),
    PermissionMode(
        "plan",
        "Plan",
        "Asks for a plan instead of action. Kimi does not enforce it, so read the plan first.",
    ),
)

_CUSTOM: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "auto",
        "CLI's own policy",
        "Runs your CLI's command as written. That CLI decides what it may do.",
    ),
)

_DSH: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "auto",
        "Harness policy",
        "Never asks. DeepSeek Harness's own settings decide what runs.",
    ),
)

_CURSOR: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "ask",
        "Ask",
        "Read-only exploration. Nothing is changed.",
    ),
    PermissionMode(
        "plan",
        "Plan",
        "Designs the approach before coding.",
    ),
    PermissionMode(
        "auto",
        "Agent",
        "Full tool access. In the chat, edits apply without asking.",
    ),
)

_API: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "ask",
        "Ask before acting",
        "Reads run freely. Edits, writes and shell commands wait for an approval "
        "card here in the chat.",
    ),
    PermissionMode(
        "accept-edits",
        "Auto-accept edits",
        "Edits and writes in the working folder run. Shell commands still ask.",
    ),
    PermissionMode(
        "plan",
        "Plan",
        "Reads and plans. The agent gets no editing or shell tools.",
    ),
    PermissionMode(
        "auto",
        "Full access",
        "Everything runs without asking.",
    ),
)

_JARVIS: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "ask",
        "Ask before acting",
        "Reads run freely. Edits, commands and consequential actions wait for an approval card.",
    ),
    PermissionMode(
        "accept-edits",
        "Auto-accept edits",
        "File edits in the working folder run. Commands and consequential actions still ask.",
    ),
    PermissionMode(
        "plan",
        "Plan",
        "Reads and plans, changes nothing.",
    ),
    PermissionMode(
        "bypass",
        "Bypass permissions",
        "Nothing asks. Blacklisted actions stay blocked.",
    ),
)

_SOCIETY: Final[tuple[PermissionMode, ...]] = (
    PermissionMode(
        "bypass",
        "Bypass permissions",
        "Run Dodaios tools without prompts. Dodaios blocks, denied capabilities and "
        "credential boundaries still apply; vendor-native CLI tools use that runner's controls.",
    ),
    PermissionMode(
        "ask",
        "Ask",
        "Read freely; show a decision in this chat before an action or write.",
    ),
    PermissionMode(
        "always_ask",
        "Always ask",
        "Show a decision in this chat before every Dodaios tool call, including reads.",
    ),
)

#: The ladder key of the Jarvis surface — not a runner, but the one word the
#: front page's composer shows whichever runner answers.
JARVIS_LADDER: Final[str] = "jarvis"

# runner (or JARVIS_LADDER) -> (ladder, default)
_LADDERS: Final[dict[str, tuple[tuple[PermissionMode, ...], str]]] = {
    "claude-cli": (_CLAUDE, "bypassPermissions"),
    "codex-cli": (_CODEX, "full-access"),
    "agy-cli": (_AGY, "skip-permissions"),
    "grok-cli": (_GROK, "bypassPermissions"),
    "opencode-cli": (_OPENCODE, "auto"),
    "kimi-cli": (_KIMI, "auto"),
    # GLM Coding Plan drives the Claude Code binary, so it takes Claude
    # Code's own words.
    "glm-cli": (_CLAUDE, "bypassPermissions"),
    "dsh-cli": (_DSH, "auto"),
    "custom-cli": (_CUSTOM, "auto"),
    "cursor-cli": (_CURSOR, "auto"),
    "api": (_API, "auto"),
    JARVIS_LADDER: (_JARVIS, "bypass"),
    "society": (_SOCIETY, "bypass"),
}

# The universal stance ordering: every ladder is a sub-sequence of this once
# its vendor words are translated, so a mode can be folded across runners.
_STANCE: Final[dict[str, int]] = {
    # 0 = reads only, 1 = ask first, 2 = edits yes / commands ask, 3 = all.
    "plan": 0,
    "read-only": 0,
    "ask": 1,
    "default": 1,
    "dontAsk": 1,
    "approve-for-me": 1,
    "accept-edits": 2,
    "acceptEdits": 2,
    "auto_codex": 2,
    "auto_claude": 2,
    "auto": 3,
    "full-access": 3,
    "bypassPermissions": 3,
    "skip-permissions": 3,
    "bypass": 3,
    "always_ask": 1,
}


def _stance(runner: str, mode: str) -> int:
    # Codex's "auto" is the workspace-write sandbox (edits yes, not everything);
    # Claude Code's "auto" is its classifier (routine yes, risky asks).
    if runner == "codex-cli" and mode == "auto":
        return _STANCE["auto_codex"]
    if runner in ("claude-cli", "glm-cli") and mode == "auto":
        return _STANCE["auto_claude"]
    return _STANCE.get(mode, 1)


def ladder_key(surface: str, runner: str) -> str:
    """Which ladder a session shows: the runner's own on the agent surface,
    the one Jarvis ladder on the front page's chat."""
    from dodaios.agent_chat.surface_kits import kit_for  # lazy: kits import no ladder

    return kit_for(surface).ladder or runner


def stance_of(mode: str) -> int:
    """The runner-independent stance of a mode: 0 reads only, 1 ask first,
    2 edits yes / commands ask, 3 everything. Unknown words count as "ask"."""
    return _STANCE.get((mode or "").strip(), 1)


def permission_modes(runner: str) -> tuple[PermissionMode, ...]:
    """The ladder the composer offers for ``runner`` (or the Jarvis ladder)."""
    return _LADDERS.get(runner, _LADDERS["api"])[0]


def default_permission(runner: str) -> str:
    return _LADDERS.get(runner, _LADDERS["api"])[1]


def permission_ids(runner: str) -> tuple[str, ...]:
    return tuple(m.id for m in permission_modes(runner))


def is_permission_mode(runner: str, mode: str) -> bool:
    return mode in permission_ids(runner)


def society_mode_supported(runner: str, mode: str) -> bool:
    """Whether this transport can honor a Society mode without hidden prompts."""
    if mode == "bypass":
        return True
    if mode == "ask":
        # Hermes and OpenClaw ask over ACP (session/request_permission) before
        # the actions their own approval policy marks as risky.
        return runner in {
            "brain",
            "codex-cli",
            "claude-cli",
            "glm-cli",
            "hermes-cli",
            "openclaw-cli",
        }
    if mode == "always_ask":
        # OpenClaw: Dodaios' gate plugin asks before every native file call
        # (reads too), exec asks over ACP, Dodaios' tools ask on their own.
        return runner in {"brain", "codex-cli", "openclaw-cli"}
    return False


def normalize_permission(runner: str, mode: str | None) -> str:
    """Fold ``mode`` onto the closest mode ``runner`` accepts.

    A mode the runner offers passes through. ``plan`` passes through wherever
    a ladder has it. Anything else (a mode from another runner's ladder, or
    the legacy ``ask``/``auto`` pair) snaps to the mode of the same stance,
    else the nearest LOWER stance — moving to a runner that cannot express
    "edits yes, commands ask" must not silently grant everything.
    """
    picked = (mode or "").strip()
    ids = permission_ids(runner)
    if not picked:
        return default_permission(runner)
    if picked in ids:
        return picked
    # Legacy ask/auto from before the ladders (store rows written by the
    # first draft of this package).
    want = _stance(runner, picked) if picked in _STANCE else 1
    if picked == "auto":
        want = 3
    # Plan / read-only are only ever the target when that is what was asked
    # for: folding "ask" onto a read-only sandbox would silently take the
    # hands away.
    pool = [m for m in ids if want == 0 or _stance(runner, m) > 0]
    candidates = sorted(
        (abs(_stance(runner, m) - want), _stance(runner, m) > want, i, m)
        for i, m in enumerate(pool)
    )
    return candidates[0][3] if candidates else default_permission(runner)


__all__ = [
    "JARVIS_LADDER",
    "PermissionMode",
    "default_permission",
    "is_permission_mode",
    "ladder_key",
    "normalize_permission",
    "permission_ids",
    "permission_modes",
    "society_mode_supported",
    "stance_of",
]

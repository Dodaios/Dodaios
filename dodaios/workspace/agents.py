"""What a workspace terminal can RUN: an open registry of coding-agent CLIs plus the plain shell.

CLI entries reuse ``CliSpec`` for detection but are NOT in the shared CLI catalog
(``dodaios/clis/catalog/seed_catalog.json``); see ``__init__``. With no shell on
the host the shell entry reports not installed.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dodaios.clis.prober import CliStatusProber
from dodaios.clis.spec import AuthConfig, CliSpec, CliStatus, InstallMethods, RiskConfig
from dodaios.terminal.shells import default_shell
from dodaios.workspace.launch_picks import VALUE as picks_value
from dodaios.workspace.launch_picks import LaunchPicks, RuntimePicks, flag_modes

log = logging.getLogger(__name__)

# A semver in the --version output ("2.1.195 (Claude Code)", "codex-cli 0.142.3").
_SEMVER_RE = r"(\d+\.\d+\.\d+)"

# Patch optional, for CLIs numbering in two parts (Kimi: ``kimi, version 1.3``).
_LOOSE_SEMVER_RE = r"(\d+\.\d+(?:\.\d+)?)"

# Registry key of the plain-shell entry; several layers must agree on it.
PLAIN_TERMINAL = "shell"


@dataclass(frozen=True, slots=True)
class TrustSpec:
    """Where and how one CLI records "this folder is trusted".

    We write the answer BEFORE launch because a PTY trust dialog cannot be
    answered programmatically. ``home_env`` moves the file to ``$VAR/<filename>``;
    ``both_path_forms`` seeds backslash and slash spellings of the cwd.
    """

    filename: str
    fmt: Literal["json", "toml"]
    section: tuple[str, ...] = ("projects",)
    key: str = "trust_level"
    value: Any = "trusted"
    extra_defaults: tuple[tuple[str, Any], ...] = ()
    home_env: str | None = None
    subdir: str = ""
    both_path_forms: bool = False
    # One-time copy before the first mutation, for files the user's CLI shares.
    backup: bool = False
    # Per-project value is a bare scalar, not an object (``{ "<path>": "TRUST_FOLDER" }``).
    scalar: bool = False


@dataclass(frozen=True, slots=True)
class AccountSpec:
    """How one CLI's entire identity moves to a different directory.

    Mechanism behind several subscriptions of one CLI (:mod:`dodaios.agent_accounts`).
    ``shared_env`` names general-purpose variables (``XDG_DATA_HOME``) that also
    redirect other tools in the pane, so such an entry is offered as single-login.
    """

    env: tuple[tuple[str, str], ...]
    native_dir: str
    shared_env: tuple[str, ...] = ()
    #: Paths in the account dir that prove a login; EMPTY = sign-in state unreadable.
    login_markers: tuple[str, ...] = ()
    #: Args appended to the binary to start its sign-in; empty = no login command.
    login_argv: tuple[str, ...] = ()

    @property
    def dedicated(self) -> bool:
        """True when every variable that moves this CLI is its own."""
        return not self.shared_env


@dataclass(frozen=True, slots=True)
class WinShim:
    """How to reach the real executable behind a Windows ``.cmd`` shim.

    ConPTY cannot exec a batch file and ``cmd /c`` adds a process between pane
    and agent. ``kind``: a Node script run via ``node.exe`` or a native executable.
    """

    relative_path: tuple[str, ...]
    kind: Literal["node", "exe"] = "node"


@dataclass(frozen=True, slots=True)
class WorkspaceAgent:
    """One thing a workspace terminal can run.

    ``kind``: ``"cli"`` (detected via ``spec``, launched with ``launch_command``
    inside a shell) or ``"shell"`` (installed = the host has a shell).
    ``needs_trust``: pre-mark the folder trusted (``dodaios.workspace.trust``).
    Fields below ``description`` replace ``if agent == "<name>"`` branches in
    layers that must not know product names (AP-21).
    """

    name: str
    display_name: str
    kind: str = "cli"
    spec: CliSpec | None = None
    launch_command: str | None = None
    needs_trust: bool = True
    description: str = ""

    #: PATH lookup name; split from ``launch_command`` (``which`` cannot find "uv tool run kimi").
    binary: str = ""
    binary_aliases: tuple[str, ...] = ()
    launch_args: tuple[str, ...] = ()
    win_shim: WinShim | None = None
    extra_path_dirs: tuple[str, ...] = ()
    spawn_env: tuple[tuple[str, str], ...] = ()
    #: Environment resolved per spawn AND resume. ``None`` = not configured and
    #: must stop the launch (a half-set one talks to the wrong vendor).
    spawn_env_factory: Callable[[], dict[str, str] | None] | None = None
    generation_probe: Callable[[], str | None] | None = None

    #: Model / effort / permission picks on the launch argv (``None`` = offers none).
    launch_picks: LaunchPicks | None = None
    #: Same picks for a RUNNING pane, as typed commands (``/effort max``);
    #: ``None`` = the process owns them and the composer locks those pills.
    runtime_picks: RuntimePicks | None = None

    trust: TrustSpec | None = None
    account: AccountSpec | None = None
    #: Session adapter that reopens its conversations; empty = this entry's own.
    #: Another entry's name lets a launch profile (GLM over Claude Code) inherit resume.
    resume_adapter: str = ""
    file_reference: Literal["at", "quoted"] = "quoted"
    #: False when the agent's own interface is elsewhere (DeepSeek Harness serves
    #: its chat in the browser). Single reader: :func:`dodaios.agentic_ide.session.accepts_prompts`.
    accepts_typed_prompts: bool = True
    needs_input_line_wait: bool = True
    input_markers: tuple[str, ...] = ()
    #: Readiness needs the cursor visible on the marker row (Ratatui draws it while input is off).
    requires_visible_input_cursor: bool = False
    #: The CLI asks for screen colours just AFTER its input line appears; typing
    #: into that gap corrupts the answer (``]10;rgb:...``), so readiness waits
    #: (:func:`dodaios.agentic_ide.fleet_actions.colour_probe_settled`).
    asks_colours_after_input_line: bool = False
    #: Max resumed panes of this CLI+account still starting (0 = shared gate only).
    resume_start_limit: int = 0
    #: TUI furniture stripped before a transcript is summarised; adds to the shared set.
    chrome_fragments: tuple[str, ...] = ()
    busy_fragments: tuple[str, ...] = ()
    #: A line submitted mid-turn reaches that turn; False = unknown, so stop first
    #: (:meth:`dodaios.agentic_ide.session.Registry.send_prompt`).
    steers_mid_turn: bool = False
    instruction_filename: str = ""
    #: User-added (:mod:`dodaios.workspace.custom_clis`); never run its ``--version``.
    custom: bool = False
    logo_url: str = ""
    #: Start through a shell, for a command that is shell SOURCE and cannot be exec'd.
    shell_launch: bool = False

    spoken_aliases: tuple[str, ...] = ()
    spoken_aliases_needing_suffix: tuple[str, ...] = ()
    alias_suffix: str = "code"

    @property
    def is_coding_agent(self) -> bool:
        """True for an entry that runs an agent rather than a bare shell."""
        return self.kind == "cli"

    @property
    def executable(self) -> str:
        """The name to resolve on PATH — explicit, else the spec's, else empty."""
        if self.binary:
            return self.binary
        return self.spec.binary_name if self.spec is not None else ""

    @property
    def adapter_key(self) -> str:
        """Which session adapter this entry resumes through."""
        return self.resume_adapter or self.name


def make_cli_agent(
    name: str,
    display_name: str,
    *,
    binary: str,
    npm_package: str = "",
    homepage: str = "",
    launch_command: str | None = None,
    description: str = "",
    install: InstallMethods | None = None,
    version_regex: str = _SEMVER_RE,
    needs_trust: bool = True,
    **extra: Any,
) -> WorkspaceAgent:
    """Build a registrable entry for an interactive CLI.

    Give a name and binary (and optionally the npm package); an entry installed
    another way passes ``install=``. ``extra`` forwards :class:`WorkspaceAgent` fields.
    """
    spec = CliSpec(
        name=name,
        display_name=display_name,
        description=description or f"{display_name} coding-agent CLI.",
        homepage=homepage,
        binary_name=binary,
        check_command=(binary, "--version"),
        version_parse_regex=version_regex,
        install=install or InstallMethods(npm_package=npm_package or None, recommended="npm"),
        # Only installation matters; the agent handles login on first launch.
        auth=AuthConfig(type="none"),
        risk=RiskConfig(default_tier="monitor"),
        category="agent",
    )
    return WorkspaceAgent(
        name=name,
        display_name=display_name,
        kind="cli",
        spec=spec,
        launch_command=launch_command or binary,
        needs_trust=needs_trust,
        description=description,
        binary=binary,
        **extra,
    )


#: Claude Code keeps trust in ``~/.claude.json``; the GLM profile seeds the same file.
CLAUDE_TRUST = TrustSpec(
    filename=".claude.json",
    fmt="json",
    section=("projects",),
    key="hasTrustDialogAccepted",
    value=True,
    extra_defaults=(("hasCompletedProjectOnboarding", True),),
    # No ``home_env``: ``CLAUDE_CONFIG_DIR`` moves the ``.claude`` DIRECTORY, not this file.
    home_env=None,
    subdir="",
    both_path_forms=True,
    backup=True,
)

CODEX_TRUST = TrustSpec(
    filename="config.toml",
    fmt="toml",
    section=("projects",),
    key="trust_level",
    value="trusted",
    home_env="CODEX_HOME",
    subdir=".codex",
)

GROK_TRUST = TrustSpec(
    filename="trusted_folders.toml",
    fmt="toml",
    section=("folders",),
    key="trusted",
    value=True,
    home_env="GROK_HOME",
    subdir=".grok",
    backup=True,
)

#: Antigravity (``agy``) shares ``~/.gemini/trustedFolders.json`` with the Gemini
#: CLI (path -> ``"TRUST_FOLDER"``); backed up because the file is not ours alone.
ANTIGRAVITY_TRUST = TrustSpec(
    filename="trustedFolders.json",
    fmt="json",
    section=(),
    value="TRUST_FOLDER",
    home_env="GEMINI_HOME",
    subdir=".gemini",
    both_path_forms=True,
    backup=True,
    scalar=True,
)


def _grok_build_install() -> InstallMethods:
    """Official Grok Build installer (``install.ps1`` on Windows, ``install.sh`` elsewhere)."""
    url = (
        "https://x.ai/cli/install.ps1" if sys.platform == "win32" else "https://x.ai/cli/install.sh"
    )
    return InstallMethods(script_url=url, recommended="script")


def _antigravity_install() -> InstallMethods:
    """Official Antigravity (``agy``) installer for the OS that will run it.

    URLs match the API-Keys card.
    """
    url = (
        "https://antigravity.google/cli/install.ps1"
        if sys.platform == "win32"
        else "https://antigravity.google/cli/install.sh"
    )
    return InstallMethods(script_url=url, recommended="script")


def _cursor_cli_install() -> InstallMethods:
    """Official Cursor CLI installer: PowerShell URL on Windows, ``curl | bash`` elsewhere."""
    url = (
        "https://cursor.com/install?win32=true"
        if sys.platform == "win32"
        else "https://cursor.com/install"
    )
    return InstallMethods(script_url=url, recommended="script")


KIMI_CURRENT = "kimi-code"
KIMI_LEGACY = "kimi-cli"

_KIMI_CURRENT_PACKAGE = "kimi-code"


def kimi_generation() -> str | None:
    """Which Kimi is installed: the current CLI, the legacy one, or unknown.

    Both generations put ``kimi`` on PATH with different data directories and
    flags, and ``kimi --version`` succeeds for either; a wrong guess resumes the
    wrong history.

    The BINARY decides, not the data directory: after an upgrade the new binary
    is on PATH but its data root does not exist until first run, while the old
    root still does, so a directory-first probe reports the legacy generation.
    Resolved binary path first (an npm install carries the package name), then
    data roots as fallback. ``None`` = unknown; the caller reads no history.
    """
    import shutil
    from pathlib import Path

    try:
        from dodaios.core.path_augment import ensure_cli_paths

        ensure_cli_paths()
    except Exception:  # noqa: BLE001, S110 - PATH augmentation is best-effort
        pass
    binary = shutil.which("kimi")
    if binary:
        try:
            resolved = Path(binary).resolve()
        except OSError:
            resolved = Path(binary)
        # The package name shows in the resolved path or a sibling node_modules tree.
        parts = {part.lower() for part in resolved.parts}
        if _KIMI_CURRENT_PACKAGE in parts:
            return KIMI_CURRENT
        package = resolved.parent / "node_modules" / "@moonshot-ai" / _KIMI_CURRENT_PACKAGE
        if package.is_dir():
            return KIMI_CURRENT

    home = Path.home()
    if (home / ".kimi-code").is_dir():
        return KIMI_CURRENT
    if (home / ".kimi").is_dir():
        return KIMI_LEGACY
    return None


def glm_spawn_env() -> dict[str, str] | None:
    """Environment that turns a Claude Code process into a GLM one.

    ``None`` (no key configured) stops the launch: the CLI never says which
    backend it got, so a half-set environment would bill the wrong vendor silently.
    ``ANTHROPIC_API_KEY`` is blanked (empty = removed from the child) because it
    outranks the token we pass.
    """
    from dodaios.core.config import get_secret, load_config

    token = (get_secret("zai_api_key", "ZAI_API_KEY") or "").strip()
    if not token:
        return None
    try:
        settings = load_config().agentic_ide.glm
    except Exception as exc:  # noqa: BLE001 - a broken config must not brick the pane
        log.warning("GLM pane: falling back to default endpoint settings: %s", exc)
        settings = None

    def _setting(field: str, fallback: str) -> str:
        value = getattr(settings, field, "") if settings is not None else ""
        return str(value or fallback).strip()

    env = {
        "ANTHROPIC_BASE_URL": _setting("base_url", "https://api.z.ai/api/anthropic"),
        "ANTHROPIC_AUTH_TOKEN": token,
        "API_TIMEOUT_MS": _setting("request_timeout_ms", "3000000"),
        "ANTHROPIC_API_KEY": "",
    }
    # Pin a model only when the user chose one: vendor docs disagree about ids.
    for field, var in (
        ("opus_model", "ANTHROPIC_DEFAULT_OPUS_MODEL"),
        ("sonnet_model", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
        ("haiku_model", "ANTHROPIC_DEFAULT_HAIKU_MODEL"),
    ):
        if chosen := _setting(field, ""):
            env[var] = chosen
    return env



_CLAUDE_PICKS = LaunchPicks(
    provider="claude-api",
    model_args=("--model", picks_value),
    effort_args=("--effort", picks_value),
    permission_args=flag_modes(
        "--permission-mode",
        "default",
        "acceptEdits",
        "plan",
        "auto",
        "dontAsk",
        "bypassPermissions",
    ),
)

#: GLM drives the Claude Code binary, so it takes the same permission words; no
#: model list (Z.ai's own) and no effort flag (belongs to Anthropic's endpoint).
_GLM_PICKS = LaunchPicks(provider="claude-api", permission_args=_CLAUDE_PICKS.permission_args)

_CLAUDE_RUNTIME = RuntimePicks(model=f"/model {picks_value}", effort=f"/effort {picks_value}")

_CODEX_PICKS = LaunchPicks(
    provider="openai-codex",
    model_args=("--model", picks_value),
    # A ``-c`` override parsed as TOML: the level goes in bare.
    effort_args=("-c", f"model_reasoning_effort={picks_value}"),
    permission_args=(
        ("read-only", ("--sandbox", "read-only")),
        ("approve-for-me", ("--approve-for-me",)),
        ("auto", ("--sandbox", "workspace-write")),
        ("full-access", ("--dangerously-bypass-approvals-and-sandbox",)),
    ),
)

_AGY_PICKS = LaunchPicks(
    provider="antigravity",
    model_args=("--model", picks_value),
    effort_args=("--effort", picks_value),
    permission_args=(
        ("accept-edits", ("--mode", "accept-edits")),
        ("plan", ("--mode", "plan")),
        ("skip-permissions", ("--dangerously-skip-permissions",)),
    ),
    effort_required=True,
)

_GROK_PICKS = LaunchPicks(
    provider="grok-build",
    model_args=("--model", picks_value),
    effort_args=("--reasoning-effort", picks_value),
    permission_args=flag_modes(
        "--permission-mode",
        "default",
        "acceptEdits",
        "plan",
        "bypassPermissions",
    ),
)

#: OpenCode and Kimi bring their own models, so no list is offered; the shape
#: check in ``launch_picks`` stands in.
_OPENCODE_PICKS = LaunchPicks(
    model_args=("--model", picks_value),
    permission_args=(("auto", ("--auto",)),),
    ladder="api",
)

_KIMI_PICKS = LaunchPicks(
    model_args=("--model", picks_value),
    permission_args=(("auto", ("--auto",)),),
    ladder="api",
)

_CURSOR_PICKS = LaunchPicks(
    provider="cursor",
    model_args=("--model", picks_value),
    permission_args=(
        ("auto", ("--force",)),
        ("plan", ("--mode", "plan")),
        ("ask", ("--mode", "ask")),
    ),
)
_CURSOR_RUNTIME = RuntimePicks(model=f"/model {picks_value}")


_AGENTS: dict[str, WorkspaceAgent] = {
    "claude": make_cli_agent(
        "claude",
        "Claude Code",
        launch_picks=_CLAUDE_PICKS,
        runtime_picks=_CLAUDE_RUNTIME,
        binary="claude",
        npm_package="@anthropic-ai/claude-code",
        homepage="https://claude.com/claude-code",
        trust=CLAUDE_TRUST,
        account=AccountSpec(env=(("CLAUDE_CONFIG_DIR", "{dir}"),), native_dir="~/.claude"),
        file_reference="at",
        needs_input_line_wait=False,
        steers_mid_turn=True,
        instruction_filename="CLAUDE.md",
        # The footer row would be quoted as a busy pane's "activity"; the branch
        # glyph and rotating "Tip: Use /btw" prefix are the stable markers.
        chrome_fragments=("🌿", "tip: use"),
        spawn_env=(("CLAUDE_CODE_DISABLE_MOUSE_CLICKS", "1"),),
        spoken_aliases=("claude", "cloude", "claud", "clode", "klaude", "kloude"),
        spoken_aliases_needing_suffix=(
            "cloud",
            "clawed",
            "clod",
            "loud",
            "cloth",
            "glow",
        ),
    ),
    "codex": make_cli_agent(
        "codex",
        "Codex",
        launch_picks=_CODEX_PICKS,
        binary="codex",
        npm_package="@openai/codex",
        homepage="https://github.com/openai/codex",
        launch_args=("-c", "check_for_update_on_startup=false"),
        trust=CODEX_TRUST,
        account=AccountSpec(env=(("CODEX_HOME", "{dir}"),), native_dir="~/.codex"),
        win_shim=WinShim(
            relative_path=("node_modules", "@openai", "codex", "bin", "codex.js"),
            kind="node",
        ),
        instruction_filename="AGENTS.md",
        input_markers=("›", "»"),
        requires_visible_input_cursor=True,
        asks_colours_after_input_line=True,
        # Enter mid-task steers (Tab queues); review/compact turns refuse the steer.
        steers_mid_turn=True,
        resume_start_limit=1,
        spoken_aliases=("codex", "kodex", "codecs", "codeks"),
    ),
    "cursor": make_cli_agent(
        "cursor",
        "Cursor CLI",
        launch_picks=_CURSOR_PICKS,
        runtime_picks=_CURSOR_RUNTIME,
        binary="agent",
        homepage="https://cursor.com/docs/cli/overview",
        description="Cursor's terminal coding agent — the same models as the editor.",
        install=_cursor_cli_install(),
        binary_aliases=("cursor-agent",),
        needs_trust=False,
        extra_path_dirs=("~/.local/bin",),
        file_reference="at",
        instruction_filename="AGENTS.md",
        input_markers=("→",),
        version_regex=_LOOSE_SEMVER_RE,
        spoken_aliases=("cursor", "cursor cli", "cursor-cli", "cursor agent"),
    ),
    "opencode": make_cli_agent(
        "opencode",
        "OpenCode",
        launch_picks=_OPENCODE_PICKS,
        binary="opencode",
        homepage="https://opencode.ai",
        description="Open-source terminal coding agent — bring your own model.",
        install=InstallMethods(
            npm_package="opencode-ai",
            script_url="https://opencode.ai/install",
            recommended="npm",
        ),
        needs_trust=False,
        win_shim=WinShim(
            relative_path=("node_modules", "opencode-ai", "bin", "opencode.exe"),
            kind="exe",
        ),
        spawn_env=(("OPENCODE_DISABLE_AUTOUPDATE", "1"),),
        file_reference="at",
        instruction_filename="AGENTS.md",
        spoken_aliases=("opencode",),
        spoken_aliases_needing_suffix=("open",),
    ),
    "kimi": make_cli_agent(
        "kimi",
        "Kimi Code",
        launch_picks=_KIMI_PICKS,
        binary="kimi",
        npm_package="@moonshot-ai/kimi-code",
        homepage="https://moonshotai.github.io/kimi-code/en/",
        description="Moonshot AI's terminal coding agent.",
        version_regex=_LOOSE_SEMVER_RE,
        needs_trust=False,
        win_shim=WinShim(
            relative_path=(
                "node_modules",
                "@moonshot-ai",
                "kimi-code",
                "dist",
                "main.mjs",
            ),
            kind="node",
        ),
        spawn_env=(("KIMI_CODE_NO_AUTO_UPDATE", "1"),),
        # No AccountSpec: the legacy generation ignores ``KIMI_CODE_HOME`` and config
        # shares one file with credentials (docs/os-parity.md).
        # Its installer's dir is not on the PATH a GUI-launched macOS/Linux process inherits.
        extra_path_dirs=("~/.local/bin",),
        generation_probe=kimi_generation,
        spoken_aliases=("kimi", "kimmy", "kimmi", "kimme", "kimmie"),
    ),
    "glm": make_cli_agent(
        "glm",
        "GLM Coding Plan",
        launch_picks=_GLM_PICKS,
        binary="claude",
        npm_package="@anthropic-ai/claude-code",
        homepage="https://docs.z.ai/devpack/tool/claude",
        description="Z.ai's GLM models, driven through the Claude Code CLI.",
        trust=CLAUDE_TRUST,
        resume_adapter="claude",
        file_reference="at",
        needs_input_line_wait=False,
        steers_mid_turn=True,
        instruction_filename="CLAUDE.md",
        spawn_env_factory=glm_spawn_env,
        spawn_env=(("CLAUDE_CODE_DISABLE_MOUSE_CLICKS", "1"),),
        spoken_aliases=("glm", "g l m", "gee ell em", "jlm"),
    ),
    "grok-build": make_cli_agent(
        "grok-build",
        "Grok Build",
        launch_picks=_GROK_PICKS,
        binary="grok",
        homepage="https://x.ai/cli",
        description="xAI's terminal coding agent — SuperGrok or X Premium+.",
        install=_grok_build_install(),
        trust=GROK_TRUST,
        account=AccountSpec(
            env=(("GROK_HOME", "{dir}"),),
            native_dir="~/.grok",
            login_markers=("auth.json",),
            login_argv=("login",),
        ),
        extra_path_dirs=("~/.grok/bin",),
        launch_args=("--no-auto-update",),
        file_reference="at",
        instruction_filename="AGENTS.md",
        spoken_aliases=("grok", "groc", "grock", "grok build"),
    ),
    "antigravity": make_cli_agent(
        "antigravity",
        "Antigravity",
        launch_picks=_AGY_PICKS,
        binary="agy",
        homepage="https://antigravity.google",
        description="Google's terminal coding agent — billed against the Google subscription.",
        install=_antigravity_install(),
        trust=ANTIGRAVITY_TRUST,
        # No AccountSpec: ``GEMINI_HOME`` is shared; ``agy`` has no ``login`` subcommand.
        extra_path_dirs=("~/.local/bin",),
        file_reference="at",
        instruction_filename="GEMINI.md",
        spoken_aliases=(
            "antigravity",
            "anti gravity",
            "anti-gravity",
            "agy",
        ),
    ),
    "deepseek-harness": make_cli_agent(
        "deepseek-harness",
        "DeepSeek Harness",
        binary="dsh",
        npm_package="@deepseek-ai/dsh",
        homepage="https://deepseek.com/harness",
        description="DeepSeek's agent harness — the pane runs it, the chat is in the browser.",
        # ``dsh web`` is the only interactive profile; it opens its UI in the browser.
        launch_command="dsh web",
        launch_args=("web",),
        accepts_typed_prompts=False,
        needs_input_line_wait=False,
        needs_trust=False,
        win_shim=WinShim(
            relative_path=("node_modules", "@deepseek-ai", "dsh", "lib", "bin.js"),
            kind="node",
        ),
        instruction_filename="AGENTS.md",
        spoken_aliases=(
            "deepseek",
            "deep seek",
            "deepseek harness",
            "deep seek harness",
            "dipsik",
            "deepsick",
            "deep sick",
            "dsh",
        ),
    ),
    PLAIN_TERMINAL: WorkspaceAgent(
        name=PLAIN_TERMINAL,
        display_name="Plain Terminal",
        kind="shell",
        needs_trust=False,
        description="This machine's own shell — no agent, just a prompt.",
        needs_input_line_wait=False,
    ),
}


#: User-added entries, rebuilt from their store on change. Kept apart from
#: ``_AGENTS`` so re-reading a file cannot drop shipped or plugin entries.
_CUSTOM_AGENTS: dict[str, WorkspaceAgent] = {}
_custom_revision: int = -1


def builtin_names() -> tuple[str, ...]:
    """Every registry key this app ships or a plugin registered in code."""
    return tuple(_AGENTS)


def _custom_aliases(display_name: str, entry_id: str) -> tuple[str, ...]:
    """Spellings for a user-added entry; conservative (a one-word name only from four letters)."""
    out: list[str] = []
    name = " ".join(str(display_name or "").lower().split())
    words = name.split()
    if len(words) > 1:
        out.append(name)
    elif words and len(words[0]) >= 4 and words[0].isalpha():
        out.append(words[0])
    slug = str(entry_id or "").lower()
    if len(slug) >= 4 and slug.replace("-", "").isalnum() and slug not in out:
        out.append(slug)
    return tuple(out)


def _custom_agent(entry: Any) -> WorkspaceAgent:
    """Turn one stored custom CLI into an entry.

    ``spec=None``: detection is a PATH lookup, never a stranger's ``--version``.
    """
    from dodaios.workspace import custom_clis

    through_shell = custom_clis.needs_shell(entry.command)
    return WorkspaceAgent(
        name=entry.id,
        display_name=entry.display_name,
        kind="cli",
        spoken_aliases=_custom_aliases(entry.display_name, entry.id),
        spec=None,
        launch_command=entry.command,
        needs_trust=False,
        description=entry.description,
        binary=entry.binary,
        launch_args=() if through_shell else custom_clis.split_command(entry.command)[1:],
        file_reference=entry.file_reference,
        custom=True,
        logo_url=custom_clis.logo_url(entry),
        shell_launch=through_shell,
    )


def _sync_custom_agents() -> None:
    """Rebuild the user's entries when their store changed (called from every read)."""
    global _custom_revision
    from dodaios.workspace import custom_clis

    revision = custom_clis.revision()
    if revision == _custom_revision:
        return
    try:
        entries = custom_clis.list_custom_clis()
    except Exception as exc:  # noqa: BLE001 - a broken store must not hide the built-ins
        log.warning("workspace agents: custom entries unavailable: %s", exc)
        entries = []
    _custom_revision = revision
    _CUSTOM_AGENTS.clear()
    for entry in entries:
        if entry.id in _AGENTS:
            # Store refuses these, so this is a hand-edited file; the shipped entry wins.
            log.warning(
                "workspace agents: custom entry %r shadows a built-in; ignoring it",
                entry.id,
            )
            continue
        _CUSTOM_AGENTS[entry.id] = _custom_agent(entry)
    _forget_command_catalog()


def refresh_custom_agents() -> None:
    """Re-read the user's entries now and forget the last detection sweep."""
    global _custom_revision
    _custom_revision = -1
    _sync_custom_agents()
    invalidate_agent_detection()


def _registry() -> dict[str, WorkspaceAgent]:
    """Every entry, built-ins first, in UI order; the plain terminal stays LAST."""
    _sync_custom_agents()
    merged: dict[str, WorkspaceAgent] = {}
    shell = _AGENTS.get(PLAIN_TERMINAL)
    for name, agent in _AGENTS.items():
        if name != PLAIN_TERMINAL:
            merged[name] = agent
    merged.update(_CUSTOM_AGENTS)
    if shell is not None:
        merged[PLAIN_TERMINAL] = shell
    return merged


def register_agent(agent: WorkspaceAgent, *, replace: bool = False) -> WorkspaceAgent:
    """Add ``agent`` to the registry; refuses an existing name unless ``replace``."""
    if not agent.name:
        raise ValueError("A workspace agent needs a name.")
    if agent.name in _AGENTS and not replace:
        raise ValueError(f"A workspace agent called {agent.name!r} is already registered.")
    _AGENTS[agent.name] = agent
    _forget_command_catalog()
    return agent


def _forget_command_catalog() -> None:
    """Drop the cached command catalog that lists coding CLIs; never raises."""
    try:
        from dodaios.commands.registry import get_registry

        get_registry.cache_clear()
    except Exception:  # noqa: BLE001, S110 - the catalog is not this module's job
        pass
    # Rebuild the spoken-request parser only when already loaded (looked up in
    # sys.modules: this runs INSIDE the registry read its own rebuild performs).
    intent = sys.modules.get("dodaios.agentic_ide.intent")
    refresh = getattr(intent, "refresh_agent_patterns", None)
    if refresh is not None:
        try:
            refresh()
        except Exception as exc:  # noqa: BLE001 - a stale parser beats a failed registration
            log.warning("workspace agents: spoken-name patterns not refreshed: %s", exc)


def list_agents() -> list[WorkspaceAgent]:
    """Every registered entry, in registration order."""
    return list(_registry().values())


def get_agent(name: str) -> WorkspaceAgent | None:
    return _registry().get(name)


def behind_win_shim(spec: WorkspaceAgent, shim: str) -> tuple[str, ...] | None:
    """What the Windows ``.cmd`` shim would have launched, launched directly.

    ``cmd.exe`` re-parses arguments (a line break cuts a multi-line prompt).
    ``None`` when the declared path is missing: other layouts must fall back.
    """
    if spec.win_shim is None:
        return None
    target = Path(shim).resolve().parent.joinpath(*spec.win_shim.relative_path)
    if not target.is_file():
        return None
    if spec.win_shim.kind == "exe":
        return (str(target),)
    from dodaios.core.path_augment import resolve_node_executable

    node = resolve_node_executable()
    return (node, str(target)) if node else None


def agent_names() -> tuple[str, ...]:
    """Every registered name, plain terminal included."""
    return tuple(_registry())


def coding_agent_names() -> tuple[str, ...]:
    """Only the entries that run a coding agent, no plain shell."""
    return tuple(name for name, agent in _registry().items() if agent.is_coding_agent)


def needs_trust(name: str) -> bool:
    """Does opening this entry require pre-seeding folder trust?"""
    agent = get_agent(name)
    return bool(agent and agent.needs_trust)


# Snapshot of the SHIPPED coding agents at import; misses plugin and user entries.
# Runnability checks must call ``coding_agent_names()`` (live registry).
AGENT_NAMES: tuple[str, ...] = tuple(
    name for name, agent in _AGENTS.items() if agent.is_coding_agent
)


def install_command(name: str) -> str | None:
    """The shell command that installs the agent; ``None`` when no method is reachable here."""
    agent = get_agent(name)
    if agent is None or agent.spec is None:
        return None
    methods = agent.spec.install
    chosen = methods.recommended
    available = methods.available_methods()
    if chosen not in available:
        chosen = available[0] if available else None
    if chosen in (None, "manual"):
        return None
    from dodaios.clis.installer import CliInstaller

    argv = CliInstaller().build_command(agent.spec, chosen)  # type: ignore[arg-type]
    if not argv:
        return None
    return " ".join(argv)


def coding_agents() -> list[WorkspaceAgent]:
    """Every registered entry that runs a coding agent, in registration order."""
    return [a for a in _registry().values() if a.is_coding_agent]


def generation_of(name: str) -> str | None:
    """Which generation of ``name``'s CLI this machine has; ``None`` unless a vendor ships two."""
    agent = get_agent(name)
    if agent is None or agent.generation_probe is None:
        return None
    try:
        return agent.generation_probe()
    except Exception as exc:  # noqa: BLE001 - a probe must never block a launch
        log.warning("generation probe for %s failed: %s", name, exc)
        return None


def spoken_aliases() -> dict[str, str]:
    """Every spelling a transcript may carry, mapped to its entry."""
    out: dict[str, str] = {}
    for agent in _registry().values():
        for spelling in (*agent.spoken_aliases, *agent.spoken_aliases_needing_suffix):
            out.setdefault(spelling, agent.name)
    return out


def aliases_needing_suffix() -> dict[str, tuple[str, str]]:
    """Ambiguous spellings -> ``(entry, word that must follow)``: "cloud code", not "cloud"."""
    return {
        spelling: (agent.name, agent.alias_suffix)
        for agent in _registry().values()
        for spelling in agent.spoken_aliases_needing_suffix
    }


def reserved_call_signs() -> frozenset[str]:
    """Names a pane may never carry because a product answers to them.

    NARROW: registry key, first display word and spoken spellings only; every
    display word would reserve "Coding"/"Plan" and poison fuzzy names like "Cody".
    """
    names: set[str] = set()
    for agent in _registry().values():
        if not agent.is_coding_agent:
            continue
        names.add(agent.name.lower())
        first = agent.display_name.split()
        if first:
            names.add(first[0].lower())
        names.update(spelling.lower() for spelling in agent.spoken_aliases)
    # Single letters and names with spaces are not call-sign shaped; hyphens ok.
    return frozenset(
        n for n in names
        if len(n) > 1 and n.replace("-", "").isalnum()
    )


@dataclass(slots=True)
class AgentInfo:
    """Runtime status of one entry, returned by the /agents endpoints."""

    name: str
    display_name: str
    installed: bool
    version: str | None
    install_command: str | None
    launch_command: str
    kind: str = "cli"
    description: str = ""
    #: True for an entry the user added, so a surface can offer to edit it.
    custom: bool = False
    #: Where to fetch this entry's mark; empty = the UI's own asset or monogram.
    logo_url: str = ""


#: How long a detection sweep answers for: it spawns one subprocess per CLI and
#: stalls the event loop that delivers the wake microphone.
_DETECTION_TTL_S = 30.0

_detection_cache: tuple[float, list[AgentInfo]] | None = None
#: The sweep currently running; concurrent callers share ONE burst of subprocesses.
_detection_task: asyncio.Task[list[AgentInfo]] | None = None


def invalidate_agent_detection() -> None:
    """Forget the cached sweep; for callers that KNOW the answer just changed."""
    global _detection_cache
    _detection_cache = None


async def detect_agents(
    prober: CliStatusProber | None = None, *, force: bool = False
) -> list[AgentInfo]:
    """Probe every registered entry and report what this machine can run.

    The plain terminal answers from ``default_shell``. Cached for
    ``_DETECTION_TTL_S`` unless ``force``; an explicit ``prober`` bypasses the cache.
    """
    if prober is not None:
        return await _sweep_agents(prober)

    global _detection_cache, _detection_task
    cached = _detection_cache
    if not force and cached is not None and time.monotonic() - cached[0] < _DETECTION_TTL_S:
        return list(cached[1])

    running = _detection_task
    if running is not None and not running.done():
        try:
            same_loop = running.get_loop() is asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - no loop is not reachable here
            same_loop = False
        if same_loop:
            # Shielded: a caller that goes away must not cancel the shared sweep.
            return list(await asyncio.shield(running))

    task = asyncio.ensure_future(_sweep_agents(CliStatusProber()))
    _detection_task = task
    try:
        infos = await asyncio.shield(task)
    finally:
        if _detection_task is task:
            _detection_task = None
    _detection_cache = (time.monotonic(), infos)
    return list(infos)


def _augment_path() -> None:
    """Put the places CLIs install themselves onto PATH (idempotent, best-effort).

    A GUI-launched process has a minimal PATH.
    """
    try:
        from dodaios.core.path_augment import ensure_cli_paths

        ensure_cli_paths()
    except Exception:  # noqa: BLE001, S110 - PATH augmentation is best-effort
        pass


def _on_path(binary: str) -> bool:
    """Is ``binary`` resolvable the way a pane would? No subprocess (see :func:`_custom_agent`)."""
    import shutil

    if not binary:
        return False
    _augment_path()
    return shutil.which(binary) is not None


async def _sweep_agents(prober: CliStatusProber) -> list[AgentInfo]:
    """One real detection pass: shared prober for spec entries, PATH lookup (off the
    event loop) for user-added CLIs, shell check for the plain terminal."""
    registry = _registry()
    _augment_path()
    specs = [a.spec for a in registry.values() if a.spec is not None and a.name != "cursor"]
    statuses = await prober.probe_all(specs) if specs else {}
    if "cursor" in registry:
        statuses["cursor"] = await _cursor_status()
    shell = default_shell()
    unspecced = [a for a in registry.values() if a.spec is None and a.is_coding_agent]
    found: dict[str, bool] = {}
    if unspecced:
        found = await asyncio.to_thread(lambda: {a.name: _on_path(a.executable) for a in unspecced})

    return [
        _agent_info(
            agent,
            status=statuses.get(agent.name),
            shell=shell,
            on_path=found.get(agent.name, False),
        )
        for agent in registry.values()
    ]


def _agent_info(
    agent: WorkspaceAgent,
    *,
    status: Any | None,
    shell: Any | None,
    on_path: bool,
) -> AgentInfo:
    """One entry's status row; shared by sweep and recheck so they cannot disagree."""
    if agent.spec is None and agent.is_coding_agent:
        return AgentInfo(
            name=agent.name,
            display_name=agent.display_name,
            installed=on_path,
            # None on purpose: asking would be the subprocess this path avoids.
            version=None,
            install_command=None,
            launch_command=agent.launch_command or "",
            kind=agent.kind,
            description=agent.description,
            custom=agent.custom,
            logo_url=agent.logo_url,
        )
    if agent.spec is None:
        return AgentInfo(
            name=agent.name,
            display_name=agent.display_name,
            installed=shell is not None,
            version=shell.label if shell else None,
            install_command=None,
            launch_command="",
            kind=agent.kind,
            description=agent.description,
        )
    installed = bool(status and status.installed)
    # The documented binary may be missing while an installer alias is on PATH
    # (Cursor's ``cursor-agent``); a pane of it would still start.
    if not installed and agent.binary_aliases and agent.name != "cursor":
        installed = any(_on_path(name) for name in agent.binary_aliases)
    return AgentInfo(
        name=agent.name,
        display_name=agent.display_name,
        installed=installed,
        version=status.version if status and status.installed else None,
        install_command=install_command(agent.name),
        launch_command=agent.launch_command or "",
        kind=agent.kind,
        description=agent.description,
    )


async def recheck_agent(name: str) -> AgentInfo | None:
    """Probe ONE entry now and forget the cached sweep (cheap enough to poll after an install).

    Re-augments PATH first: the new binary may live where a GUI process never looked.
    """
    agent = get_agent(name)
    if agent is None:
        return None
    invalidate_agent_detection()
    await asyncio.to_thread(_augment_path)
    if name == "cursor":
        return _agent_info(agent, status=await _cursor_status(), shell=None, on_path=False)
    if agent.spec is not None:
        status = await CliStatusProber().probe(agent.spec)
        return _agent_info(agent, status=status, shell=None, on_path=False)
    if agent.is_coding_agent:
        on_path = await asyncio.to_thread(_on_path, agent.executable)
        return _agent_info(agent, status=None, shell=None, on_path=on_path)
    return _agent_info(agent, status=None, shell=default_shell(), on_path=False)


async def _cursor_status() -> CliStatus:
    from dodaios.workspace.cursor_cli import resolve_cursor_binary

    binary = await asyncio.to_thread(resolve_cursor_binary)
    return CliStatus(installed=binary is not None, binary_path=binary)


def _build_pty_argv(command: str) -> tuple[str, ...] | None:
    """Wrap a command in the default shell so it runs in a PTY and the shell stays open."""
    shell = default_shell()  # pwsh>powershell>cmd / $SHELL first
    if shell is None:
        return None
    path = shell.argv[0]
    if shell.id in ("pwsh", "powershell"):
        return (path, "-NoLogo", "-NoExit", "-Command", command)
    if shell.id == "cmd":
        return (path, "/k", command)
    # POSIX: run the command, then drop to an interactive shell.
    return (path, "-c", f"{command}; exec {path}")


def shell_run_argv(command: str) -> tuple[str, ...] | None:
    """Shell argv that runs ``command`` and EXITS with it.

    Unlike :func:`_build_pty_argv`: an IDE pane IS its agent, and a surviving
    shell would look like a running agent. ``None`` without a shell.
    """
    shell = default_shell()
    if shell is None:
        return None
    path = shell.argv[0]
    if shell.id in ("pwsh", "powershell"):
        return (path, "-NoLogo", "-NoProfile", "-Command", command)
    if shell.id == "cmd":
        # /c, never /k: the shell has to die with the agent.
        return (path, "/c", command)
    return (path, "-c", command)


def plain_terminal_argv() -> tuple[str, ...] | None:
    """Full PTY argv for a plain shell session: the shell's OWN interactive argv, no wrapper."""
    shell = default_shell()
    return tuple(shell.argv) if shell is not None else None


def build_agent_argv(name: str) -> tuple[str, ...] | None:
    """Full PTY argv that opens this entry, or None when it cannot run here."""
    agent = get_agent(name)
    if agent is None:
        return None
    if agent.launch_command is None:
        return plain_terminal_argv()
    from dodaios.workspace.launch_picks import launch_argv

    # Only catalog-owned permission defaults; request-supplied picks are not accepted.
    defaults = launch_argv(name)
    command = " ".join((agent.launch_command, *defaults))
    return _build_pty_argv(command)


def build_install_argv(name: str) -> tuple[str, ...] | None:
    """Full PTY argv that runs the agent's install command in a shell."""
    cmd = install_command(name)
    return _build_pty_argv(cmd) if cmd else None


def pty_available() -> bool:
    """True when this host can run an in-app PTY (a shell + a real PTY backend)."""
    if default_shell() is None:
        return False
    try:
        from dodaios.terminal.backend import make_pty_backend

        return type(make_pty_backend()).__name__ != "NullPtyBackend"
    except Exception:  # noqa: BLE001
        return False


__all__ = [
    "AGENT_NAMES",
    "ANTIGRAVITY_TRUST",
    "CLAUDE_TRUST",
    "CODEX_TRUST",
    "GROK_TRUST",
    "KIMI_CURRENT",
    "KIMI_LEGACY",
    "PLAIN_TERMINAL",
    "AccountSpec",
    "AgentInfo",
    "TrustSpec",
    "WinShim",
    "WorkspaceAgent",
    "agent_names",
    "aliases_needing_suffix",
    "build_agent_argv",
    "build_install_argv",
    "builtin_names",
    "coding_agent_names",
    "coding_agents",
    "detect_agents",
    "generation_of",
    "get_agent",
    "glm_spawn_env",
    "install_command",
    "invalidate_agent_detection",
    "kimi_generation",
    "list_agents",
    "make_cli_agent",
    "needs_trust",
    "plain_terminal_argv",
    "pty_available",
    "recheck_agent",
    "refresh_custom_agents",
    "register_agent",
    "reserved_call_signs",
    "shell_run_argv",
    "spoken_aliases",
]

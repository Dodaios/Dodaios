"""DeepSeek Harness and user-defined CLI planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat.runner_cli import base as _rc_base
from dodaios.agent_chat.runner_cli.base import (
    CLI_BINARIES,
    CliPlan,
    CliUnavailable,
    _argv_prompt,
    _behind_shim,
    _identity_message,
)


def dsh_argv_prefix() -> list[str]:
    binary = _rc_base._which(*CLI_BINARIES["dsh-cli"])
    if not binary:
        raise CliUnavailable("DeepSeek Harness (dsh) is not installed or not on PATH.")
    return _behind_shim(binary, "deepseek-harness")


def plan_dsh(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None = None,
) -> CliPlan:
    """DeepSeek Harness's headless profile: one task in, the final message out.

    No model flag, no session, no tool stream — the harness keeps its key and
    its policy in its own settings (``dodaios.workspace.agents``). What comes
    back is text, and the chat shows it as the answer.
    """
    prompt = _identity_message("dsh-cli", prompt, identity, resume)
    prefix = dsh_argv_prefix()
    argv = [*prefix, "--profile", "headless", _argv_prompt(prefix, prompt)]
    env = _rc_base._registry_env("deepseek-harness", _rc_base._account_env("deepseek-harness"))
    return CliPlan(argv, env, None, "text", None)


def plan_custom_cli(
    *,
    provider: str,
    session_id: str = "",
    prompt: str,
    cwd: Path,
    resume: str | None = None,
    **_unused: Any,
) -> CliPlan:
    """A CLI the user added (``dodaios.workspace.custom_clis``), run headless.

    The one generic runner behind every ``custom-<id>`` thread provider: it
    looks the entry up, expands its headless template (``{prompt}`` /
    ``{session}``; no ``{prompt}`` = the message goes to stdin) and runs it in
    plain-text mode like the DeepSeek Harness — stdout is the answer. The
    working folder is the thread's; the environment is the grid pane's.
    """
    import uuid

    from dodaios.agent_chat.catalog import CUSTOM_ROW_PREFIX
    from dodaios.workspace import custom_clis

    entry_id = (
        provider[len(CUSTOM_ROW_PREFIX) :] if provider.startswith(CUSTOM_ROW_PREFIX) else provider
    )
    entry = custom_clis.get_custom_cli(entry_id)
    if entry is None or not entry.headless_command:
        raise CliUnavailable(
            "This CLI no longer has a headless command. Re-add it in the CLI wizard."
        )
    resuming = bool(resume and entry.headless_resume)
    template = entry.headless_resume if resuming else entry.headless_command
    chosen = (
        str(resume)
        if resuming
        else (uuid.uuid4().hex if (entry.headless_resume or "{session}" in template) else "")
    )
    argv, on_stdin = custom_clis.expand_template(template, prompt=prompt, session=chosen)
    overrides: dict[str, str] = {}
    while argv and custom_clis._is_assignment(argv[0]):  # noqa: SLF001 — same parser as the grid
        name, _, value = argv.pop(0).partition("=")
        overrides[name] = value
    if not argv:
        raise CliUnavailable("The headless command of this CLI is empty.")
    binary = _rc_base._which(argv[0])
    if binary is None:
        raise CliUnavailable(f"{entry.display_name} ({argv[0]}) is not installed or not on PATH.")
    argv[0] = binary
    env = _rc_base._registry_env(entry.id, _rc_base._account_env(entry.id))
    env.update(overrides)
    return CliPlan(argv, env, prompt if on_stdin else None, "text", chosen or None)

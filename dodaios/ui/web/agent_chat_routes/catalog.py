"""The provider catalog, composer tools, typeahead and provider health."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
)

from dodaios.agent_chat import typeahead
from dodaios.agent_chat.catalog import ACCESS_ACCOUNTS, claude_code_models, rows_for
from dodaios.agent_chat.permissions import (
    default_permission,
    ladder_key,
    permission_modes,
)
from dodaios.agent_chat.surface_kits import kit_for
from dodaios.agent_chat.tools import shell_label
from dodaios.ui.web import agent_chat_routes as _r
from dodaios.ui.web.agent_chat_routes.models import (
    ProviderHealthResponse,
    ProviderHealthRow,
    SurfaceName,
)

router = APIRouter()


# ------------------------------------------------------------------ catalog


@router.get("/catalog")
async def get_catalog(
    request: Request,
    surface: SurfaceName = "agent",
    account_id: str = "",
    session_id: str = "",
    cwd: str | None = None,
) -> dict[str, Any]:
    """Provider rows for the composer's picker.

    Static shape from ``dodaios.agent_chat.catalog`` plus two live facts per
    row: which runner answers on this machine (for ``surface``) and whether
    that runner's binary is installed. The picker reads credential state from
    ``/api/jarvis-agent/status`` for worker providers. Chat-only API seats
    report shared key presence here. On the Jarvis surface every row shows
    the one Jarvis ladder (``permissions.JARVIS_LADDER``).

    Which rows a surface gets is ``catalog.rows_for``: the front page's chat
    has no CLI seats, so it is offered only the providers whose own API a
    brain plugin drives — and no CLI is probed for its model list either.
    """
    svc = await _r._async_service(request)
    cli_seats = kit_for(surface).cli_seats
    from dodaios.agent_chat.runner_cli import cli_catalog_scope

    if session_id:
        session = await _r._session_or_bound_agent_chat(svc, session_id)
        if session is None or session.surface != surface:
            raise HTTPException(status_code=404, detail="Chat session not found")
        account_id = session.account_id
        cwd = session.cwd
    if account_id and account_id not in ACCESS_ACCOUNTS:
        # "subscription" / "api-key" pin a way of paying, not a login: the
        # seat's active login answers for them (``runner_cli._login_id``).
        from dodaios import agent_accounts

        if agent_accounts.resolve(account_id) is None:
            raise HTTPException(status_code=400, detail="Unknown subscription account")
    folder = _r._folder_for(surface, cwd)
    with cli_catalog_scope(
        account_id=account_id,
        cwd=Path(folder) if folder else None,
        ignore_user_config=kit_for(surface).brain_runner and cli_seats,
    ):
        live_models = await _r._live_cli_models() if cli_seats else {}
    # Off the event loop: every CLI row resolves its binary on PATH, and that
    # many ``shutil.which`` walks cost ~0.3 s on a Windows PATH — a stall the
    # whole app shared on every composer open (AP-26 spirit, async-def freeze).
    rows = await asyncio.to_thread(_r._catalog_rows, surface, live_models)
    return {
        "providers": rows,
        "default_cwd": svc.default_cwd(surface),
        "shell": shell_label(),
        # This backend takes a plan's review with its answer (plan_review.py).
        # A window newer than its backend reads the missing flag and keeps the
        # plan read-only, instead of sending edits that would be dropped.
        "plan_review": True,
        "selection": (
            selection.to_dict()
            if surface == "jarvis" and (selection := svc.store.chat_selection()) is not None
            else None
        ),
    }


def _catalog_rows(
    surface: str, live_models: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """The provider rows for ``surface`` with this machine's runner facts."""
    from dodaios.agent_chat import agent_provider_prefs
    from dodaios.core.config import get_provider_secret
    from dodaios.missions.worker_runtime.provider_map import JARVIS_TO_WORKER_SLUG

    # Every surface's rows carry the models hidden on the API Keys page, and
    # every model picker leaves them out. The on/off switch is the agents'
    # own: other surfaces keep every seat.
    prefs = agent_provider_prefs.load()
    agents = surface == agent_provider_prefs.AGENT_SURFACE
    plain = kit_for(surface).plain
    rows: list[dict[str, Any]] = []
    for row in rows_for(surface):
        d = row.to_dict()
        runner = _r.resolve_runner(row.id, surface=surface)
        d["runner"] = runner
        d["cli_installed"] = _r._cli_installed(runner) if runner not in ("api", "brain") else None
        if runner in ("api", "brain") and not row.keyless and row.id not in JARVIS_TO_WORKER_SLUG:
            d["api_key_set"] = bool(get_provider_secret(row.id))
        # A CLI that publishes its own model list (agy, Codex) overrides the
        # curated fallback with what THIS account can actually pick.
        if d["cli_installed"] and runner in live_models:
            d["curated_models"] = live_models[runner]
        # The dual row: Claude Code takes its own ids and aliases; with only
        # an API key — and on a surface with no CLI seats, always — the
        # Anthropic catalog route lists the models live.
        if row.id == "claude-api":
            if runner == "claude-cli":
                d["curated_models"] = [m.to_dict() for m in claude_code_models()]
                d["models_source"] = "curated"
            else:
                d["models_source"] = "live"
                # "Ultracode" is a Claude Code switch; the API has no such step.
                d["effort_levels"] = [lvl for lvl in d["effort_levels"] if lvl != "ultracode"]
        # The permission ladder is the RUNNER's (Claude Code's modes when the
        # CLI answers, the API runner's when only a key is there), so the
        # composer shows the words the thing that runs actually understands —
        # except on the Jarvis surface, where one ladder serves every seat.
        ladder = ladder_key(surface, runner)
        d["permission_modes"] = [m.to_dict() for m in permission_modes(ladder)]
        d["default_permission_mode"] = default_permission(ladder)
        # Which characters open the composer's typeahead on this seat —
        # decided here, from the runner, so the box never offers a "/" list
        # to a seat that would read it as plain text.
        # A plain chat has nothing to complete against: no commands, no files.
        d["typeahead"] = [] if plain else list(typeahead.triggers_for(runner, surface))
        if agents:
            d["enabled"] = prefs.enabled(row.id)
        d["hidden_models"] = list(prefs.hidden(row.id))
        rows.append(d)
    return rows


# ----------------------------------------------------------- typeahead


@router.get("/tools", openapi_extra={"x-jarvis-readonly": True})
async def get_composer_tools(
    request: Request,
    provider: str = "",
    model: str = "",
    q: str = Query("", max_length=200),
    category: str = "",
    cwd: str | None = None,
    stance: str = "ask",
) -> dict[str, Any]:
    """Discover tools for the Dodaios chat without executing any capability."""
    from dodaios.agent_chat.tool_catalog import discover

    svc = await _r._async_service(request)
    if provider and not any(row.id == provider for row in rows_for("jarvis")):
        raise HTTPException(status_code=400, detail="Unknown chat provider")
    pending = asyncio.create_task(
        discover(
            provider=provider,
            model=model,
            query=q,
            category=category,
            cwd=_r._validate_cwd(cwd) or svc.default_cwd("jarvis"),
            stance=stance,
        )
    )
    try:
        while not pending.done():
            await asyncio.wait({pending}, timeout=0.1)
            if await request.is_disconnected():
                pending.cancel()
                raise HTTPException(status_code=499, detail="Search cancelled")
        return await pending
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@router.get("/typeahead", openapi_extra={"x-jarvis-readonly": True})
async def get_typeahead(
    request: Request,
    trigger: str = Query(..., min_length=1, max_length=1),
    surface: SurfaceName = "agent",
    provider: str = "",
    cwd: str | None = None,
    q: str = Query("", max_length=200),
    limit: int = Query(40, ge=1, le=1000),
    session_id: str = "",
) -> dict[str, Any]:
    """What the composer lists after ``/``, ``@`` or ``$`` on one seat.

    The seat is (surface, provider) resolved to its runner exactly as a turn
    would be; the folder is the chat's. A Claude Code seat's ``/`` rows are the
    commands the CLI itself reports; the other rows are read from the disk the
    runner reads (``dodaios.agent_chat.typeahead``) — skills, plugins, the
    files under the folder — and a trigger the seat does not honour answers
    with an empty list. The composer reads a ``/`` or ``$`` list whole and
    filters it itself, hence the high ``limit``.
    """
    svc = await _r._async_service(request)
    runner = _r.resolve_runner(provider, surface=surface) if provider else "api"
    folder = _r._validate_cwd(cwd) or svc.default_cwd(surface)
    # A society chat completes its own teammates, capabilities and learned
    # skills, so the list needs to know WHICH agent is typing.
    agent_id = ""
    if surface == "society" and session_id:
        from dodaios.society.surface import agent_id_of

        agent_id = agent_id_of(session_id) or ""
    return await asyncio.to_thread(
        typeahead.suggest,
        runner=runner,
        cwd=folder,
        trigger=trigger,
        query=q,
        limit=limit,
        surface=surface,
        agent_id=agent_id,
    )


def _cli_auth_status(runner: str) -> Any | None:
    """The vendor CLI's own login snapshot. ``None`` if ``runner`` is not a CLI
    this app can read the login of (OpenCode, Kimi and the DeepSeek harness
    keep theirs where no reader has been verified — see the registry)."""
    if runner == "glm-cli":
        # GLM Coding Plan is Claude Code plus a Z.ai key: the key IS the login.
        from types import SimpleNamespace

        from dodaios.workspace.agents import glm_spawn_env

        configured = glm_spawn_env() is not None
        return SimpleNamespace(
            connected=configured,
            mode="subscription",
            message="GLM Coding Plan: Z.ai key saved"
            if configured
            else "GLM Coding Plan: no Z.ai key — add one under API Keys",
        )
    if runner == "claude-cli":
        from dodaios.claude_auth import ClaudeAuthService

        return ClaudeAuthService().status()
    if runner == "codex-cli":
        from dodaios.codex_auth import CodexAuthService

        return CodexAuthService().status()
    if runner == "agy-cli":
        from dodaios.google_cli.auth_service import GoogleCliAuthService

        return GoogleCliAuthService().status()
    if runner == "grok-cli":
        from dodaios.grok_build_auth import GrokBuildAuthService

        return GrokBuildAuthService().status()
    return None


def _cli_subscription_connected(runner: str, st: Any) -> bool:
    """Whether ``st`` is a login this CLI seat can actually spend.

    Claude and Grok Build report ``connected=True`` for a stored API key as
    well; that key belongs to a different picker row. Antigravity's
    ``api_key`` mode is the Gemini key, same split. Codex's ``connected``
    is the CLI's own auth.json (ChatGPT login or a key the CLI itself
    holds), which is what ``codex exec`` uses.
    """
    connected = bool(getattr(st, "connected", False))
    mode = (getattr(st, "mode", None) or "").strip().lower()
    if runner == "claude-cli":
        return connected and mode == "subscription"
    if runner == "grok-cli":
        return connected and mode == "subscription"
    if runner == "agy-cli":
        return connected and mode == "oauth-personal"
    return connected


def _cli_login_snapshot(runner: str) -> tuple[str, str, str]:
    """Login presence for a vendor CLI seat. Never a live API-key call.

    Returns ``(status, reason, detail)``. A signed-in subscription is
    ``ok``; anything else is ``needs_setup`` so the picker does not borrow
    API-key words ("Key rejected") for a seat that has no key.
    """
    try:
        st = _r._cli_auth_status(runner)
    except Exception as exc:  # noqa: BLE001 — one bad CLI must not lose the sweep
        _r.log.info("agent chat: CLI login check for %s failed: %s", runner, exc)
        return (
            "unknown",
            "check_failed",
            f"The check itself failed ({type(exc).__name__})",
        )
    if st is None:
        # The CLI keeps its own login and this app has no verified reader for
        # it: no dot rather than a guessed one (the turn itself says if the
        # CLI is signed out).
        return "unknown", "self_managed", f"{runner}: keeps its own login"
    connected = _r._cli_subscription_connected(runner, st)
    detail = (getattr(st, "message", None) or "").strip() or (
        f"{runner}: signed in" if connected else f"{runner}: not signed in"
    )
    if connected:
        return "ok", "ok", detail
    return "needs_setup", "not_configured", detail


async def _one_provider_health(cfg: Any, provider_id: str, *, surface: str) -> ProviderHealthRow:
    """One row, never raising: a broken check is ``unknown``, not a 500."""
    runner = _r.resolve_runner(provider_id, surface=surface)
    if runner in _r._CLI_RUNNERS:
        try:
            status, reason, detail = await asyncio.to_thread(_r._cli_login_snapshot, runner)
        except Exception as exc:  # noqa: BLE001 — one bad row must not lose the sweep
            _r.log.info("agent chat: CLI health check for %s failed: %s", provider_id, exc)
            return ProviderHealthRow(
                provider=provider_id,
                status="unknown",
                reason="check_failed",
                detail=f"The check itself failed ({type(exc).__name__})",
            )
        return ProviderHealthRow(provider=provider_id, status=status, reason=reason, detail=detail)

    from dodaios.ui.web.provider_routes import provider_health

    try:
        health = await provider_health(cfg, provider_id)
    except TimeoutError:
        return ProviderHealthRow(
            provider=provider_id, status="unknown", reason="timeout", detail="No answer in time"
        )
    except Exception as exc:  # noqa: BLE001 — one bad row must not lose the sweep
        _r.log.info("agent chat: health check for %s failed: %s", provider_id, exc)
        return ProviderHealthRow(
            provider=provider_id,
            status="unknown",
            reason="check_failed",
            detail=f"The check itself failed ({type(exc).__name__})",
        )
    return ProviderHealthRow(
        provider=provider_id,
        status=health.status,
        reason=health.reason,
        detail=health.detail,
    )


@router.get("/provider-health")
async def get_provider_health(
    request: Request, surface: SurfaceName = "agent", refresh: bool = False
) -> ProviderHealthResponse:
    """Which of ``surface``'s rows actually answer right now.

    The composer shows whether a provider is CONNECTED — a key is saved. That
    is not the same as usable: a key can be revoked, an account can run out of
    credits, an endpoint can be down. On the maintainer's own box on
    2026-08-26, four of nine connected rows were in one of those states, and
    the picker offered all nine as if they were equal.

    API / brain seats report what the API-Keys screen's tab dots report
    (``provider_routes.provider_health``): key presence plus the outcome of
    that provider's last REAL call. Nothing here sends a request — until
    2026-09-30 every open of the chat spent a paid one-token completion per
    keyed provider. A seat never used since its key was saved is ``unknown``
    and draws no dot. A vendor CLI seat spends a subscription login, so this
    reports that login instead. The dual Claude row is why the split exists —
    its catalog id is ``claude-api``, and the API-key verdict would otherwise
    paint "Key rejected" on a Claude Code seat that is signed in.

    Nothing waits for this: the composer paints from the catalog and folds
    these in when they land. A row that does not finish inside the sweep
    ceiling comes back ``unknown`` and is drawn exactly as it was before.
    """
    (await _r._async_service(request))  # 503 like every other route when the chat is off
    from dodaios.brain.provider_health_ledger import ledger_version
    from dodaios.core.config import secret_generation

    now = time.monotonic()
    version = (ledger_version(), secret_generation())
    cached = _r._health_cache.get(surface)
    if cached and not refresh and cached[1] == version and (now - cached[0]) < _r._HEALTH_TTL_S:
        return ProviderHealthResponse(providers=cached[2], checked_at=cached[0], cached=True)

    from dodaios.ui.web.provider_routes import _resolve_cfg

    cfg = _resolve_cfg(request)
    ids = [row.id for row in rows_for(surface)]
    tasks = {
        pid: asyncio.create_task(_r._one_provider_health(cfg, pid, surface=surface)) for pid in ids
    }
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks.values(), return_exceptions=True), timeout=_r._HEALTH_SWEEP_S
        )
    except TimeoutError:
        _r.log.info("agent chat: provider health sweep hit its %.0fs ceiling", _r._HEALTH_SWEEP_S)
    rows: list[ProviderHealthRow] = []
    for pid, task in tasks.items():
        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is None:
                rows.append(task.result())
                continue
        task.cancel()
        rows.append(
            ProviderHealthRow(
                provider=pid, status="unknown", reason="timeout", detail="No answer in time"
            )
        )
    _r._health_cache[surface] = (now, version, rows)
    return ProviderHealthResponse(providers=rows, checked_at=now, cached=False)

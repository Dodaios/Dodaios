"""Standalone FastAPI app — for ``python -m conductor serve``.

In embedded mode (Jarvis has a web server), only ``router`` is imported
from ``routes.py``; this app here is the entry point for a standalone
Conductor deployment.

The standalone app runs shell commands on request, so it is locked down:
see ``security.StandaloneGuard`` (Host allowlist, Origin allowlist, bearer
token on every route except ``/api/health`` and the webhook). There is no
CORS unless origins are listed in ``CONDUCTOR_CORS_ORIGINS``.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core.runner import Runner
from ..core.scheduler import Scheduler
from ..core.store import ConductorStore
from .routes import router
from .security import (
    ALLOWED_HOSTS_ENV,
    CORS_ORIGINS_ENV,
    StandaloneGuard,
    resolve_api_token,
    split_env_list,
)


def create_app(
    store: ConductorStore | None = None,
    start_scheduler: bool = True,
    *,
    api_token: str | None = None,
    allowed_hosts: list[str] | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Creates a standalone FastAPI app including store + runner + scheduler.

    Lifecycle is wired via startup/shutdown events. ``store`` can be
    provided explicitly (e.g. tests with a tmp DB); the default is
    ``~/.conductor/conductor.sqlite``.

    ``api_token`` defaults to ``CONDUCTOR_API_TOKEN`` or a fresh random
    token (``app.state.conductor_api_token``). ``allowed_hosts`` adds
    names to the loopback Host allowlist (default from
    ``CONDUCTOR_ALLOWED_HOSTS``); ``cors_origins`` lists the only browser
    origins that may call the API (default from ``CONDUCTOR_CORS_ORIGINS``,
    empty = no browser origin at all).
    """
    token = resolve_api_token(api_token)
    hosts = (allowed_hosts if allowed_hosts is not None
             else split_env_list(os.environ.get(ALLOWED_HOSTS_ENV)))
    origins = (cors_origins if cors_origins is not None
               else split_env_list(os.environ.get(CORS_ORIGINS_ENV)))

    app = FastAPI(
        title="Conductor — Workflow & Schedule Hub",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )
    # Added last = outermost: refuses before CORS or any route sees it.
    app.add_middleware(
        StandaloneGuard, token=token, allowed_hosts=hosts, allowed_origins=origins,
    )
    app.state.conductor_api_token = token
    app.include_router(router)

    active_store = store or ConductorStore()
    runner = Runner(active_store)
    scheduler = Scheduler(active_store, runner)

    app.state.conductor_store = active_store
    app.state.conductor_runner = runner
    app.state.conductor_scheduler = scheduler

    @app.on_event("startup")
    async def _startup() -> None:
        await active_store.init()
        await active_store.cleanup_interrupted_runs()
        # Plant seed jobs on first startup.
        from ..core.seed import ensure_seed_jobs
        try:
            added = await ensure_seed_jobs(active_store)
            if added:
                import logging
                logging.getLogger(__name__).info(
                    "Conductor seed: planting %d jobs", added,
                )
        except Exception:  # noqa: BLE001
            pass
        if start_scheduler:
            scheduler.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await scheduler.stop()
        await active_store.close()

    @app.get("/api/health")
    async def _health() -> dict[str, str]:
        return {"ok": "true", "version": "0.1.0", "tool": "conductor"}

    return app

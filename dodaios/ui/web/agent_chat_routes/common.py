"""Constants and shared state of the agent-chat routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from dodaios.agent_chat import runner_cli
from dodaios.agent_chat.app_service import service_from_state
from dodaios.ui.web.agent_chat_routes.models import (
    ProviderHealthRow,
)

log = logging.getLogger("dodaios.ui.web.agent_chat_routes")


#: The same names, as data — a multipart form field cannot be typed by a
#: ``Literal`` without turning an unknown surface into a 422 on a file the
#: person just dropped.
SURFACE_NAMES: frozenset[str] = frozenset({"jarvis", "agent", "local-models", "society", "side"})


#: Surfaces that never appear in an unfiltered session list: an agent's
#: canonical chat belongs to its model card, and the IDE's side chat to its
#: side panel, not to the IDE's threads or the front page's history.
HIDDEN_SURFACES: frozenset[str] = frozenset({"society", "side"})


_WS_PING_S = 20.0


# ------------------------------------------------------------------ helpers


# The one builder of the service, under one lock: two services would both
# carry on the hosted turns, and the one the window talks to would lose them.
_service_from_state = service_from_state


#: How long after the server is up the boot reattach waits, so it never sits
#: on the path to a usable window (AP-26).
_REATTACH_DELAY_S: Final = 2.0


#: How long one sweep stands. The sweep sends nothing to any provider (it
#: reads key presence, CLI login state and the passive record of real calls),
#: but the CLI login reads are not free, so a sweep is reused for a while — and
#: dropped the moment the health record changes (see ``get_provider_health``).
_HEALTH_TTL_S: Final[float] = 300.0

#: The whole sweep's ceiling. A row whose (local) check has not finished when
#: this runs out is reported ``unknown`` and draws no dot.
_HEALTH_SWEEP_S: Final[float] = 20.0


#: surface -> (checked_at, (health-record version, credential generation), rows).
#: Process-local, like every other short cache in the routes; a restart simply
#: re-sweeps. Keyed on both counters so a new real-call outcome AND any key
#: saved or deleted — through whichever path — drop the sweep at once.
_health_cache: dict[str, tuple[float, tuple[int, int], list[ProviderHealthRow]]] = {}


#: Vendor CLI runners. Their credential is a subscription login, not a key,
#: so the API-Keys one-token probe is the wrong check: the dual Claude row
#: is catalogued as ``claude-api``, and that probe hits Anthropic's endpoint
#: and paints "Key rejected" on a Claude Code seat that is signed in.
_CLI_RUNNERS: Final[frozenset[str]] = runner_cli.CLI_RUNNERS


#: ``StandingError.code`` -> HTTP status. Anything unknown reads as a bad request.
_STANDING_STATUS: Final[dict[str, int]] = {
    "not_found": 404,
    "invalid": 422,
    "state": 409,
    "limit": 409,
    "unavailable": 503,
}

#: The owner's clicks on one standing task, and the service call each one is.
_STANDING_ACTIONS: Final[dict[str, str]] = {
    "accept": "accept",
    "decline": "decline",
    "pause": "pause",
    "resume": "resume",
    "end": "end",
    "run": "run_now",
}


#: Warm-ups in flight, by chat session (one at a time; kept so they finish).
_WARMING: dict[str, asyncio.Task[bool]] = {}

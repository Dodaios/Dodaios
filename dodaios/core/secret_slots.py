"""Every name a credential is stored under, as far as it can be known.

``set_secret(key, value)`` files a credential under ``key`` in the OS
credential store. A credential store cannot be listed portably, so anything
that has to visit every stored credential (the one-time copy to a renamed
service, the uninstaller) needs the names from here:

* ``KNOWN_SECRET_KEYS`` -- the fixed names, spelled as literals or module
  constants at the place that saves them.
* ``DYNAMIC_SLOT_SOURCES`` -- every module that computes a name at runtime
  (from a table, a catalog, or a record the user created), with what the
  names look like and, where it is cheap and side-effect free, how to list
  the ones that exist right now.

``tests/unit/core/test_secret_slots_coverage.py`` reads every ``set_secret``
and ``set_password`` call in the package: a fixed name must be listed here, and
a computed one must come from a module in ``DYNAMIC_SLOT_SOURCES``. A name
that cannot be listed is still safe: ``dodaios.core.config.get_secret`` reads
the legacy service whenever the current one has nothing for a slot, so the
listing is an optimisation for the copy and a completeness aid for the
uninstaller, never the thing that keeps a credential reachable.

Importing this module imports nothing else from the package; each lister
imports its source lazily and only when called.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

log = logging.getLogger(__name__)

# The fixed names: each is saved (or read) under exactly this spelling.
KNOWN_SECRET_KEYS: frozenset[str] = frozenset(
    {
        # dodaios.core.control_key.KEYRING_SLOT
        "jarvis_control_api_key",
        # dodaios.admin.client.ADMIN_HMAC_KEY
        "jarvis_admin_hmac",
        # dodaios.channels.telegram, dodaios.marketplace.telegram_connect
        "telegram_bot_token",
        # dodaios.marketplace.discord_connect
        "discord_bot_token",
        # dodaios.friends.identity.PRIVKEY_SECRET_KEY
        "socials_node_privkey",
        # dodaios.computers.identity.PRIVATE_KEY_SECRET
        "computers_ssh_private_key",
        # dodaios.ui.web.telephony_routes
        "twilio_auth_token",
        # dodaios.core.config (team proxy credential)
        "team_proxy_token",
        # Read by name in provider adapters; saved through the wizard table.
        "cartesia_api_key",
        "codex_openai_api_key",
        "huggingface",
        "inworld_api_key",
        "openai_api_key",
        "zai_api_key",
    }
)


@dataclass(frozen=True)
class SlotSource:
    """A module that computes credential names at runtime."""

    # What the names look like, for a reader of this table.
    shape: str
    # Lists the names that exist right now, or ``None`` when that needs work
    # this module should not do (a database query, a network call).
    lister: Callable[[], Iterable[str]] | None = None


def _wizard_keys() -> Iterable[str]:
    from dodaios.setup.wizard import SECRETS

    return (spec.key for spec in SECRETS)


def _provider_candidate_keys() -> Iterable[str]:
    from dodaios.core.config import PROVIDER_SECRET_CANDIDATES

    return (key for pairs in PROVIDER_SECRET_CANDIDATES.values() for key, _env in pairs)


def _cloud_provider_keys() -> Iterable[str]:
    from dodaios.computers.cloud import PROVIDERS

    return (spec.keyring_slot for spec in PROVIDERS.values())


def _computer_keys() -> Iterable[str]:
    from dodaios.computers.service import (
        _passphrase_slot,
        _password_slot,
        _private_key_slot,
    )
    from dodaios.computers.store import ComputerStore

    for computer in ComputerStore().all():
        yield _password_slot(computer.id)
        yield _private_key_slot(computer.id)
        yield _passphrase_slot(computer.id)


def _paired_server_keys() -> Iterable[str]:
    from dodaios.computers.pairing import _slot, get_pairing

    return (_slot(server.id) for server in get_pairing().servers())


def _cli_keys() -> Iterable[str]:
    from dodaios.clis.catalog import load_catalog

    return (key for spec in load_catalog().values() for key in spec.auth.secret_keys)


def _mcp_keys() -> Iterable[str]:
    from dodaios.mcp.registry import MCPRegistry

    registry = MCPRegistry()
    registry.load_from_mcp_json()
    return (key for spec in registry.all_specs() for key in spec.required_auth)


def _oauth_families() -> set[str]:
    from dodaios.marketplace.catalog_data import load_catalog
    from dodaios.marketplace.publisher_clients import (
        SHIPPED_PUBLIC_CLIENT_IDS,
        SHIPPED_TOKEN_BROKERS,
    )

    families = set(SHIPPED_PUBLIC_CLIENT_IDS) | set(SHIPPED_TOKEN_BROKERS)
    families.update(
        plugin.oauth_client_family
        for plugin in load_catalog().plugins
        if plugin.oauth_client_family
    )
    return families


def _oauth_client_keys() -> Iterable[str]:
    from dodaios.marketplace.publisher_clients import (
        publisher_secret_names,
        publisher_secret_names_secret,
    )

    for family in sorted(_oauth_families()):
        yield f"{family}_oauth_client_id"
        yield f"{family}_oauth_client_secret"
        yield publisher_secret_names(family)[0]
        yield publisher_secret_names_secret(family)[0]


def _plugin_token_keys() -> Iterable[str]:
    from dodaios.marketplace.catalog_data import load_catalog
    from dodaios.marketplace.token_store import _keyring_key

    # The head entry of each plugin's token blob. A long blob continues in
    # chunk entries named after the head; those are read through the legacy
    # fallback until the plugin saves its tokens again.
    for plugin in load_catalog().plugins:
        try:
            yield _keyring_key(plugin.id)
        except ValueError:
            # The token store refuses this id, so nothing can be stored under it.
            log.debug("catalog plugin id %r has no token slot", plugin.id)


_SOURCES: dict[str, SlotSource] = {
    "dodaios.core.config": SlotSource(
        "provider slots of PROVIDER_SECRET_CANDIDATES", _provider_candidate_keys
    ),
    "dodaios.setup.wizard": SlotSource("the keys of the SECRETS table", _wizard_keys),
    "dodaios.ui.web.control_routes": SlotSource(
        "a key of the wizard SECRETS table (ALLOWED_SECRET_KEYS)", _wizard_keys
    ),
    "dodaios.ui.web.provider_routes": SlotSource(
        "a key of the wizard SECRETS table, or its provider family's slot", _wizard_keys
    ),
    "dodaios.computers.cloud": SlotSource(
        "<provider>_api_token from the PROVIDERS table", _cloud_provider_keys
    ),
    "dodaios.computers.service": SlotSource(
        "computer_password_<id>, computer_private_key_<id>, computer_key_passphrase_<id>",
        _computer_keys,
    ),
    "dodaios.computers.pairing": SlotSource("paired_server_<id>", _paired_server_keys),
    "dodaios.clis.auth": SlotSource(
        "auth.secret_keys of a CLI catalog entry", _cli_keys
    ),
    "dodaios.ui.web.mcp_routes": SlotSource(
        "required_auth of an MCP server spec", _mcp_keys
    ),
    "dodaios.marketplace.publisher_clients": SlotSource(
        "<family>_oauth_client_id/_secret, publisher_<family>_oauth_client_id/_secret",
        _oauth_client_keys,
    ),
    "dodaios.marketplace.token_store": SlotSource(
        "plugin_<id>_tokens, plus chunk entries <head>__<n> / <head>__b<bank>_<n>",
        _plugin_token_keys,
    ),
    "dodaios.society.credentials": SlotSource("society_credential.<agent>.<ENV_NAME>"),
    "dodaios.tasks.source_credentials": SlotSource(
        "routine_source_<id>_<created_at_ns>_<field>"
    ),
    "dodaios.tasks.webhook_auth": SlotSource("routine_webhook_<id>_<created_at_ns>"),
    "dodaios.ui.web.routine_hooks_routes": SlotSource(
        "routine_webhook_<id>_<created_at_ns> (dodaios.tasks.webhook_auth)"
    ),
}

#: Module name -> how it names credentials at runtime.
DYNAMIC_SLOT_SOURCES: Mapping[str, SlotSource] = MappingProxyType(_SOURCES)


def dynamic_secret_keys() -> frozenset[str]:
    """The computed names that exist right now, from every source that can list them.

    A source that fails (a store that does not exist yet, a catalog that does
    not parse) is logged and skipped: the others still count.
    """
    found: set[str] = set()
    for module, source in DYNAMIC_SLOT_SOURCES.items():
        if source.lister is None:
            continue
        try:
            found.update(key for key in source.lister() if key)
        except Exception as exc:  # noqa: BLE001 — one unlistable source must not hide the rest
            log.info("credential names of %s not listed (%s)", module, type(exc).__name__)
    return frozenset(found)


def all_secret_keys() -> frozenset[str]:
    """Every credential name that can be known without the store listing itself."""
    return KNOWN_SECRET_KEYS | dynamic_secret_keys()


__all__ = [
    "DYNAMIC_SLOT_SOURCES",
    "KNOWN_SECRET_KEYS",
    "SlotSource",
    "all_secret_keys",
    "dynamic_secret_keys",
]

"""A stored MCP command keeps starting a bundled server under every package name.

The seed catalog, a user's catalog override and the browser evidence of a
plugin all carry the ``python -m <module>`` command a bundled server was
published with. These tests pin that every reader recognises such a command by
the published module name AND by the name the package is imported as today -
they are the same string until the package moves, and both must keep working
after it has.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from dodaios.core.branding import LEGACY_PACKAGE_NAMES
from dodaios.marketplace import bundled_servers
from dodaios.marketplace.bundled_servers import (
    AMD_SERVER_MODULES,
    CONNECTED_SERVER_MODULES,
    runs_amd_server,
    runs_bundled_server,
    runs_connected_server,
)
from dodaios.marketplace.catalog import PluginSpec
from dodaios.marketplace.catalog_data import load_seed_catalog
from dodaios.marketplace.mcp_bridge import _stdio_entry
from dodaios.marketplace.plugin_mcp import plugin_to_mcp_server_spec
from dodaios.marketplace.plugin_registry import _default_client_factory
from dodaios.marketplace.token_store import Tokens

# The names stored commands were published under. Written out on purpose: they
# are data on disk in existing installations, not references to this package.
PUBLISHED_CONNECTED = "jarvis.plugins.tool.connected_server"  # rename-keep
PUBLISHED_AMD = "jarvis.marketplace.amd_mcp"  # rename-keep

_PACKAGE = bundled_servers.__name__.partition(".")[0]


def _bundled_seed_plugins() -> list[PluginSpec]:
    return [
        plugin
        for plugin in load_seed_catalog().plugins
        if plugin.mcp_server
        and str(plugin.mcp_server.get("transport", "")).lower() == "stdio"
        and list(plugin.mcp_server.get("install") or [])[:2] == ["python", "-m"]
    ]


def test_published_names_stay_bundled_servers() -> None:
    assert PUBLISHED_CONNECTED.partition(".")[0] in LEGACY_PACKAGE_NAMES
    assert PUBLISHED_CONNECTED in CONNECTED_SERVER_MODULES
    assert PUBLISHED_AMD in AMD_SERVER_MODULES


def test_the_name_the_package_is_imported_as_is_a_bundled_server() -> None:
    assert f"{_PACKAGE}.plugins.tool.connected_server" in CONNECTED_SERVER_MODULES
    assert f"{_PACKAGE}.marketplace.amd_mcp" in AMD_SERVER_MODULES
    # Each accepted name is a real module, so a stored command still starts.
    for name in sorted(CONNECTED_SERVER_MODULES | AMD_SERVER_MODULES):
        assert importlib.import_module(name).__name__.startswith(_PACKAGE + ".")


@pytest.mark.parametrize(
    "command",
    [
        ["python", "-m", PUBLISHED_CONNECTED, "zoom"],
        [sys.executable, "-m", PUBLISHED_CONNECTED, "zoom"],
        ["python", "-m", f"{_PACKAGE}.plugins.tool.connected_server", "zoom"],
    ],
)
def test_connected_server_commands_are_recognised(command: list[str]) -> None:
    assert runs_connected_server(command)
    assert runs_bundled_server(command)
    assert not runs_amd_server(command)


def test_amd_server_command_is_recognised() -> None:
    assert runs_amd_server(["python", "-m", PUBLISHED_AMD])
    assert runs_bundled_server(["python", "-m", PUBLISHED_AMD])
    assert not runs_connected_server(["python", "-m", PUBLISHED_AMD])


@pytest.mark.parametrize(
    "command",
    [
        [],
        ["python"],
        ["python", "-m"],
        ["python", "-c", PUBLISHED_CONNECTED],
        ["python", "-m", "other.plugins.tool.connected_server"],
        ["python", "-m", PUBLISHED_CONNECTED + ".evil"],
        ["python", PUBLISHED_CONNECTED, "-m"],
        ["python", "-m", ["not", "a", "name"]],
        ["npx", "-y", "@scope/server"],
    ],
)
def test_other_commands_are_not_bundled_servers(command: list[object]) -> None:
    assert not runs_bundled_server(command)


def test_the_seed_catalog_names_only_recognised_bundled_servers() -> None:
    """The shipped catalog is the stored configuration every install starts from."""
    plugins = _bundled_seed_plugins()
    assert plugins, "the seed catalog ships bundled stdio servers"
    for plugin in plugins:
        assert runs_bundled_server(plugin.mcp_server["install"]), plugin.id


def test_every_reader_treats_a_seed_entry_as_bundled() -> None:
    """Worker bridge, in-process spec and client factory agree on the seed's commands."""
    tokens = Tokens(access="token-under-test")
    for plugin in _bundled_seed_plugins():
        install = plugin.mcp_server["install"]

        entry = _stdio_entry(plugin.mcp_server, {})
        assert entry is not None
        assert entry["command"] == sys.executable, plugin.id

        built = plugin_to_mcp_server_spec(plugin, tokens)
        assert built is not None
        spec, env = built
        assert spec.install_command[0] == sys.executable, plugin.id

        if runs_connected_server(install):
            assert env["JARVIS_CONNECTOR_AUTH_TYPE"] == "pat", plugin.id
            client = _default_client_factory(spec, env_overrides=env)
            assert type(client).__name__ == "BundledRestMcpClient", plugin.id

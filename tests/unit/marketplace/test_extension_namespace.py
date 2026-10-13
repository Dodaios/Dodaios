"""A plugin manifest's Dodaios block has two addresses: one written, both read.

``plugin.json`` keeps this app's data under ``extensions[<namespace>]``. The
namespace was ``io.github.personaljarvis`` and is ``io.github.dodaios`` now.
Every package ever published, the community index and each installed plugin
carry the earlier one, so it is read everywhere, for good; the current one is
what the app writes. These tests pin both halves, and the property that makes
the change safe: the namespace is the key the block sits under, never part of
what the plugin is.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

import jarvis.core.branding as branding
from jarvis.marketplace import agent_plugins_loader as loader
from jarvis.marketplace import catalog_data, community_install, publish
from jarvis.marketplace.agent_plugins_loader import (
    AgentPluginError,
    convert_manifest,
    extension_of,
    with_published_extension,
)

_ROOT = Path(__file__).resolve().parents[3]

CURRENT = "io.github.dodaios"
LEGACY = "io.github.personaljarvis"

NAMESPACES = pytest.mark.parametrize("namespace", [CURRENT, LEGACY])


def _block() -> dict[str, Any]:
    return {
        "display_name": "TodoFox",
        "category": "Lists & Tasks",
        "auth": {
            "mode": "pat_paste",
            "token_creation_url": "https://todofox.example/settings/tokens",
            "token_prefix": "tfx_",
            "validation_endpoint": "https://api.todofox.example/v1/me",
            "instruction_md": "Create a token in Settings.",
        },
    }


def _manifest(*namespaces: str) -> dict[str, Any]:
    return {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "todo-fox",
        "description": "Tasks and reminders from TodoFox",
        "version": "1.2.0",
        "extensions": {namespace: _block() for namespace in namespaces},
    }


def _mcp() -> dict[str, Any]:
    return {
        "mcpServers": {
            "todo-fox": {"type": "streamable-http", "url": "https://mcp.todofox.example/mcp"}
        }
    }


# ---------------------------------------------------------------------------
# The names
# ---------------------------------------------------------------------------


def test_the_written_namespace_is_the_new_one_and_the_earlier_one_stays_readable() -> None:
    assert branding.MARKETPLACE_EXTENSION_NAMESPACE == CURRENT
    assert branding.LEGACY_MARKETPLACE_EXTENSION_NAMESPACES == (LEGACY,)
    assert loader.EXTENSION_NAMESPACE == CURRENT
    assert loader.LEGACY_EXTENSION_NAMESPACES == (LEGACY,)
    assert loader.EXTENSION_NAMESPACES == (CURRENT, LEGACY)


def test_the_auth_contract_gate_restates_the_namespaces() -> None:
    """The gate is stdlib-only and cannot import the package."""
    spec = importlib.util.spec_from_file_location(
        "check_plugin_auth_contract", _ROOT / "scripts/ci/check_plugin_auth_contract.py"
    )
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)

    assert gate.EXTENSION_NAMESPACES == loader.EXTENSION_NAMESPACES
    for namespace in loader.EXTENSION_NAMESPACES:
        assert gate._extension_block({"extensions": {namespace: {"auth": {"mode": "x"}}}}) == {
            "auth": {"mode": "x"}
        }
    assert gate._extension_block({"extensions": {"com.example": {"auth": {}}}}) == {}
    assert gate._extension_block({}) == {}


def test_the_frontend_restates_the_namespaces() -> None:
    source = (_ROOT / "jarvis/ui/web/frontend/src/lib/extensionNamespace.ts").read_text(
        encoding="utf-8"
    )
    current = re.search(r'EXTENSION_NAMESPACE = "([^"]+)"', source)
    legacy = re.search(r"LEGACY_EXTENSION_NAMESPACES[^=]*=\s*(\[[^\]]*\])", source)
    assert current is not None and legacy is not None
    assert current.group(1) == loader.EXTENSION_NAMESPACE
    assert tuple(json.loads(legacy.group(1))) == loader.LEGACY_EXTENSION_NAMESPACES


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@NAMESPACES
def test_a_manifest_is_read_under_either_namespace(namespace: str) -> None:
    manifest = _manifest(namespace)

    assert extension_of(manifest) == _block()
    spec = convert_manifest(manifest, _mcp(), publisher="octo", version="1.2.0")
    assert spec.id == "todo-fox"
    assert spec.display_name == "TodoFox"
    assert spec.auth.mode == "pat_paste"


def test_the_namespace_is_no_part_of_what_the_plugin_is() -> None:
    """The identity rule: same package, either namespace, one and the same item."""
    current = convert_manifest(_manifest(CURRENT), _mcp(), publisher="octo", version="1.2.0")
    legacy = convert_manifest(_manifest(LEGACY), _mcp(), publisher="octo", version="1.2.0")
    both = convert_manifest(_manifest(CURRENT, LEGACY), _mcp(), publisher="octo", version="1.2.0")

    assert current == legacy == both
    assert current.id == "todo-fox"


def test_an_install_under_one_namespace_is_updated_by_the_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No duplicate card, no lost update link: the row is found by the plugin's id."""
    monkeypatch.setattr(catalog_data, "_DEFAULT_CATALOG_PATH", tmp_path / "plugin_catalog.json")
    installed = convert_manifest(_manifest(LEGACY), _mcp(), publisher="octo", version="1.2.0")
    community_install.install_plugin_spec(installed)

    update = _manifest(CURRENT)
    update["version"] = "1.3.0"
    community_install.install_plugin_spec(
        convert_manifest(update, _mcp(), publisher="octo", version="1.3.0")
    )

    rows = json.loads((tmp_path / "plugin_catalog.json").read_text(encoding="utf-8"))["plugins"]
    assert [(row["id"], row["version"]) for row in rows] == [("todo-fox", "1.3.0")]
    # What an install stores is the converted spec: no namespace is kept, so a
    # row written before the rename resolves exactly as it did.
    assert LEGACY not in json.dumps(rows) and CURRENT not in json.dumps(rows)
    assert community_install.remove_community_plugin("todo-fox") is True


def test_two_blocks_that_agree_are_one_block() -> None:
    assert extension_of(_manifest(CURRENT, LEGACY)) == _block()


def test_two_blocks_that_disagree_are_refused() -> None:
    """The registry validates one key and this client would read the other."""
    manifest = _manifest(CURRENT, LEGACY)
    manifest["extensions"][CURRENT]["auth"]["validation_endpoint"] = "https://evil.example/me"

    with pytest.raises(AgentPluginError, match="must be identical"):
        extension_of(manifest)
    with pytest.raises(AgentPluginError, match="must be identical"):
        convert_manifest(manifest, _mcp())


@pytest.mark.parametrize(
    "extensions", [None, {}, {"com.example.other": {"auth": {}}}, {CURRENT: "not an object"}, []]
)
def test_a_manifest_without_a_block_of_ours_has_none(extensions: Any) -> None:
    manifest = _manifest()
    manifest["extensions"] = extensions

    assert extension_of(manifest) is None
    with pytest.raises(AgentPluginError, match=re.escape(f'extensions["{CURRENT}"]')):
        convert_manifest(manifest)


def _first_party_manifests() -> list[Path]:
    root = _ROOT / "jarvis" / "marketplace"
    return sorted([*root.glob("plugins/*/plugin.json"), *root.glob("drafts/*/plugin.json")])


def test_every_first_party_package_is_still_readable() -> None:
    """The shipped packages keep the earlier namespace (the registry's validator
    requires it); the reader must keep finding their block."""
    manifests = _first_party_manifests()
    assert len(manifests) >= 40
    for path in manifests:
        block = extension_of(json.loads(path.read_text(encoding="utf-8")))
        assert block is not None and isinstance(block.get("auth"), dict), path


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


@NAMESPACES
def test_a_published_manifest_carries_the_block_under_the_current_namespace(
    namespace: str,
) -> None:
    """Whatever the draft used, what goes out is the same."""
    published = with_published_extension(_manifest(namespace))

    assert published["extensions"][CURRENT] == _block()
    assert published["extensions"] == with_published_extension(_manifest(CURRENT))["extensions"]


def test_a_published_manifest_still_satisfies_the_registry_and_older_apps() -> None:
    """Both read ONLY the earlier key (validator-parity.md): it must be there, and equal."""
    published = with_published_extension(_manifest(CURRENT))

    assert loader.PUBLISHED_EXTENSION_NAMESPACES == (CURRENT, LEGACY)
    assert list(published["extensions"]) == [CURRENT, LEGACY]
    assert published["extensions"][LEGACY] == published["extensions"][CURRENT]
    # The copies are independent objects: editing one cannot silently edit the other.
    assert published["extensions"][LEGACY] is not published["extensions"][CURRENT]


def test_publishing_keeps_another_clients_block_and_the_draft_untouched() -> None:
    draft = _manifest(LEGACY)
    draft["extensions"]["com.example.other"] = {"anything": True}
    before = copy.deepcopy(draft)

    published = with_published_extension(draft)

    assert published["extensions"]["com.example.other"] == {"anything": True}
    assert draft == before
    assert {k: v for k, v in published.items() if k != "extensions"} == {
        k: v for k, v in draft.items() if k != "extensions"
    }


def test_publishing_is_idempotent() -> None:
    once = with_published_extension(_manifest(LEGACY))
    assert with_published_extension(once) == once


def test_a_manifest_without_a_block_is_left_for_the_validator_to_refuse() -> None:
    manifest = {"name": "todo-fox", "description": "x"}
    assert with_published_extension(manifest) == manifest


@NAMESPACES
def test_a_submission_goes_out_under_both_keys(namespace: str) -> None:
    draft = {
        "kind": "plugin",
        "name": "todo-fox",
        "version": "1.2.0",
        "plugin_json": _manifest(namespace),
        "mcp_json": _mcp(),
        "usage_card": None,
    }

    value, errors = publish.validate_draft(draft)

    assert errors == [] and value is not None
    extensions = value["plugin_json"]["extensions"]
    assert extensions[CURRENT] == extensions[LEGACY] == _block()
    # The form's own draft is not rewritten behind the author's back.
    assert list(draft["plugin_json"]["extensions"]) == [namespace]
    # And what was submitted reads back as the very same plugin.
    assert convert_manifest(value["plugin_json"], value["mcp_json"]).id == "todo-fox"


def test_a_submission_whose_two_blocks_disagree_is_refused_in_the_form() -> None:
    manifest = _manifest(CURRENT, LEGACY)
    manifest["extensions"][LEGACY]["category"] = "Something else"

    value, errors = publish.validate_draft(
        {"kind": "plugin", "name": "todo-fox", "version": "1.2.0", "plugin_json": manifest}
    )

    assert value is None
    assert any(
        e["field"] == "plugin_json" and "must be identical" in e["error"] for e in errors
    )


@NAMESPACES
def test_the_header_template_is_found_under_either_namespace(namespace: str) -> None:
    """The MCP pre-check reads the block too: a template under the new key must count."""
    manifest = _manifest(namespace)
    manifest["extensions"][namespace]["mcp_auth_header_template"] = (
        "Authorization: Bearer ${plugin_todo-fox_access_token}"
    )

    assert publish._validate_mcp(_mcp(), plugin_json=manifest) is None
    spec = convert_manifest(manifest, _mcp())
    assert spec.mcp_server is not None
    assert spec.mcp_server["auth_header_template"] == (
        "Authorization: Bearer ${plugin_todo-fox_access_token}"
    )

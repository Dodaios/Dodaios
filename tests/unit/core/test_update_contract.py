"""``jarvis.core.update_contract`` — where a release tells its updater to look.

Two things are pinned here. The tracked ``install/update-contract.json`` must
describe THIS tree truthfully, because the version before a release believes
it. And the reader must fall back to the default locations for anything it
cannot trust, because those locations are what an update is checked against.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

import jarvis
from jarvis.core.branding import CONFIG_FILE_NAME, MACOS_APP_DIR_NAME
from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS
from jarvis.core.update_contract import (
    CONTRACT_PATH,
    CONTRACT_SCHEMA,
    DEFAULT_CONTRACT,
    VERSION_PATTERN,
    UpdateContract,
    parse_update_contract,
    read_update_contract,
)

REPO = Path(__file__).resolve().parents[3]


def _document(**overrides: object) -> str:
    return json.dumps({"schema": CONTRACT_SCHEMA, **overrides})


# --------------------------------------------------------------------------- #
# The tracked contract describes this tree
# --------------------------------------------------------------------------- #
def test_the_tracked_contract_is_the_default_contract() -> None:
    """A release without the file must behave exactly like this one."""
    payload = json.loads((REPO / CONTRACT_PATH).read_text(encoding="utf-8"))
    assert payload.pop("schema") == CONTRACT_SCHEMA
    stated = {key: value for key, value in asdict(DEFAULT_CONTRACT).items() if value is not None}
    assert payload == stated
    assert read_update_contract(REPO) == DEFAULT_CONTRACT


def test_the_contract_points_at_files_this_tree_really_has() -> None:
    contract = read_update_contract(REPO)

    assert (REPO / contract.ui_bundle_dir / "index.html").is_file()
    assert (REPO / (contract.launcher_module.replace(".", "/") + ".py")).is_file()

    version_text = (REPO / contract.version_file).read_text(encoding="utf-8")
    match = re.search(VERSION_PATTERN, version_text)
    assert match is not None
    assert match.group(1) == jarvis.__version__


def test_the_contract_agrees_with_every_other_copy_of_these_names() -> None:
    from jarvis.autostart.command import LAUNCHER_MODULE as autostart_launcher
    from jarvis.ui import relauncher

    assert DEFAULT_CONTRACT.config_file == CONFIG_FILE_NAME
    assert DEFAULT_CONTRACT.macos_app_dir_name == MACOS_APP_DIR_NAME
    assert DEFAULT_CONTRACT.launcher_module == autostart_launcher
    assert relauncher.LAUNCHER_MODULE == DEFAULT_CONTRACT.launcher_module
    assert DEFAULT_CONTRACT.rollback_hook is None


def test_the_reader_is_standard_library_only() -> None:
    """The restart helper loads it; it must not drag the runtime in."""
    probe = (
        "import sys\n"
        "import jarvis.core.update_contract\n"
        "print('\\n'.join(sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'pydantic', 'fastapi', 'httpx', 'loguru'})))\n"
    )
    proc = subprocess.run(  # noqa: S603 - fixed argv, this interpreter
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(REPO),
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def test_a_tree_without_the_file_gets_the_default_locations(tmp_path: Path) -> None:
    assert read_update_contract(tmp_path) == DEFAULT_CONTRACT


def test_a_moved_tree_is_read_as_it_describes_itself(tmp_path: Path) -> None:
    (tmp_path / "install").mkdir()
    (tmp_path / CONTRACT_PATH).write_text(
        _document(
            ui_bundle_dir="newpkg/ui/web/dist",
            launcher_module="newpkg.ui.web.launcher",
            version_file="newpkg/__init__.py",
            config_file="newpkg.toml",
            macos_app_dir_name="New Product.app",
            rollback_hook="install/rollback.py",
        ),
        encoding="utf-8",
    )
    assert read_update_contract(tmp_path) == UpdateContract(
        ui_bundle_dir="newpkg/ui/web/dist",
        launcher_module="newpkg.ui.web.launcher",
        version_file="newpkg/__init__.py",
        config_file="newpkg.toml",
        macos_app_dir_name="New Product.app",
        rollback_hook="install/rollback.py",
    )


def test_a_key_the_document_leaves_out_keeps_its_default() -> None:
    contract = parse_update_contract(_document(launcher_module="newpkg.launcher"))
    assert contract.launcher_module == "newpkg.launcher"
    assert contract.ui_bundle_dir == DEFAULT_CONTRACT.ui_bundle_dir
    assert contract.config_file == DEFAULT_CONTRACT.config_file


def test_an_unknown_key_is_ignored() -> None:
    contract = parse_update_contract(_document(config_file="x.toml", data_dir="somewhere"))
    assert contract.config_file == "x.toml"


def test_an_explicit_null_hook_means_no_hook() -> None:
    assert parse_update_contract(_document(rollback_hook=None)).rollback_hook is None


def test_a_byte_order_mark_does_not_hide_the_contract(tmp_path: Path) -> None:
    (tmp_path / "install").mkdir()
    (tmp_path / CONTRACT_PATH).write_bytes(
        b"\xef\xbb\xbf" + _document(config_file="x.toml").encode("utf-8")
    )
    assert read_update_contract(tmp_path).config_file == "x.toml"


# --------------------------------------------------------------------------- #
# Refusing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '"jarvis/ui/web/dist"',
        json.dumps({"ui_bundle_dir": "newpkg/dist"}),  # no schema at all
        json.dumps({"schema": 2, "ui_bundle_dir": "newpkg/dist"}),
        json.dumps({"schema": "1", "ui_bundle_dir": "newpkg/dist"}),
        json.dumps({"schema": True, "ui_bundle_dir": "newpkg/dist"}),
        json.dumps({"schema": 1.0, "ui_bundle_dir": "newpkg/dist"}),
    ],
)
def test_an_unreadable_or_unknown_document_is_the_default_contract(text: str) -> None:
    assert parse_update_contract(text) == DEFAULT_CONTRACT


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",
        "../outside/dist",
        "pkg/../../outside",
        "pkg/./dist",
        "./pkg/dist",
        "pkg//dist",
        "pkg/dist/",
        "C:/Windows/System32",
        "C:\\Windows\\System32",
        "pkg\\ui\\dist",
        "pkg/ui dist",
        "~/dist",
        "$HOME/dist",
        "pkg/dist\n",
        "",
        "x" * 300,
        42,
        None,
        ["pkg", "dist"],
    ],
)
@pytest.mark.parametrize("field", ["ui_bundle_dir", "version_file"])
def test_a_path_that_could_leave_the_checkout_rejects_the_document(
    field: str, bad_path: object
) -> None:
    text = _document(**{field: bad_path, "launcher_module": "newpkg.launcher"})
    # The valid launcher is dropped too: a document is believed whole or not at all.
    assert parse_update_contract(text) == DEFAULT_CONTRACT


@pytest.mark.parametrize(
    "bad_module",
    [
        "newpkg.launcher; import os",
        "newpkg launcher",
        "newpkg..launcher",
        ".newpkg.launcher",
        "newpkg.launcher.",
        "1newpkg.launcher",
        "newpkg/launcher",
        "-c",
        "newpkg.launcher\n",
        "",
        7,
        None,
    ],
)
def test_a_launcher_that_is_not_a_module_name_rejects_the_document(
    bad_module: object,
) -> None:
    assert parse_update_contract(_document(launcher_module=bad_module)) == DEFAULT_CONTRACT


@pytest.mark.parametrize(
    "bad_name", ["sub/dir.toml", "..", ".", "a\\b.toml", "", "name with space.toml", 3, None]
)
def test_a_config_name_that_is_not_a_plain_file_name_rejects_the_document(
    bad_name: object,
) -> None:
    assert parse_update_contract(_document(config_file=bad_name)) == DEFAULT_CONTRACT


@pytest.mark.parametrize(
    "bad_name", ["Product", "../Evil.app", "sub/Product.app", ".app", " Product.app", "", 5, None]
)
def test_an_app_name_that_is_not_one_bundle_directory_rejects_the_document(
    bad_name: object,
) -> None:
    assert parse_update_contract(_document(macos_app_dir_name=bad_name)) == DEFAULT_CONTRACT


@pytest.mark.parametrize(
    "bad_hook",
    ["../rollback.py", "/opt/rollback.py", "install/rollback.sh", "install/rollback", "", 1, []],
)
def test_a_hook_that_is_not_a_script_inside_the_tree_rejects_the_document(
    bad_hook: object,
) -> None:
    assert parse_update_contract(_document(rollback_hook=bad_hook)) == DEFAULT_CONTRACT


def test_an_oversized_file_is_not_a_contract(tmp_path: Path) -> None:
    (tmp_path / "install").mkdir()
    padded = json.dumps(
        {"schema": CONTRACT_SCHEMA, "config_file": "x.toml", "padding": "p" * 20_000}
    )
    (tmp_path / CONTRACT_PATH).write_text(padded, encoding="utf-8")
    assert read_update_contract(tmp_path) == DEFAULT_CONTRACT


def test_a_file_that_is_not_utf8_is_not_a_contract(tmp_path: Path) -> None:
    (tmp_path / "install").mkdir()
    (tmp_path / CONTRACT_PATH).write_bytes(b'{"schema": 1, "config_file": "\xff\xfe.toml"}')
    assert read_update_contract(tmp_path) == DEFAULT_CONTRACT

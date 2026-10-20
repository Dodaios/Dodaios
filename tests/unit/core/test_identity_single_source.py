"""Every identity name comes from ``dodaios.core.branding``, or is pinned to it here.

Most code imports the constants. A few places cannot: a plugin held to the
no-``dodaios.*`` import rule, the PyInstaller spec and runtime hook, the shell
and packaging scripts, ``pyproject.toml``, the frontend. Each of those restates
a value, and each restated value is pinned below, so changing one name in
``branding.py`` either reaches every copy or fails this file by name.

The last section checks the names against each other: two names that land in
one case-insensitive namespace (two executables in one folder, two folders in
the home directory) must differ in more than letter case, across the current
names and every ``LEGACY_*`` name an older installation still carries.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

import dodaios.core.branding as branding
from dodaios.core import config as core_config
from dodaios.core import identity_boot
from dodaios.core.instance import (
    DATA_DIR_ENV_VAR,
    DEV_INSTANCE_NAME,
    INSTANCE_ENV_VAR,
    resolve_data_dir,
)
from dodaios.core.paths import user_data_dir
from dodaios.ui.desktop_log import DESKTOP_LOG_FILE_NAME, desktop_log_path

_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (_ROOT / relative_path).read_text(encoding="utf-8")


def _module_constant(relative_path: str, name: str) -> object:
    """The literal a module assigns to ``name`` at top level, read without importing it."""
    tree = ast.parse(_read(relative_path))
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return ast.literal_eval(node.value)  # type: ignore[arg-type]
    raise AssertionError(f"{relative_path} assigns no top-level {name}")


# ---------------------------------------------------------------------------
# Python that may not import the package
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_path",
    ["dodaios/plugins/stt/deepgram_api.py", "dodaios/plugins/stt/groq_api.py"],
)
def test_a_plugin_reads_keys_from_the_hosts_keyring_services(relative_path: str) -> None:
    assert _module_constant(relative_path, "_KEYRING_SERVICE") == branding.KEYRING_SERVICE_NAME
    assert (
        _module_constant(relative_path, "_LEGACY_KEYRING_SERVICES")
        == branding.LEGACY_KEYRING_SERVICE_NAMES
    )
    # The named constants are the only spellings: no second literal beside them.
    source = _read(relative_path)
    for service in (branding.KEYRING_SERVICE_NAME, *branding.LEGACY_KEYRING_SERVICE_NAMES):
        assert source.count(f'"{service}"') == 1, service


@pytest.mark.parametrize(
    "relative_path",
    [
        "dodaios/plugins/brain/openrouter.py",
        "dodaios/plugins/stt/openrouter_stt.py",
        "dodaios/plugins/tts/openrouter_tts.py",
    ],
)
def test_a_plugin_attributes_requests_to_the_official_repository(relative_path: str) -> None:
    repository = f"https://github.com/{branding.DEFAULT_OFFICIAL_REPO_SLUG}"
    assert f'"HTTP-Referer": "{repository}"' in _read(relative_path)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("_WINDOWS_USER_DATA_DIR_NAME", branding.WINDOWS_USER_DATA_DIR_NAME),
        ("_LEGACY_WINDOWS_USER_DATA_DIR_NAMES", branding.LEGACY_WINDOWS_USER_DATA_DIR_NAMES),
        ("_FALLBACK_USER_DATA_DIR_NAME", branding.FALLBACK_USER_DATA_DIR_NAME),
        ("_LEGACY_FALLBACK_USER_DATA_DIR_NAMES", branding.LEGACY_FALLBACK_USER_DATA_DIR_NAMES),
        ("_CONFIG_FILE_NAME", branding.CONFIG_FILE_NAME),
        ("_LEGACY_CONFIG_FILE_NAMES", branding.LEGACY_CONFIG_FILE_NAMES),
        ("_MUTEX_NAMES", identity_boot.primary_mutex_names()),
        ("_REPORT_ENV_VAR", identity_boot.HOOK_REPORT_ENV_VAR),
    ],
)
def test_the_frozen_runtime_hook_restates_the_directory_names(name: str, expected: object) -> None:
    assert _module_constant("packaging/pyinstaller_rthook_frozen.py", name) == expected


def test_the_frozen_runtime_hook_restates_the_lock_files_and_launcher_names() -> None:
    hook_path = "packaging/pyinstaller_rthook_frozen.py"
    assert _load_runtime_hook()._PRIMARY_LOCK_FILES == identity_boot.PRIMARY_LOCK_FILES
    # Every executable that is the desktop app may migrate, under its current
    # and its earlier names; nothing else.
    windows_names = (
        branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME,
        *branding.LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES,
    )
    gui_names = {
        branding.MACOS_EXECUTABLE_NAME,
        *branding.LEGACY_MACOS_EXECUTABLE_NAMES,
        *(name.removesuffix(".exe") for name in windows_names),
        _module_constant("dodaios.spec", "GUI_EXE_NAME"),
        *_module_constant("dodaios.spec", "LEGACY_GUI_EXE_NAMES"),
    }
    assert set(_module_constant(hook_path, "_GUI_EXE_NAMES")) == gui_names
    # The bundle seeds a first-run config from the file dodaios.spec ships.
    bundled = _module_constant(hook_path, "_BUNDLED_CONFIG_FILE_NAME")
    assert f'datas.append((str(PROJECT_ROOT / "{bundled}"), "."))' in _read("dodaios.spec")
    # And the engine it loads by path is shipped as a plain file.
    engine = "/".join(_module_constant(hook_path, "_ENGINE_PATH"))
    assert f'(str(PROJECT_ROOT / "{engine}"), "dodaios/core")' in _read("dodaios.spec")
    assert (_ROOT / engine).is_file()


def test_the_pyinstaller_spec_restates_the_bundle_names() -> None:
    assert _module_constant("dodaios.spec", "GUI_EXE_NAME") == branding.MACOS_EXECUTABLE_NAME
    assert (
        f'{_module_constant("dodaios.spec", "GUI_EXE_NAME")}.exe'
        == branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME
    )
    # The windowed launcher ships under its earlier name too: pins, logon tasks
    # and shortcuts of earlier releases start that file.
    legacy_gui = _module_constant("dodaios.spec", "LEGACY_GUI_EXE_NAMES")
    assert legacy_gui == branding.LEGACY_MACOS_EXECUTABLE_NAMES
    assert tuple(f"{name}.exe" for name in legacy_gui) == (
        branding.LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES
    )
    assert "*legacy_gui_exes," in _read("dodaios.spec")
    assert _module_constant("dodaios.spec", "CLI_EXE_NAME") == branding.CLI_COMMAND_NAME
    # The frozen build keeps the command's first earlier name beside the new one.
    legacy_exes = _module_constant("dodaios.spec", "LEGACY_CLI_EXE_NAMES")
    assert legacy_exes == branding.LEGACY_CLI_COMMAND_NAMES[:1]
    assert "*legacy_cli_exes," in _read("dodaios.spec")
    assert _module_constant("dodaios.spec", "MACOS_APP_NAME") == branding.MACOS_APP_DIR_NAME
    assert (
        _module_constant("dodaios.spec", "MACOS_BUNDLE_IDENTIFIER") == branding.MACOS_DMG_BUNDLE_ID
    )
    spec = _read("dodaios.spec")
    assert f'"CFBundleName": "{branding.MACOS_APP_NAME}"' in spec
    assert f'"CFBundleDisplayName": "{branding.MACOS_APP_NAME}"' in spec


# The exact-value guard: a literal equal to one of these anywhere in shipped
# Python is a second definition. Each allowed file says why it has one.
_RESTATEMENTS_ALLOWED = {
    "dodaios/core/branding.py": "the single source",
    "dodaios/plugins/stt/deepgram_api.py": "plugin without dodaios.* imports, pinned above",
    "dodaios/plugins/stt/groq_api.py": "plugin without dodaios.* imports, pinned above",
    "packaging/pyinstaller_rthook_frozen.py": "runtime hook, no dodaios.* imports, pinned above",
    "dodaios/agent_runtimes/acp.py": "ACP client name, an identifier of its own",
    "dodaios/agentic_ide/github_link.py": "HTTP user agent, an identifier of its own",
    "dodaios/brain/identity.py": "the former product name told to a model",
    "dodaios/codex_app_server.py": "client title sent to the Codex app server",
}


def _distinctive_identity_values() -> dict[str, str]:
    """Branding values specific enough that an equal literal elsewhere is a copy."""
    found: dict[str, str] = {}
    for name in sorted(vars(branding)):
        if not name.isupper():
            continue
        value = getattr(branding, name)
        for item in value if isinstance(value, tuple) else (value,):
            if not isinstance(item, str):
                continue
            folded = item.casefold().replace("-", "").replace(" ", "")
            if "personaljarvis" in folded and "/" not in item:
                found.setdefault(item, name)
    return found


def _shipped_python_files() -> list[Path]:
    roots = [_ROOT / "dodaios", _ROOT / "ui", _ROOT / "install", _ROOT / "packaging"]
    files = [path for root in roots for path in root.rglob("*.py")]
    return [path for path in files if "node_modules" not in path.parts]


def test_no_module_restates_an_identity_value() -> None:
    values = _distinctive_identity_values()
    assert branding.LEGACY_KEYRING_SERVICE_NAMES[0] in values
    assert branding.MACOS_BUNDLE_ID in values
    # The current credential service is the bare product word, which is also
    # the package, the command and the MCP server name: a literal equal to it
    # is no evidence of a copy. Store calls are checked for it by the next test.
    assert branding.KEYRING_SERVICE_NAME not in values
    offenders: list[str] = []
    for path in _shipped_python_files():
        relative = path.relative_to(_ROOT).as_posix()
        if relative in _RESTATEMENTS_ALLOWED:
            continue
        source = path.read_text(encoding="utf-8-sig")
        if "ersonal" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and node.value in values:
                offenders.append(
                    f"{relative}:{node.lineno}: {node.value!r} restates "
                    f"branding.{values[node.value]}"
                )
    assert not offenders, "import the constant from dodaios.core.branding:\n" + "\n".join(offenders)


_STORE_CALLS = frozenset({"get_password", "set_password", "delete_password", "peek_password"})


def _store_calls_naming_a_service(source: str, services: frozenset[str]) -> list[int]:
    """Lines where a credential-store call spells one of ``services`` as a literal."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        callee = node.func.attr if isinstance(node.func, ast.Attribute) else None
        first = node.args[0]
        if callee in _STORE_CALLS and isinstance(first, ast.Constant) and first.value in services:
            lines.append(node.lineno)
    return lines


def test_no_credential_store_call_spells_a_service_name() -> None:
    services = frozenset({branding.KEYRING_SERVICE_NAME, *branding.LEGACY_KEYRING_SERVICE_NAMES})
    offenders: list[str] = []
    for path in _shipped_python_files():
        relative = path.relative_to(_ROOT).as_posix()
        if relative in _RESTATEMENTS_ALLOWED:
            continue
        source = path.read_text(encoding="utf-8-sig")
        offenders += [
            f"{relative}:{line}" for line in _store_calls_naming_a_service(source, services)
        ]
    assert not offenders, "use dodaios.core.config.KEYRING_SERVICE: " + ", ".join(offenders)
    # And the check has teeth.
    probe = f'keyring.get_password("{branding.KEYRING_SERVICE_NAME}", "slot")'
    assert _store_calls_naming_a_service(probe, services) == [1]


# ---------------------------------------------------------------------------
# Scripts, packaging and project metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relative_path", "current", "legacy"),
    [
        ("install/install.sh", 'DEFAULT_INSTALL_DIR_NAME="{}"', 'LEGACY_INSTALL_DIR_NAME="{}"'),
        ("install/uninstall.sh", 'DEFAULT_INSTALL_DIR_NAME="{}"', 'LEGACY_INSTALL_DIR_NAME="{}"'),
        ("install/install.ps1", "$DefaultInstallDirName = '{}'", "$LegacyInstallDirName = '{}'"),
        ("install/uninstall.ps1", "$DefaultInstallDirName = '{}'", "$LegacyInstallDirName = '{}'"),
    ],
)
def test_the_scripts_restate_the_install_directory_names(
    relative_path: str, current: str, legacy: str
) -> None:
    # Each script names the current folder and the one earlier name it still
    # recognises; there is one earlier name, so one variable carries it.
    assert branding.LEGACY_DEFAULT_INSTALL_DIR_NAMES == (".personal-jarvis",)
    lines = _read(relative_path).splitlines()
    assert current.format(branding.DEFAULT_INSTALL_DIR_NAME) in lines
    assert legacy.format(branding.LEGACY_DEFAULT_INSTALL_DIR_NAMES[0]) in lines


def test_the_installers_read_the_migration_engine_from_where_it_lives() -> None:
    engine = "dodaios/core/identity_migration.py"
    assert (_ROOT / engine).is_file()
    assert f'IDENTITY_ENGINE_PATH="{engine}"' in _read("install/install.sh").splitlines()
    assert f"$IdentityEnginePath = '{engine}'" in _read("install/install.ps1").splitlines()


@pytest.mark.parametrize(
    ("variable", "expected"),
    [
        ("MACOS_BUNDLE_ID", branding.MACOS_BUNDLE_ID),
        ("MACOS_AUTOSTART_LABEL", branding.MACOS_AUTOSTART_LABEL),
    ],
)
def test_the_shell_uninstaller_restates_the_macos_identifiers(
    variable: str, expected: str
) -> None:
    assert f'\n{variable}="{expected}"\n' in _read("install/uninstall.sh")


def test_the_shell_uninstaller_restates_both_bundle_names() -> None:
    script = _read("install/uninstall.sh")
    assert f'\nMACOS_APP_DIR_NAME="{branding.MACOS_APP_DIR_NAME}"\n' in script
    assert branding.LEGACY_MACOS_APP_DIR_NAMES == ("Personal Jarvis.app",)
    legacy = branding.LEGACY_MACOS_APP_DIR_NAMES[0]
    assert f'\nLEGACY_MACOS_APP_DIR_NAME="{legacy}"\n' in script
    assert 'for app_dir_name in "$MACOS_APP_DIR_NAME" "$LEGACY_MACOS_APP_DIR_NAME"; do' in script


def test_the_shell_uninstaller_names_every_credential_service() -> None:
    script = _read("install/uninstall.sh")
    assert f'\nKEYRING_SERVICE_NAME="{branding.KEYRING_SERVICE_NAME}"\n' in script
    legacy = " ".join(branding.LEGACY_KEYRING_SERVICE_NAMES)
    assert f'\nLEGACY_KEYRING_SERVICE_NAMES="{legacy}"\n' in script


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        ("AppName", branding.LAUNCHER_ENTRY_NAME),
        ("GuiExeName", branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME),
        ("CliExeName", f"{branding.CLI_COMMAND_NAME}.exe"),
        ("LegacyCliExeName", f"{branding.LEGACY_CLI_COMMAND_NAMES[0]}.exe"),
        ("UserDataDirDisplay", rf"%LOCALAPPDATA%\{branding.WINDOWS_USER_DATA_DIR_NAME}"),
        ("AppPublisher", branding.LAUNCHER_ENTRY_NAME),
        ("LegacyAppName", branding.LEGACY_LAUNCHER_ENTRY_NAMES[0]),
        ("LegacyGuiExeName", branding.LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES[0]),
    ],
)
def test_the_windows_installer_script_restates_the_names(definition: str, expected: str) -> None:
    assert f'\n#define {definition} "{expected}"\n' in _read(
        "packaging/windows/Dodaios.iss"
    )


def test_the_windows_installer_retires_the_earlier_shortcuts_and_keeps_its_identity() -> None:
    script = _read("packaging/windows/Dodaios.iss")
    # Windows upgrades by AppId: a new one would install a second product.
    assert '#define AppGuid "7F1C4E42-2E5B-4F0A-9E1B-1A7B6C0D5E88"' in script
    # The shortcuts an earlier release created under the earlier name go; the
    # Desktop one only where it starts this installation.
    install_delete = script.split("\n[InstallDelete]\n", 1)[1].split("\n[", 1)[0]
    assert r'"{autoprograms}\{#LegacyAppName}\{#LegacyAppName}.lnk"' in install_delete
    assert "Check: LegacyShortcutStartsThisApp(" in install_delete
    assert "UsePreviousGroup=no" in script
    # The setup's product name is what the SignPath artifact configuration
    # checks (docs/code-signing-policy.md): it stays until that pin moves.
    assert "VersionInfoProductName={#SignedProductName}" in script
    policy = _read("docs/code-signing-policy.md")
    signed = re.search(r'#define SignedProductName "([^"]+)"', script)
    assert signed is not None and f'product-name="{signed.group(1)}"' in policy


def test_the_packaging_scripts_restate_the_names() -> None:
    windows = _read("packaging/windows/build.ps1")
    frozen_cli_names = (branding.CLI_COMMAND_NAME, branding.LEGACY_CLI_COMMAND_NAMES[0])
    required = (
        branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME,
        *branding.LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES,
        *(f"{name}.exe" for name in frozen_cli_names),
    )
    assert "@(" + ", ".join(f'"{name}"' for name in required) + ")" in windows
    quoted = " ".join(f'"{name}"' for name in frozen_cli_names)
    assert f"\nCLI_EXE_NAMES=({quoted})\n" in _read("packaging/linux/build.sh")
    # The AppImage links its launcher to the windowed executable, current name first.
    gui = (branding.MACOS_EXECUTABLE_NAME, *branding.LEGACY_MACOS_EXECUTABLE_NAMES)
    quoted_gui = " ".join(f'"{name}"' for name in gui)
    assert f'\nGUI_EXE_CANDIDATES=({quoted_gui} "Jarvis")\n' in _read("packaging/linux/build.sh")
    assert f"for cli_name in {' '.join(frozen_cli_names)}; do" in _read(
        "packaging/macos/build.sh"
    )
    linux = _read("packaging/linux/build.sh")
    assert f'\nDESKTOP_FILE_NAME="{branding.LINUX_DESKTOP_ENTRY_FILE_NAME}"\n' in linux
    # The installed icon carries the window class's name, like the entry.
    assert f'\nICON_FILE_NAME="{branding.LINUX_WM_CLASS}.png"\n' in linux
    assert f'\nAPP_NAME="{branding.MACOS_APP_NAME}"\n' in _read("packaging/macos/build.sh")


def test_the_project_metadata_restates_the_distribution_and_its_commands() -> None:
    project = tomllib.loads(_read("pyproject.toml"))
    assert project["project"]["name"] == branding.DISTRIBUTION_NAME
    scripts = project["project"]["scripts"]
    assert set(branding.CLI_COMMAND_NAMES) <= set(scripts)
    # Every earlier name is the same program as the command it used to be.
    for legacy in branding.LEGACY_CLI_COMMAND_NAMES:
        assert scripts[legacy] == scripts[branding.CLI_COMMAND_NAME], legacy
    for legacy in branding.LEGACY_CONTROL_CLI_COMMAND_NAMES:
        assert scripts[legacy] == scripts[branding.CONTROL_CLI_COMMAND_NAME], legacy
    assert scripts[branding.CLI_COMMAND_NAME] != scripts[branding.CONTROL_CLI_COMMAND_NAME]
    # No further alias of either command is registered behind branding's back.
    # The one exception is the short control alias, which is a console script
    # but deliberately not one of the commands the installer puts on PATH.
    commands = {scripts[branding.CLI_COMMAND_NAME], scripts[branding.CONTROL_CLI_COMMAND_NAME]}
    aliases = {name for name, target in scripts.items() if target in commands}
    assert aliases - set(branding.CLI_COMMAND_NAMES) == {"jctl"}
    assert scripts["jctl"] == scripts[branding.CONTROL_CLI_COMMAND_NAME]
    data_files = project["tool"]["setuptools"]["data-files"]
    assert data_files, "the wheel ships its reader documents as data files"
    for target in data_files:
        assert target.startswith(f"share/{branding.DISTRIBUTION_NAME}/"), target
    # The extras refer to the project by its own name, never by the earlier one.
    for group in project["project"]["optional-dependencies"].values():
        for legacy in branding.LEGACY_DISTRIBUTION_NAMES:
            assert not any(item.startswith(f"{legacy}[") for item in group), group


def test_the_frozen_build_bundles_the_metadata_under_either_distribution_name() -> None:
    spec = _read("dodaios.spec")
    assert f"\nDISTRIBUTION_NAMES = {branding.DISTRIBUTION_NAMES!r}\n" in spec
    assert "datas += copy_metadata(_installed_distribution())" in spec


def test_the_frontend_restates_the_display_name_and_a_known_repository() -> None:
    source = _read("dodaios/ui/web/frontend/src/lib/branding.ts")
    name = re.search(r'^export const PRODUCT_NAME = "([^"]+)";$', source, re.MULTILINE)
    slug = re.search(r'^export const OFFICIAL_REPO_SLUG = "([^"]+)";$', source, re.MULTILINE)
    assert name is not None and name.group(1) == branding.PRODUCT_NAME
    # The repository moved once; either address reaches it, nothing else may.
    assert slug is not None and slug.group(1) in (
        branding.DEFAULT_OFFICIAL_REPO_SLUG,
        *branding.LEGACY_OFFICIAL_REPO_SLUGS,
    )


# ---------------------------------------------------------------------------
# One resolver per directory
# ---------------------------------------------------------------------------


def _load_runtime_hook() -> ModuleType:
    path = _ROOT / "packaging" / "pyinstaller_rthook_frozen.py"
    spec = importlib.util.spec_from_file_location("identity_rthook_frozen", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # a no-op outside a frozen build
    return module


@pytest.mark.parametrize(
    ("shape", "local_appdata", "expected_parts"),
    [
        # Windows: the per-user local application data directory.
        ("windows", ("Users", "ada", "AppData", "Local"), ("Users", "ada", "AppData", "Local")),
        # macOS and Linux: no LOCALAPPDATA, so the dot directory in the home.
        ("macos", None, ("Users", "ada")),
        ("linux", None, ("home", "ada")),
        # An exported-but-empty variable is not a directory.
        ("empty-variable", (), ("home", "ada")),
    ],
)
def test_the_user_data_directory_on_every_os_shape(
    shape: str,
    local_appdata: tuple[str, ...] | None,
    expected_parts: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_parts = ("Users", "ada") if shape in {"windows", "macos"} else ("home", "ada")
    home = tmp_path.joinpath(*home_parts)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    # Variables other platforms use for the same idea must not move the directory.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    if local_appdata is None:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    elif not local_appdata:
        monkeypatch.setenv("LOCALAPPDATA", "")
    else:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path.joinpath(*local_appdata)))

    leaf = (
        branding.WINDOWS_USER_DATA_DIR_NAME
        if shape == "windows"
        else branding.FALLBACK_USER_DATA_DIR_NAME
    )
    expected = tmp_path.joinpath(*expected_parts) / leaf
    assert user_data_dir() == expected
    # The frozen build's hook cannot import the package; its copy must agree.
    assert _load_runtime_hook()._user_data_dir() == expected


def test_the_data_directory_has_one_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "checkout"
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)
    monkeypatch.delenv(INSTANCE_ENV_VAR, raising=False)
    assert resolve_data_dir(root) == root / "data"

    monkeypatch.setenv(INSTANCE_ENV_VAR, DEV_INSTANCE_NAME)
    assert resolve_data_dir(root) == root / "data-dev"

    # The override wins over the instance, is trimmed, and a blank one is ignored.
    monkeypatch.setenv(DATA_DIR_ENV_VAR, f"  {tmp_path / 'elsewhere'}  ")
    assert resolve_data_dir(root) == tmp_path / "elsewhere"
    monkeypatch.setenv(DATA_DIR_ENV_VAR, "   ")
    assert resolve_data_dir(root) == root / "data-dev"


def test_config_and_the_early_log_resolve_through_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for override in (None, tmp_path / "override"):
        if override is None:
            monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)
        else:
            monkeypatch.setenv(DATA_DIR_ENV_VAR, str(override))
        expected = resolve_data_dir(core_config.PROJECT_ROOT)
        assert core_config._resolve_data_dir() == expected
        assert desktop_log_path() == expected / DESKTOP_LOG_FILE_NAME


@pytest.mark.usefixtures("prefixed_environment_restored")
def test_the_frozen_hook_points_the_data_directory_inside_the_user_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import sys

    hook = _load_runtime_hook()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    # Blank counts as unset for the hook, and setting (not deleting) the two
    # variables lets monkeypatch take back what the hook exports.
    monkeypatch.setenv("JARVIS_CONFIG", "")
    monkeypatch.setenv(DATA_DIR_ENV_VAR, "")

    hook._apply()

    # What the hook exports is what the shared resolver then returns.
    assert Path(os.environ[DATA_DIR_ENV_VAR]) == user_data_dir() / "data"
    assert resolve_data_dir(tmp_path / "ignored") == user_data_dir() / "data"
    assert Path(os.environ["JARVIS_CONFIG"]) == user_data_dir() / branding.CONFIG_FILE_NAME
    # The package resolves the same file the hook pointed at.
    assert core_config.resolve_config_file(user_data_dir()) == Path(os.environ["JARVIS_CONFIG"])


# ---------------------------------------------------------------------------
# No two names collide
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityName:
    """One name as it exists on a machine.

    ``namespace`` is where the name lives (names in one namespace can clash),
    ``role`` is what it names, ``generation`` tells a current name from one an
    older installation still carries.
    """

    namespace: str
    role: str
    generation: str
    value: str


# Namespace and role of every branding constant that names something on disk or
# in an OS registry. A constant ``X`` may come with ``LEGACY_X`` (one earlier
# value) or ``LEGACY_XS`` (several): the table picks those up by name.
_ROLES: tuple[tuple[str, str, str], ...] = (
    ("executable", "gui-exe", "WINDOWS_BRANDED_LAUNCHER_FILE_NAME"),
    ("executable", "gui-exe", "MACOS_EXECUTABLE_NAME"),
    ("home-dir", "install", "DEFAULT_INSTALL_DIR_NAME"),
    ("home-dir", "data", "FALLBACK_USER_DATA_DIR_NAME"),
    ("localappdata-dir", "data", "WINDOWS_USER_DATA_DIR_NAME"),
    ("localappdata-dir", "launcher", "WINDOWS_BRANDED_LAUNCHER_DIR_NAME"),
    ("macos-bundle-id", "managed", "MACOS_BUNDLE_ID"),
    ("macos-bundle-id", "dmg", "MACOS_DMG_BUNDLE_ID"),
    ("keyring-service", "app", "KEYRING_SERVICE_NAME"),
    ("applications-dir", "app", "MACOS_APP_DIR_NAME"),
    ("start-menu", "app", "WINDOWS_SHORTCUT_FILE_NAME"),
    ("desktop-entry", "app", "LINUX_DESKTOP_ENTRY_FILE_NAME"),
    # The config file sits in the checkout root or in the per-user directory.
    ("config-dir", "config", "CONFIG_FILE_NAME"),
    # Both folders can land on the Desktop (deliverables fall back to it).
    ("desktop-dir", "output-mirror", "DESKTOP_OUTPUT_MIRROR_DIR_NAME"),
    ("desktop-dir", "deliverables", "DELIVERABLES_DIR_NAME"),
    ("vault-dir", "wiki", "OBSIDIAN_VAULT_FOLDER_NAME"),
)


def _executable_stem(value: str) -> str:
    return value[:-4] if value.casefold().endswith(".exe") else value


def _names_from(module: ModuleType, console_scripts: list[str]) -> list[IdentityName]:
    names: list[IdentityName] = []
    for namespace, role, constant in _ROLES:
        generations = [("current", (getattr(module, constant),))]
        legacy_one = getattr(module, f"LEGACY_{constant}", None)
        legacy_many = getattr(module, f"LEGACY_{constant}S", ())
        legacy = (*((legacy_one,) if legacy_one else ()), *legacy_many)
        generations.append(("legacy", legacy))
        for generation, values in generations:
            for value in values:
                stem = _executable_stem(value) if namespace == "executable" else value
                names.append(IdentityName(namespace, role, generation, stem))
    # Every console script lands in the same folder as the branded launcher.
    names += [
        IdentityName("executable", f"cli:{name}", "current", name) for name in console_scripts
    ]
    return names


def _collisions(names: list[IdentityName]) -> list[str]:
    """Pairs that differ in what they name but not in their case-folded spelling."""
    found: list[str] = []
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            if first.namespace != second.namespace or first.role == second.role:
                continue
            if first.value.casefold() == second.value.casefold():
                found.append(
                    f"{first.namespace}: {first.role} ({first.generation}) {first.value!r} "
                    f"== {second.role} ({second.generation}) {second.value!r}"
                )
    return found


def _console_scripts() -> list[str]:
    return sorted(tomllib.loads(_read("pyproject.toml"))["project"]["scripts"])


def _current_names() -> list[IdentityName]:
    return _names_from(branding, _console_scripts())


# The names the product is planned to move to. Data only: nothing sets them
# yet. When they become the branding values, today's values become LEGACY_*
# and the first test below covers them without this table. The commands
# ``dodaios`` and ``dodaiosctl`` already made that move: they are console
# scripts now, and the first test sees them among the current names. So did
# the data directory and the config file, the install directory, the
# Windows identity (the windowed executable, its per-user folder, the
# shortcut), the Linux desktop entry and the macOS bundle's name: current names
# now, with their earlier values in LEGACY_* tuples. The macOS bundle ids below
# are planned only: a new id starts every privacy grant over, so they wait for
# their own migration.
_PLANNED_NAMES: tuple[IdentityName, ...] = (
    IdentityName("macos-bundle-id", "managed", "planned", "com.dodaios.desktop"),
    IdentityName("macos-bundle-id", "dmg", "planned", "ai.dodaios.desktop"),
)


def test_no_two_current_or_legacy_names_collide() -> None:
    names = _current_names()
    # The table is not empty by accident, and it sees the known near miss: the
    # branded launcher and the hyphenated command differ by more than case.
    values = {(name.role, name.value) for name in names}
    assert ("gui-exe", _executable_stem(branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME)) in values
    # Every command the install puts on PATH is in the table, the new names
    # and the earlier ones alike.
    for command in branding.CLI_COMMAND_NAMES:
        assert (f"cli:{command}", command) in values
    assert _collisions(names) == []


def test_the_launcher_names_stay_clear_of_the_commands_that_exist() -> None:
    # The windowed executable shares a folder with the console scripts, under
    # its current name and its earlier one (the frozen build ships both).
    gui = [name for name in _current_names() if name.role == "gui-exe"]
    assert {(name.generation, name.value) for name in gui} >= {
        ("current", "DodaiosApp"),
        ("legacy", "PersonalJarvis"),
    }
    commands = {name.casefold() for name in _console_scripts()}
    for name in gui:
        assert name.value.casefold() not in commands
    # And the check has teeth: a launcher spelled like the command is caught.
    clash = IdentityName("executable", "gui-exe", "planned", branding.CLI_COMMAND_NAME.title())
    assert len(_collisions([*_current_names(), clash])) == 1


def test_the_windows_identity_moved_with_its_earlier_names_in_the_table() -> None:
    names = _current_names()
    found = {(n.namespace, n.role, n.generation, n.value) for n in names}
    assert ("localappdata-dir", "launcher", "current", "DodaiosApp") in found
    assert ("localappdata-dir", "launcher", "legacy", "PersonalJarvis") in found
    assert ("start-menu", "app", "current", "Dodaios.lnk") in found
    assert ("start-menu", "app", "legacy", "Personal Jarvis.lnk") in found
    # The launcher folder sits beside the data directory, so it cannot take
    # the plain product name the data directory has.
    data = next(n for n in names if n.role == "data" and n.namespace == "localappdata-dir")
    clash = IdentityName("localappdata-dir", "launcher", "planned", data.value)
    assert len(_collisions([*names, clash])) == 1


def test_the_macos_bundle_name_moved_with_its_earlier_name_in_the_table() -> None:
    names = _current_names()
    bundle = {(n.generation, n.value) for n in names if n.namespace == "applications-dir"}
    assert bundle == {("current", "Dodaios.app"), ("legacy", "Personal Jarvis.app")}


def test_the_planned_names_collide_with_nothing_an_installation_carries() -> None:
    assert _collisions([*_current_names(), *_PLANNED_NAMES]) == []


def test_the_data_directory_moved_with_its_earlier_names_in_the_table() -> None:
    names = _current_names()
    data = {(n.namespace, n.generation, n.value) for n in names if n.role == "data"}
    assert ("localappdata-dir", "current", "Dodaios") in data
    assert ("localappdata-dir", "legacy", "Jarvis") in data
    assert ("home-dir", "current", ".dodaios-data") in data
    assert ("home-dir", "legacy", ".jarvis") in data
    config = {(n.generation, n.value) for n in names if n.role == "config"}
    assert config == {("current", "dodaios.toml"), ("legacy", "jarvis.toml")}
    # A launcher folder named like the data directory would be the same folder.
    clash = IdentityName("localappdata-dir", "launcher", "planned", "dodaios")
    assert len(_collisions([*names, clash])) == 1


def test_the_install_directory_moved_with_its_earlier_name_in_the_table() -> None:
    names = _current_names()
    install = {(n.namespace, n.generation, n.value) for n in names if n.role == "install"}
    assert install == {
        ("home-dir", "current", ".dodaios"),
        ("home-dir", "legacy", ".personal-jarvis"),
    }
    # The data directory's fallback sits in the same home directory and must
    # never be spelled like the install directory, under either name.
    clash = IdentityName("home-dir", "data", "planned", ".DODAIOS")
    assert len(_collisions([*names, clash])) == 1


def test_legacy_constants_join_the_table_by_name() -> None:
    module = ModuleType("branding_after_a_rename")
    for _namespace, _role, constant in _ROLES:
        setattr(module, constant, getattr(branding, constant))
    module.DEFAULT_INSTALL_DIR_NAME = ".renamed-again"
    module.LEGACY_DEFAULT_INSTALL_DIR_NAMES = (branding.DEFAULT_INSTALL_DIR_NAME,)
    # A new data directory that only differs in case from the OLD install
    # directory would be the same folder on Windows and macOS.
    module.FALLBACK_USER_DATA_DIR_NAME = branding.DEFAULT_INSTALL_DIR_NAME.upper()

    found = _collisions(_names_from(module, []))

    assert len(found) == 1 and "install (legacy)" in found[0] and "data (current)" in found[0]


@pytest.mark.parametrize(
    ("gui_exe", "command"),
    [("Dodaios", "dodaios"), ("PersonalJarvis", "personaljarvis")],
)
def test_a_command_spelled_like_the_launcher_is_caught(gui_exe: str, command: str) -> None:
    names = [
        IdentityName("executable", "gui-exe", "current", gui_exe),
        IdentityName("executable", f"cli:{command}", "current", command),
    ]
    assert len(_collisions(names)) == 1

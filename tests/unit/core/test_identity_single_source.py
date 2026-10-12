"""Every identity name comes from ``jarvis.core.branding``, or is pinned to it here.

Most code imports the constants. A few places cannot: a plugin held to the
no-``jarvis.*`` import rule, the PyInstaller spec and runtime hook, the shell
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

import jarvis.core.branding as branding
from jarvis.core import config as core_config
from jarvis.core.instance import (
    DATA_DIR_ENV_VAR,
    DEV_INSTANCE_NAME,
    INSTANCE_ENV_VAR,
    resolve_data_dir,
)
from jarvis.core.paths import user_data_dir
from jarvis.ui.desktop_log import DESKTOP_LOG_FILE_NAME, desktop_log_path

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
    ["jarvis/plugins/stt/deepgram_api.py", "jarvis/plugins/stt/groq_api.py"],
)
def test_a_plugin_reads_keys_from_the_hosts_keyring_service(relative_path: str) -> None:
    assert _module_constant(relative_path, "_KEYRING_SERVICE") == branding.KEYRING_SERVICE_NAME
    # The named constant is the only spelling: no second literal beside it.
    assert _read(relative_path).count(f'"{branding.KEYRING_SERVICE_NAME}"') == 1


@pytest.mark.parametrize(
    "relative_path",
    [
        "jarvis/plugins/brain/openrouter.py",
        "jarvis/plugins/stt/openrouter_stt.py",
        "jarvis/plugins/tts/openrouter_tts.py",
    ],
)
def test_a_plugin_attributes_requests_to_the_official_repository(relative_path: str) -> None:
    repository = f"https://github.com/{branding.DEFAULT_OFFICIAL_REPO_SLUG}"
    assert f'"HTTP-Referer": "{repository}"' in _read(relative_path)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("_WINDOWS_USER_DATA_DIR_NAME", branding.WINDOWS_USER_DATA_DIR_NAME),
        ("_FALLBACK_USER_DATA_DIR_NAME", branding.FALLBACK_USER_DATA_DIR_NAME),
        ("_CONFIG_FILE_NAME", branding.CONFIG_FILE_NAME),
    ],
)
def test_the_frozen_runtime_hook_restates_the_directory_names(name: str, expected: str) -> None:
    assert _module_constant("packaging/pyinstaller_rthook_frozen.py", name) == expected


def test_the_pyinstaller_spec_restates_the_bundle_names() -> None:
    assert _module_constant("jarvis.spec", "GUI_EXE_NAME") == branding.MACOS_EXECUTABLE_NAME
    assert (
        f'{_module_constant("jarvis.spec", "GUI_EXE_NAME")}.exe'
        == branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME
    )
    assert _module_constant("jarvis.spec", "CLI_EXE_NAME") == branding.CLI_COMMAND_NAME
    assert _module_constant("jarvis.spec", "MACOS_APP_NAME") == branding.MACOS_APP_DIR_NAME
    assert (
        _module_constant("jarvis.spec", "MACOS_BUNDLE_IDENTIFIER") == branding.MACOS_DMG_BUNDLE_ID
    )
    spec = _read("jarvis.spec")
    assert f'"CFBundleName": "{branding.MACOS_APP_NAME}"' in spec
    assert f'"CFBundleDisplayName": "{branding.MACOS_APP_NAME}"' in spec


# The exact-value guard: a literal equal to one of these anywhere in shipped
# Python is a second definition. Each allowed file says why it has one.
_RESTATEMENTS_ALLOWED = {
    "jarvis/core/branding.py": "the single source",
    "jarvis/plugins/stt/deepgram_api.py": "plugin without jarvis.* imports, pinned above",
    "jarvis/plugins/stt/groq_api.py": "plugin without jarvis.* imports, pinned above",
    "jarvis/agent_runtimes/acp.py": "ACP client name, an identifier of its own",
    "jarvis/agentic_ide/github_link.py": "HTTP user agent, an identifier of its own",
    "jarvis/brain/identity.py": "the former product name told to a model",
    "jarvis/codex_app_server.py": "client title sent to the Codex app server",
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
    roots = [_ROOT / "jarvis", _ROOT / "ui", _ROOT / "install", _ROOT / "packaging"]
    files = [path for root in roots for path in root.rglob("*.py")]
    return [path for path in files if "node_modules" not in path.parts]


def test_no_module_restates_an_identity_value() -> None:
    values = _distinctive_identity_values()
    assert branding.KEYRING_SERVICE_NAME in values
    assert branding.MACOS_BUNDLE_ID in values
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
    assert not offenders, "import the constant from jarvis.core.branding:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# Scripts, packaging and project metadata
# ---------------------------------------------------------------------------


def test_the_installers_default_to_the_branded_install_directory() -> None:
    name = re.escape(branding.DEFAULT_INSTALL_DIR_NAME)
    shell = re.search(
        r'^INSTALL_DIR="\$\{JARVIS_INSTALL_DIR:-\$HOME/(?P<name>[^}"]+)\}"$',
        _read("install/install.sh"),
        re.MULTILINE,
    )
    assert shell is not None and re.fullmatch(name, shell.group("name"))
    powershell = re.search(
        r"^\$InstallDir = .*Join-Path \$env:USERPROFILE '(?P<name>[^']+)' \}$",
        _read("install/install.ps1"),
        re.MULTILINE,
    )
    assert powershell is not None and re.fullmatch(name, powershell.group("name"))


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


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        ("AppName", branding.LAUNCHER_ENTRY_NAME),
        ("GuiExeName", branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME),
        ("CliExeName", f"{branding.CLI_COMMAND_NAME}.exe"),
        ("UserDataDirDisplay", rf"%LOCALAPPDATA%\{branding.WINDOWS_USER_DATA_DIR_NAME}"),
    ],
)
def test_the_windows_installer_script_restates_the_names(definition: str, expected: str) -> None:
    assert f'\n#define {definition} "{expected}"\n' in _read(
        "packaging/windows/PersonalJarvis.iss"
    )


def test_the_packaging_scripts_restate_the_names() -> None:
    windows = _read("packaging/windows/build.ps1")
    assert (
        f'@("{branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME}", "{branding.CLI_COMMAND_NAME}.exe")'
        in windows
    )
    assert (
        f'\nDESKTOP_FILE_NAME="{branding.LINUX_DESKTOP_ENTRY_FILE_NAME}"\n'
        in _read("packaging/linux/build.sh")
    )
    assert f'\nAPP_NAME="{branding.MACOS_APP_NAME}"\n' in _read("packaging/macos/build.sh")


def test_the_project_metadata_restates_the_distribution_and_its_commands() -> None:
    project = tomllib.loads(_read("pyproject.toml"))
    assert project["project"]["name"] == branding.DISTRIBUTION_NAME
    scripts = project["project"]["scripts"]
    assert set(branding.CLI_COMMAND_NAMES) <= set(scripts)
    assert scripts[branding.CLI_COMMAND_NAME] == scripts[branding.CLI_COMMAND_ALIAS]
    data_files = project["tool"]["setuptools"]["data-files"]
    assert data_files, "the wheel ships its reader documents as data files"
    for target in data_files:
        assert target.startswith(f"share/{branding.DISTRIBUTION_NAME}/"), target


def test_the_frontend_restates_the_display_name_and_a_known_repository() -> None:
    source = _read("jarvis/ui/web/frontend/src/lib/branding.ts")
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
# and the first test below covers them without this table.
_PLANNED_NAMES: tuple[IdentityName, ...] = (
    IdentityName("executable", "gui-exe", "planned", "DodaiosApp"),
    IdentityName("executable", "cli:dodaios", "planned", "dodaios"),
    IdentityName("home-dir", "install", "planned", ".dodaios"),
    IdentityName("home-dir", "data", "planned", ".dodaios-data"),
    IdentityName("localappdata-dir", "data", "planned", "Dodaios"),
    IdentityName("macos-bundle-id", "managed", "planned", "com.dodaios.desktop"),
    IdentityName("macos-bundle-id", "dmg", "planned", "ai.dodaios.desktop"),
    IdentityName("keyring-service", "app", "planned", "dodaios"),
)


def test_no_two_current_or_legacy_names_collide() -> None:
    names = _current_names()
    # The table is not empty by accident, and it sees the known near miss: the
    # branded launcher and the hyphenated command differ by more than case.
    values = {(name.role, name.value) for name in names}
    assert ("gui-exe", _executable_stem(branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME)) in values
    assert (f"cli:{branding.CLI_COMMAND_ALIAS}", branding.CLI_COMMAND_ALIAS) in values
    assert _collisions(names) == []


def test_the_planned_names_collide_with_nothing_an_installation_carries() -> None:
    assert _collisions([*_current_names(), *_PLANNED_NAMES]) == []


def test_legacy_constants_join_the_table_by_name() -> None:
    module = ModuleType("branding_after_a_rename")
    for _namespace, _role, constant in _ROLES:
        setattr(module, constant, getattr(branding, constant))
    module.DEFAULT_INSTALL_DIR_NAME = ".dodaios"
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

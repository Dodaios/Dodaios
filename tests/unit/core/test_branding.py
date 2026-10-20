"""Freeze the persistent product identity values used by existing installs.

The display name (``PRODUCT_NAME``) may change; every persistent identifier
below is a compatibility contract and keeps the value installs were made with.
"""

from __future__ import annotations

import importlib
import os

import pytest

import dodaios.core.branding as branding

_CURRENT_IDENTITY = {
    "PERSISTENT_PRODUCT_NAME": "Personal Jarvis",
    "PERSISTENT_COMPACT_NAME": "PersonalJarvis",
    "PERSISTENT_SLUG": "personal-jarvis",
    "PRODUCT_COMPACT_NAME": "PersonalJarvis",
    "PRODUCT_SLUG": "personal-jarvis",
    "LAUNCHER_ENTRY_NAME": "Dodaios",
    "LEGACY_LAUNCHER_ENTRY_NAMES": ("Personal Jarvis",),
    "CONFIG_FILE_NAME": "dodaios.toml",
    "LEGACY_CONFIG_FILE_NAMES": ("jarvis.toml",),
    "DISTRIBUTION_NAME": "dodaios",
    "LEGACY_DISTRIBUTION_NAMES": ("personal-jarvis",),
    "DISTRIBUTION_NAMES": ("dodaios", "personal-jarvis"),
    "CLI_COMMAND_NAME": "dodaios",
    "CONTROL_CLI_COMMAND_NAME": "dodaiosctl",
    "LEGACY_CLI_COMMAND_NAMES": ("jarvis", "personal-jarvis"),
    "LEGACY_CONTROL_CLI_COMMAND_NAMES": ("jarvisctl",),
    "CLI_COMMAND_NAMES": ("dodaios", "dodaiosctl", "jarvis", "personal-jarvis", "jarvisctl"),
    "SHELL_PROFILE_MARKER": "# Personal Jarvis: command-line tools (jarvis, personal-jarvis)",
    "FISH_CONF_FILE_NAME": "personal-jarvis.fish",
    "KEYRING_SERVICE_NAME": "dodaios",
    "LEGACY_KEYRING_SERVICE_NAMES": ("personal-jarvis",),
    "CONTROL_KEY_PREFIX": "jctl_",
    "SESSION_COOKIE_NAME": "jarvis_session",
    "MANAGED_INSTALL_MARKER": ".dodaios-managed-install",
    "LEGACY_MANAGED_INSTALL_MARKERS": (".jarvis-managed-install",),
    "MANAGED_INSTALL_MARKERS": (".dodaios-managed-install", ".jarvis-managed-install"),
    "DEFAULT_INSTALL_DIR_NAME": ".dodaios",
    "LEGACY_DEFAULT_INSTALL_DIR_NAMES": (".personal-jarvis",),
    "WINDOWS_USER_DATA_DIR_NAME": "Dodaios",
    "LEGACY_WINDOWS_USER_DATA_DIR_NAMES": ("Jarvis",),
    "FALLBACK_USER_DATA_DIR_NAME": ".dodaios-data",
    "LEGACY_FALLBACK_USER_DATA_DIR_NAMES": (".jarvis",),
    "DESKTOP_OUTPUT_MIRROR_DIR_NAME": "Dodaios-Output",
    "LEGACY_DESKTOP_OUTPUT_MIRROR_DIR_NAMES": ("Jarvis-Output",),
    "DELIVERABLES_DIR_NAME": "Dodaios-Outputs",
    "LEGACY_DELIVERABLES_DIR_NAMES": ("Jarvis-Outputs",),
    "OBSIDIAN_VAULT_FOLDER_NAME": "Dodaios",
    "LEGACY_OBSIDIAN_VAULT_FOLDER_NAMES": ("Jarvis",),
    "WINDOWS_MUTEX_NAME": r"Global\Dodaios_v1",
    "LEGACY_WINDOWS_MUTEX_NAMES": (r"Global\PersonalJarvis_v1",),
    "WINDOWS_APP_USER_MODEL_ID": "PersonalJarvis.PersonalJarvis",
    "WINDOWS_UNINSTALL_REGISTRY_SUBKEY": (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PersonalJarvis"
    ),
    "WINDOWS_AUTOSTART_TASK_NAME": "Dodaios Autostart",
    "LEGACY_WINDOWS_AUTOSTART_TASK_NAMES": ("Personal Jarvis Autostart",),
    "WINDOWS_SHORTCUT_FILE_NAME": "Dodaios.lnk",
    "LEGACY_WINDOWS_SHORTCUT_FILE_NAMES": ("Personal Jarvis.lnk",),
    "WINDOWS_AUTOSTART_DESCRIPTION": "Dodaios (Autostart)",
    "LEGACY_WINDOWS_AUTOSTART_DESCRIPTIONS": ("Personal Jarvis (Autostart)",),
    "WINDOWS_BRANDED_LAUNCHER_FILE_NAME": "DodaiosApp.exe",
    "LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES": ("PersonalJarvis.exe",),
    "WINDOWS_BRANDED_LAUNCHER_DIR_NAME": "DodaiosApp",
    "LEGACY_WINDOWS_BRANDED_LAUNCHER_DIR_NAMES": ("PersonalJarvis",),
    "WINDOWS_BRANDED_LAUNCH_ENV_VAR": "JARVIS_BRANDED_LAUNCH",
    "MACOS_APP_NAME": "Dodaios",
    "LEGACY_MACOS_APP_NAMES": ("Personal Jarvis",),
    "MACOS_APP_DIR_NAME": "Dodaios.app",
    "LEGACY_MACOS_APP_DIR_NAMES": ("Personal Jarvis.app",),
    "MACOS_APP_DIR_NAMES": ("Dodaios.app", "Personal Jarvis.app"),
    "MACOS_EXECUTABLE_NAME": "DodaiosApp",
    "LEGACY_MACOS_EXECUTABLE_NAMES": ("PersonalJarvis",),
    "MACOS_BUNDLE_ID": "com.personal-jarvis.desktop",
    "MACOS_DMG_BUNDLE_ID": "ai.personaljarvis.desktop",
    "MACOS_AUTOSTART_LABEL": "com.personal-jarvis.autostart",
    "MACOS_SIGNING_IDENTITY_LABEL": "Personal Jarvis Local Signing",
    "LINUX_APP_NAME": "Dodaios",
    "LEGACY_LINUX_APP_NAMES": ("Personal Jarvis",),
    "LINUX_DESKTOP_ENTRY_FILE_NAME": "dodaios.desktop",
    "LEGACY_LINUX_DESKTOP_ENTRY_FILE_NAMES": ("personal-jarvis.desktop",),
    "LINUX_WM_CLASS": "dodaios",
    "LEGACY_LINUX_WM_CLASSES": ("personal-jarvis",),
    "DEFAULT_OFFICIAL_REPO_SLUG": "Dodaios/Dodaios",
    "OFFICIAL_REPO_SLUG_ENV_VAR": "JARVIS_OFFICIAL_REPO_SLUG",
    "OFFICIAL_REPO_SLUG": "Dodaios/Dodaios",
    "OFFICIAL_REPO_URL": "https://github.com/Dodaios/Dodaios",
    "OFFICIAL_REPO_GIT_URL": "https://github.com/Dodaios/Dodaios.git",
    "OFFICIAL_RELEASES_LATEST_API_URL": (
        "https://api.github.com/repos/Dodaios/Dodaios/releases/latest"
    ),
    "UPDATER_USER_AGENT": "PersonalJarvis-Updater",
}


# Names that moved to the product's spelling together with their migration.
# Each keeps its earlier values in the matching ``LEGACY_*`` tuple.
_MIGRATED_TO_THE_PRODUCT_NAME = frozenset(
    {
        "CONFIG_FILE_NAME",
        "WINDOWS_USER_DATA_DIR_NAME",
        "FALLBACK_USER_DATA_DIR_NAME",
        "DESKTOP_OUTPUT_MIRROR_DIR_NAME",
        "DELIVERABLES_DIR_NAME",
        "OBSIDIAN_VAULT_FOLDER_NAME",
        "MANAGED_INSTALL_MARKER",
        "DEFAULT_INSTALL_DIR_NAME",
        # The Windows identity: launcher, shortcut, logon task, mutex.
        "LAUNCHER_ENTRY_NAME",
        "WINDOWS_MUTEX_NAME",
        "WINDOWS_AUTOSTART_TASK_NAME",
        "WINDOWS_AUTOSTART_DESCRIPTION",
        "WINDOWS_SHORTCUT_FILE_NAME",
        "WINDOWS_BRANDED_LAUNCHER_FILE_NAME",
        "WINDOWS_BRANDED_LAUNCHER_DIR_NAME",
        "MACOS_EXECUTABLE_NAME",
        # The Linux identity: menu name, desktop entry and window class, which
        # only work together (the desktop binds a window to the entry whose
        # StartupWMClass is the window's class).
        "LINUX_APP_NAME",
        "LINUX_DESKTOP_ENTRY_FILE_NAME",
        "LINUX_WM_CLASS",
        # The Python distribution (pip install name, share/<name>).
        "DISTRIBUTION_NAME",
        # The macOS bundle's name; its ids, login label and signing label stay.
        "MACOS_APP_NAME",
        "MACOS_APP_DIR_NAME",
    }
)
# Every spelling of a migrated name, the current one first.
_ALL_SPELLINGS_OF_A_MIGRATED_NAME = frozenset(
    {"MANAGED_INSTALL_MARKERS", "DISTRIBUTION_NAMES", "MACOS_APP_DIR_NAMES"}
)


def _legacy_values(name: str) -> tuple[str, ...]:
    """The ``LEGACY_*`` tuple of ``name``: its plural, ``-ES`` after an ``S``."""
    plural = f"LEGACY_{name}ES" if name.endswith("S") else f"LEGACY_{name}S"
    return getattr(branding, plural)


def test_every_migrated_name_keeps_its_earlier_values() -> None:
    for name in _MIGRATED_TO_THE_PRODUCT_NAME:
        legacy = _legacy_values(name)
        assert legacy, name
        assert getattr(branding, name) not in legacy, name


def test_the_linux_names_move_as_one_generation() -> None:
    # The entry, the class it binds a window by and the menu name are all
    # current, and each earlier spelling is the one earlier releases shipped.
    assert branding.LINUX_DESKTOP_ENTRY_FILE_NAME == f"{branding.LINUX_WM_CLASS}.desktop"
    assert branding.LEGACY_LINUX_DESKTOP_ENTRY_FILE_NAMES == tuple(
        f"{wm_class}.desktop" for wm_class in branding.LEGACY_LINUX_WM_CLASSES
    )
    assert branding.LEGACY_LINUX_WM_CLASSES == (branding.PERSISTENT_SLUG,)
    assert branding.LEGACY_LINUX_APP_NAMES == (branding.PERSISTENT_PRODUCT_NAME,)


def test_default_exported_identity_values_are_frozen() -> None:
    previous = os.environ.pop(branding.OFFICIAL_REPO_SLUG_ENV_VAR, None)
    try:
        module = importlib.reload(branding)
        actual = {name: getattr(module, name) for name in _CURRENT_IDENTITY}
        assert actual == _CURRENT_IDENTITY
    finally:
        if previous is not None:
            os.environ[branding.OFFICIAL_REPO_SLUG_ENV_VAR] = previous
        importlib.reload(branding)


def test_the_windows_identity_keeps_what_pins_and_installs_resolve_by() -> None:
    # The taskbar groups windows and resolves pins by the AUMID, a source
    # install's Installed Apps entry lives under the subkey, and a process of
    # an earlier release reads the branded-launch variable: none of them moved.
    assert "Dodaios" not in branding.WINDOWS_APP_USER_MODEL_ID
    assert "Dodaios" not in branding.WINDOWS_UNINSTALL_REGISTRY_SUBKEY
    assert branding.WINDOWS_BRANDED_LAUNCH_ENV_VAR == "JARVIS_BRANDED_LAUNCH"
    # The launcher folder sits beside the data directory and must not be it.
    assert (
        branding.WINDOWS_BRANDED_LAUNCHER_DIR_NAME.casefold()
        != branding.WINDOWS_USER_DATA_DIR_NAME.casefold()
    )


def test_the_macos_identity_keeps_what_privacy_grants_are_pinned_to() -> None:
    # A bundle id, the login item's label or the signing certificate's name
    # that moved would start every macOS privacy grant over: only the bundle's
    # name moved, and a bundle under its earlier name is renamed in place.
    assert branding.MACOS_BUNDLE_ID == "com.personal-jarvis.desktop"
    assert branding.MACOS_DMG_BUNDLE_ID == "ai.personaljarvis.desktop"
    assert branding.MACOS_AUTOSTART_LABEL == "com.personal-jarvis.autostart"
    assert branding.MACOS_SIGNING_IDENTITY_LABEL == "Personal Jarvis Local Signing"
    assert branding.MACOS_APP_DIR_NAMES[0] == branding.MACOS_APP_DIR_NAME
    assert set(branding.MACOS_APP_DIR_NAMES[1:]) == set(branding.LEGACY_MACOS_APP_DIR_NAMES)


def test_display_name_is_separate_from_persistent_identity() -> None:
    assert branding.PRODUCT_NAME == "Dodaios"
    # No persistent identifier is built from the display name: renaming the
    # product must never move a path, a registry key or a credential store.
    display = branding.PRODUCT_NAME.casefold()
    for name in _CURRENT_IDENTITY:
        if "REPO" in name or "RELEASES" in name:
            continue  # the repository is itself called Dodaios/Dodaios
        if (
            "CLI_COMMAND" in name
            or name in _MIGRATED_TO_THE_PRODUCT_NAME
            or name in _ALL_SPELLINGS_OF_A_MIGRATED_NAME
            or name == "KEYRING_SERVICE_NAME"
        ):
            # Spelled like the product by choice, as literals of their own: the
            # next test shows they do not follow the display name, and each
            # keeps its earlier names beside it, found by the migration that
            # carried it over (dodaios.core.identity_boot).
            continue
        assert display not in str(getattr(branding, name)).casefold(), name


def test_persistent_identity_does_not_follow_the_display_name(monkeypatch) -> None:
    # Derivation, not coincidence: read the module source with a different
    # display name and every frozen value must come out unchanged.
    source = branding.__spec__.loader.get_source(branding.__name__)
    assert source.count('PRODUCT_NAME = "Dodaios"') == 1
    monkeypatch.delenv(branding.OFFICIAL_REPO_SLUG_ENV_VAR, raising=False)
    namespace: dict[str, object] = {"__name__": "branding_renamed"}
    renamed = source.replace('PRODUCT_NAME = "Dodaios"', 'PRODUCT_NAME = "Renamed Again"')
    exec(compile(renamed, "branding_renamed", "exec"), namespace)  # noqa: S102
    assert namespace["PRODUCT_NAME"] == "Renamed Again"
    assert {name: namespace[name] for name in _CURRENT_IDENTITY} == _CURRENT_IDENTITY


def test_official_repo_slug_override_is_exact() -> None:
    assert (
        branding.resolve_official_repo_slug(
            {"JARVIS_OFFICIAL_REPO_SLUG": "RenamedOrg/RenamedRepo"}
        )
        == "RenamedOrg/RenamedRepo"
    )


@pytest.mark.parametrize(
    "value",
    [
        "owner",
        "owner/repo/extra",
        "/repo",
        "owner/",
        "owner/repo evil",
        " owner/repo",
        "owner/repo ",
    ],
)
def test_official_repo_slug_override_rejects_non_exact_values(value: str) -> None:
    with pytest.raises(ValueError, match="exact owner/repository slug"):
        branding.resolve_official_repo_slug({"JARVIS_OFFICIAL_REPO_SLUG": value})

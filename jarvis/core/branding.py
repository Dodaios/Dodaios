"""Product naming shared across runtime surfaces: display names and persistent identity.

This module is intentionally standard-library-only and performs no filesystem or
network I/O. It keeps two kinds of name strictly apart:

* **Display names** are what a person reads: window titles, messages, prompts,
  dialogs. ``PRODUCT_NAME`` is the only one, and it may change freely.
* **Persistent identifiers** are compatibility contracts with installations that
  already exist: the keyring service that holds a user's credentials, the install
  and data directories, the Windows mutex, AppUserModelID, registry subkey and
  scheduled task, the macOS bundle name, bundle ids and signing identity, the
  Linux desktop entry and window class, the updater's user agent. Changing one
  without an explicit migration would orphan an installation's files,
  credentials, privacy grants, desktop entries, or update channel.

Every persistent identifier derives from the ``PERSISTENT_*`` anchors below and
never from ``PRODUCT_NAME``, so renaming the product cannot move one by accident.
The anchors keep the values the product shipped with; they change only together
with the migration that carries existing installations over.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# --- Display name ------------------------------------------------------------
# The name a person reads. Never build a path, a registry key, a file name, a
# process name, a bundle id or a credential-store name from it.
PRODUCT_NAME = "Dodaios"

# --- Persistent identity anchors ---------------------------------------------
# Compatibility contracts, not branding: these spell the names existing
# installations are registered under. Do not "update" them to the display name.
PERSISTENT_PRODUCT_NAME = "Personal Jarvis"
PERSISTENT_COMPACT_NAME = "PersonalJarvis"
PERSISTENT_SLUG = "personal-jarvis"
# Earlier names of the two anchors above, kept for importers outside the
# package (packaging scripts). They are persistent identifiers, not display
# text, and hold the same values as ever.
PRODUCT_COMPACT_NAME = PERSISTENT_COMPACT_NAME
PRODUCT_SLUG = PERSISTENT_SLUG
# The name the operating system lists the app under: the Start-Menu shortcut,
# the macOS bundle, the Linux desktop entry, the entry in Installed Apps. Text
# that tells a person where to find the app in the OS uses this name, because
# that is what they will see there until those artifacts are migrated.
LAUNCHER_ENTRY_NAME = PERSISTENT_PRODUCT_NAME

CONFIG_FILE_NAME = "jarvis.toml"
KEYRING_SERVICE_NAME = PERSISTENT_SLUG
CONTROL_KEY_PREFIX = "jctl_"
SESSION_COOKIE_NAME = "jarvis_session"
MANAGED_INSTALL_MARKER = ".jarvis-managed-install"
DEFAULT_INSTALL_DIR_NAME = f".{PERSISTENT_SLUG}"

WINDOWS_USER_DATA_DIR_NAME = "Jarvis"
FALLBACK_USER_DATA_DIR_NAME = ".jarvis"
DESKTOP_OUTPUT_MIRROR_DIR_NAME = "Jarvis-Output"

WINDOWS_MUTEX_NAME = rf"Global\{PERSISTENT_COMPACT_NAME}_v1"
WINDOWS_APP_USER_MODEL_ID = f"{PERSISTENT_COMPACT_NAME}.{PERSISTENT_COMPACT_NAME}"
WINDOWS_UNINSTALL_REGISTRY_SUBKEY = (
    rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{PERSISTENT_COMPACT_NAME}"
)
WINDOWS_AUTOSTART_TASK_NAME = f"{PERSISTENT_PRODUCT_NAME} Autostart"
WINDOWS_SHORTCUT_FILE_NAME = f"{PERSISTENT_PRODUCT_NAME}.lnk"
WINDOWS_AUTOSTART_DESCRIPTION = f"{PERSISTENT_PRODUCT_NAME} (Autostart)"
WINDOWS_BRANDED_LAUNCHER_FILE_NAME = f"{PERSISTENT_COMPACT_NAME}.exe"
WINDOWS_BRANDED_LAUNCHER_DIR_NAME = PERSISTENT_COMPACT_NAME
WINDOWS_BRANDED_LAUNCH_ENV_VAR = "JARVIS_BRANDED_LAUNCH"

# The bundle name: ``/Applications/<name>.app``, and the name macOS lists the
# app under in Launchpad and in System Settings > Privacy & Security.
MACOS_APP_NAME = PERSISTENT_PRODUCT_NAME
MACOS_APP_DIR_NAME = f"{MACOS_APP_NAME}.app"
MACOS_EXECUTABLE_NAME = PERSISTENT_COMPACT_NAME
MACOS_BUNDLE_ID = f"com.{PERSISTENT_SLUG}.desktop"
# The downloadable .dmg (PyInstaller, ``jarvis.spec``) is a second, equally
# legitimate installed app: its own bundle id and therefore its own macOS
# privacy grants. ``jarvis.spec`` cannot import this module, so a parity test
# (``tests/unit/setup/test_macos_dmg_identity.py``) pins its literal to this.
MACOS_DMG_BUNDLE_ID = f"ai.{PERSISTENT_COMPACT_NAME.lower()}.desktop"
MACOS_AUTOSTART_LABEL = f"com.{PERSISTENT_SLUG}.autostart"
# Common name of the per-user self-signed code-signing certificate the
# installer creates so the app bundle keeps one TCC identity across rebuilds.
MACOS_SIGNING_IDENTITY_LABEL = f"{MACOS_APP_NAME} Local Signing"

LINUX_APP_NAME = PERSISTENT_PRODUCT_NAME
LINUX_DESKTOP_ENTRY_FILE_NAME = f"{PERSISTENT_SLUG}.desktop"
LINUX_WM_CLASS = PERSISTENT_SLUG

DEFAULT_OFFICIAL_REPO_SLUG = "Dodaios/Dodaios"
# Checkouts cloned before the GitHub rename still store this origin. The
# updater accepts it and rewrites origin to the current slug when it applies.
LEGACY_OFFICIAL_REPO_SLUGS = ("PersonalJarvis/PersonalJarvis",)
OFFICIAL_REPO_SLUG_ENV_VAR = "JARVIS_OFFICIAL_REPO_SLUG"


def resolve_official_repo_slug(environ: Mapping[str, str] | None = None) -> str:
    """Resolve one exact ``owner/repository`` slug from the process environment."""

    source = os.environ if environ is None else environ
    candidate = source.get(OFFICIAL_REPO_SLUG_ENV_VAR, "")
    if not candidate:
        return DEFAULT_OFFICIAL_REPO_SLUG
    parts = candidate.split("/")
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if len(parts) != 2 or any(not part or not set(part) <= allowed for part in parts):
        raise ValueError(
            f"{OFFICIAL_REPO_SLUG_ENV_VAR} must be an exact owner/repository slug"
        )
    return candidate


OFFICIAL_REPO_SLUG = resolve_official_repo_slug()
OFFICIAL_REPO_URL = f"https://github.com/{OFFICIAL_REPO_SLUG}"
OFFICIAL_REPO_GIT_URL = f"{OFFICIAL_REPO_URL}.git"
OFFICIAL_RELEASES_LATEST_API_URL = (
    f"https://api.github.com/repos/{OFFICIAL_REPO_SLUG}/releases/latest"
)
UPDATER_USER_AGENT = f"{PERSISTENT_COMPACT_NAME}-Updater"

__all__ = [
    "CONFIG_FILE_NAME",
    "CONTROL_KEY_PREFIX",
    "DEFAULT_OFFICIAL_REPO_SLUG",
    "DEFAULT_INSTALL_DIR_NAME",
    "LEGACY_OFFICIAL_REPO_SLUGS",
    "DESKTOP_OUTPUT_MIRROR_DIR_NAME",
    "FALLBACK_USER_DATA_DIR_NAME",
    "KEYRING_SERVICE_NAME",
    "LAUNCHER_ENTRY_NAME",
    "LINUX_APP_NAME",
    "LINUX_DESKTOP_ENTRY_FILE_NAME",
    "LINUX_WM_CLASS",
    "MACOS_APP_DIR_NAME",
    "MACOS_APP_NAME",
    "MACOS_AUTOSTART_LABEL",
    "MACOS_BUNDLE_ID",
    "MACOS_DMG_BUNDLE_ID",
    "MACOS_EXECUTABLE_NAME",
    "MACOS_SIGNING_IDENTITY_LABEL",
    "MANAGED_INSTALL_MARKER",
    "OFFICIAL_RELEASES_LATEST_API_URL",
    "OFFICIAL_REPO_GIT_URL",
    "OFFICIAL_REPO_SLUG",
    "OFFICIAL_REPO_SLUG_ENV_VAR",
    "OFFICIAL_REPO_URL",
    "PERSISTENT_COMPACT_NAME",
    "PERSISTENT_PRODUCT_NAME",
    "PERSISTENT_SLUG",
    "PRODUCT_COMPACT_NAME",
    "PRODUCT_NAME",
    "PRODUCT_SLUG",
    "SESSION_COOKIE_NAME",
    "UPDATER_USER_AGENT",
    "WINDOWS_APP_USER_MODEL_ID",
    "WINDOWS_AUTOSTART_DESCRIPTION",
    "WINDOWS_AUTOSTART_TASK_NAME",
    "WINDOWS_BRANDED_LAUNCHER_DIR_NAME",
    "WINDOWS_BRANDED_LAUNCHER_FILE_NAME",
    "WINDOWS_BRANDED_LAUNCH_ENV_VAR",
    "WINDOWS_MUTEX_NAME",
    "WINDOWS_SHORTCUT_FILE_NAME",
    "WINDOWS_UNINSTALL_REGISTRY_SUBKEY",
    "WINDOWS_USER_DATA_DIR_NAME",
    "resolve_official_repo_slug",
]

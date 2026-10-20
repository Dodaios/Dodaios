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
# The name Windows lists the app under: the Start-Menu and Desktop shortcut, the
# entry in Installed Apps, the toast identity. Text that tells a person where to
# find the app on Windows uses this name. The macOS bundle and the Linux desktop
# entry have names of their own (``MACOS_APP_NAME``, ``LINUX_APP_NAME``), each
# moved with its own migration.
LAUNCHER_ENTRY_NAME = "Dodaios"
LEGACY_LAUNCHER_ENTRY_NAMES = (PERSISTENT_PRODUCT_NAME,)

# The configuration file's name. A file under an earlier name is never
# renamed: while it exists it stays the configuration, and only an install
# that has none creates one under the current name
# (``dodaios.core.config.resolve_config_file``).
CONFIG_FILE_NAME = "dodaios.toml"
LEGACY_CONFIG_FILE_NAMES = ("jarvis.toml",)
# The credential-store service every key is filed under (Windows Credential
# Manager, macOS Keychain, Secret Service, the 0600 file fallback). Spelled as
# a literal of its own, like the commands: it does not follow the display name.
KEYRING_SERVICE_NAME = "dodaios"
# Services earlier versions filed keys under. ``dodaios.core.config`` reads
# them as a fallback and deletes from them too, and a background job copies
# their entries once (``dodaios.core.identity_credentials``). Nothing deletes
# a legacy entry except an explicit delete of that key: it is the way back for
# a downgrade.
LEGACY_KEYRING_SERVICE_NAMES = (PERSISTENT_SLUG,)
CONTROL_KEY_PREFIX = "jctl_"
SESSION_COOKIE_NAME = "jarvis_session"
# The file the one-line installer writes into the checkout it manages. Its
# presence (together with the official origin) is what lets the in-app updater
# reset the checkout. The installer writes every name, so an updater of any
# version recognises the checkout; every reader accepts any of them.
MANAGED_INSTALL_MARKER = ".dodaios-managed-install"
LEGACY_MANAGED_INSTALL_MARKERS = (".jarvis-managed-install",)
MANAGED_INSTALL_MARKERS = (MANAGED_INSTALL_MARKER, *LEGACY_MANAGED_INSTALL_MARKERS)
# The one-line installer's checkout in the home directory. An install under an
# earlier name keeps it while it is a real directory; an update run moves it by
# one rename and leaves a link behind (``install/install.sh``,
# ``install/install.ps1``, through ``dodaios.core.identity_migration``).
DEFAULT_INSTALL_DIR_NAME = ".dodaios"
LEGACY_DEFAULT_INSTALL_DIR_NAMES = (f".{PERSISTENT_SLUG}",)
# The Python distribution name (``pip install <name>``) and with it the
# ``share/<name>`` directory a wheel installs its data files under.
DISTRIBUTION_NAME = "dodaios"
# The distribution's earlier name. Releases publish the same wheel under it for
# a transition, so ``pip install -U <earlier name>`` keeps updating; its data
# files stay under ``share/<earlier name>``, which every reader still accepts.
# Both own the same package files, so an environment should hold only one:
# the installer removes the earlier one before installing, and the app warns
# once when it finds both (``dodaios.core.distribution``).
LEGACY_DISTRIBUTION_NAMES = (PERSISTENT_SLUG,)
DISTRIBUTION_NAMES = (DISTRIBUTION_NAME, *LEGACY_DISTRIBUTION_NAMES)

# Terminal commands the install puts on PATH. No command may equal the branded
# launcher's name ignoring case: on Windows and macOS they would be one file.
# The first two are the names help text, hints and documentation use.
CLI_COMMAND_NAME = "dodaios"
CONTROL_CLI_COMMAND_NAME = "dodaiosctl"
# Earlier names of the two commands. They stay installed and keep working:
# scripts, shell history and other tools call them.
LEGACY_CLI_COMMAND_NAMES = ("jarvis", PERSISTENT_SLUG)
LEGACY_CONTROL_CLI_COMMAND_NAMES = ("jarvisctl",)
CLI_COMMAND_NAMES = (
    CLI_COMMAND_NAME,
    CONTROL_CLI_COMMAND_NAME,
    *LEGACY_CLI_COMMAND_NAMES,
    *LEGACY_CONTROL_CLI_COMMAND_NAMES,
)
# First line of the PATH block written into a shell profile, and the fish
# drop-in that carries the same block. Both are found again on a later install
# and on uninstall, so the line keeps the spelling existing profiles carry: it
# names the earlier commands, and the block puts every command on PATH.
SHELL_PROFILE_MARKER = (
    f"# {PERSISTENT_PRODUCT_NAME}: command-line tools ({', '.join(LEGACY_CLI_COMMAND_NAMES)})"
)
FISH_CONF_FILE_NAME = f"{PERSISTENT_SLUG}.fish"

# The per-user data directory: ``%LOCALAPPDATA%\<name>`` on Windows, ``~/<name>``
# elsewhere. An existing installation keeps its directory under the earlier
# name until the primary instance moves it (``dodaios.core.identity_boot``);
# while a real directory still stands under an earlier name, that one is used.
WINDOWS_USER_DATA_DIR_NAME = "Dodaios"
LEGACY_WINDOWS_USER_DATA_DIR_NAMES = ("Jarvis",)
FALLBACK_USER_DATA_DIR_NAME = ".dodaios-data"
LEGACY_FALLBACK_USER_DATA_DIR_NAMES = (".jarvis",)
# Folders a person opens themselves. They are found under an earlier name for
# as long as one exists there and are never moved, so nothing on the Desktop or
# in Downloads changes its name under the user's hands.
DESKTOP_OUTPUT_MIRROR_DIR_NAME = "Dodaios-Output"
LEGACY_DESKTOP_OUTPUT_MIRROR_DIR_NAMES = ("Jarvis-Output",)
# Where finished mission deliverables are mirrored (Downloads, Desktop or the
# home directory; lower-cased on a system without a file explorer).
DELIVERABLES_DIR_NAME = "Dodaios-Outputs"
LEGACY_DELIVERABLES_DIR_NAMES = ("Jarvis-Outputs",)
# The folder created inside an existing Obsidian vault the user registers.
# Only a new registration uses it; a vault root already saved in the
# configuration keeps naming the folder it names.
OBSIDIAN_VAULT_FOLDER_NAME = "Dodaios"
LEGACY_OBSIDIAN_VAULT_FOLDER_NAMES = ("Jarvis",)

# --- Marketplace manifest namespace -------------------------------------------
# The key a plugin package keeps this app's own data under
# (``plugin.json`` -> ``extensions[<namespace>]``) and the directory its
# extension files live in (``<namespace>/usage-card.md``). Every package
# published before the rename carries a legacy namespace, so those are read
# forever (``dodaios.marketplace.agent_plugins_loader``).
MARKETPLACE_EXTENSION_NAMESPACE = "io.github.dodaios"
LEGACY_MARKETPLACE_EXTENSION_NAMESPACES = ("io.github.personaljarvis",)

# The single-instance mutex the primary desktop app holds. A primary claims the
# current name and every earlier one, and a process that finds any of them taken
# is a secondary: an old and a new release never run side by side
# (``dodaios.ui.shell.single_instance``).
WINDOWS_MUTEX_NAME = r"Global\Dodaios_v1"
LEGACY_WINDOWS_MUTEX_NAMES = (rf"Global\{PERSISTENT_COMPACT_NAME}_v1",)
# Kept on purpose: the taskbar groups windows, and resolves pins, by this id.
WINDOWS_APP_USER_MODEL_ID = f"{PERSISTENT_COMPACT_NAME}.{PERSISTENT_COMPACT_NAME}"
# Kept on purpose: the key a source install's Installed Apps entry lives under.
# Only the DisplayName written into it follows ``LAUNCHER_ENTRY_NAME``.
WINDOWS_UNINSTALL_REGISTRY_SUBKEY = (
    rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{PERSISTENT_COMPACT_NAME}"
)
# The logon task. A task registered under an earlier name keeps working and
# counts as current; only an interactive enable registers it under the current
# name, removing the earlier one in the same elevated step
# (``dodaios.autostart.windows``).
WINDOWS_AUTOSTART_TASK_NAME = "Dodaios Autostart"
LEGACY_WINDOWS_AUTOSTART_TASK_NAMES = (f"{PERSISTENT_PRODUCT_NAME} Autostart",)
WINDOWS_AUTOSTART_DESCRIPTION = "Dodaios (Autostart)"
LEGACY_WINDOWS_AUTOSTART_DESCRIPTIONS = (f"{PERSISTENT_PRODUCT_NAME} (Autostart)",)
# The Start-Menu, Desktop and Startup shortcut. A shortcut under an earlier name
# is removed only where it points into this installation.
WINDOWS_SHORTCUT_FILE_NAME = "Dodaios.lnk"
LEGACY_WINDOWS_SHORTCUT_FILE_NAMES = (f"{PERSISTENT_PRODUCT_NAME}.lnk",)
# The windowed executable: the branded pythonw copy of a source install and the
# GUI executable of the frozen build (``dodaios.spec``). Not ``Dodaios.exe``: it
# shares a folder with the ``dodaios`` command, and Windows paths ignore case.
# Earlier names are still found, and the frozen build still ships one, because
# taskbar pins, scheduled tasks and shortcuts name that file.
WINDOWS_BRANDED_LAUNCHER_FILE_NAME = "DodaiosApp.exe"
LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES = (f"{PERSISTENT_COMPACT_NAME}.exe",)
# ``%LOCALAPPDATA%\<name>\bin``, the per-user home of the branded copy. Not the
# plain product name: that is the data directory beside it.
WINDOWS_BRANDED_LAUNCHER_DIR_NAME = "DodaiosApp"
LEGACY_WINDOWS_BRANDED_LAUNCHER_DIR_NAMES = (PERSISTENT_COMPACT_NAME,)
# Kept on purpose: a process of an earlier release sets and reads it.
WINDOWS_BRANDED_LAUNCH_ENV_VAR = "JARVIS_BRANDED_LAUNCH"

# The bundle name: ``/Applications/<name>.app``, and the name macOS lists the
# app under in Finder, Launchpad and System Settings > Privacy & Security. A
# bundle of ours under an earlier name is renamed once, in place
# (``dodaios.setup.macos_app_bundle``); a rename keeps its signature, and with
# it every privacy grant, because those name the bundle id and the signing
# requirement, never the path. The bundle ids, the login item's label and the
# signing identity below did NOT move: a new one starts the grants over.
MACOS_APP_NAME = "Dodaios"
LEGACY_MACOS_APP_NAMES = (PERSISTENT_PRODUCT_NAME,)
MACOS_APP_DIR_NAME = f"{MACOS_APP_NAME}.app"
LEGACY_MACOS_APP_DIR_NAMES = tuple(f"{name}.app" for name in LEGACY_MACOS_APP_NAMES)
# Every name a bundle of ours may carry in an Applications folder, current first.
MACOS_APP_DIR_NAMES = (MACOS_APP_DIR_NAME, *LEGACY_MACOS_APP_DIR_NAMES)
# ``Contents/MacOS/<name>``: the same program as the Windows GUI executable
# (``dodaios.spec`` builds both under one name). A bundle's designated
# requirement names its bundle id and certificate, not this file, so the
# rename keeps every privacy grant.
MACOS_EXECUTABLE_NAME = "DodaiosApp"
LEGACY_MACOS_EXECUTABLE_NAMES = (PERSISTENT_COMPACT_NAME,)
MACOS_BUNDLE_ID = f"com.{PERSISTENT_SLUG}.desktop"
# The downloadable .dmg (PyInstaller, ``dodaios.spec``) is a second, equally
# legitimate installed app: its own bundle id and therefore its own macOS
# privacy grants. ``dodaios.spec`` cannot import this module, so a parity test
# (``tests/unit/setup/test_macos_dmg_identity.py``) pins its literal to this.
MACOS_DMG_BUNDLE_ID = f"ai.{PERSISTENT_COMPACT_NAME.lower()}.desktop"
MACOS_AUTOSTART_LABEL = f"com.{PERSISTENT_SLUG}.autostart"
# Common name of the per-user self-signed code-signing certificate the
# installer creates so the app bundle keeps one TCC identity across rebuilds.
# Kept on purpose: the certificate already in a user's keychain carries it.
MACOS_SIGNING_IDENTITY_LABEL = f"{PERSISTENT_PRODUCT_NAME} Local Signing"

# The Linux desktop entry: the name the app menu lists, the entry's file name
# (in ``applications`` and in ``autostart``) and the window class the running
# window is pinned to. The three move together: a desktop binds a running
# window to the entry whose ``StartupWMClass`` equals the window's class, and
# shows that entry's icon for it. An entry under an earlier name is removed
# only where it starts this installation, and an earlier-named autostart entry
# that starts this installation counts as current (``dodaios.autostart.linux``).
LINUX_APP_NAME = "Dodaios"
LEGACY_LINUX_APP_NAMES = (PERSISTENT_PRODUCT_NAME,)
LINUX_DESKTOP_ENTRY_FILE_NAME = "dodaios.desktop"
LEGACY_LINUX_DESKTOP_ENTRY_FILE_NAMES = (f"{PERSISTENT_SLUG}.desktop",)
LINUX_WM_CLASS = "dodaios"
LEGACY_LINUX_WM_CLASSES = (PERSISTENT_SLUG,)

# --- Plugin entry-point groups -------------------------------------------------
# A plugin registers under ``<namespace>.<slot>`` (``dodaios.tool``,
# ``dodaios.brain``, ...). The legacy namespaces are a wire contract with every
# plugin already published: they are read forever, next to the current one, by
# ``dodaios.core.entry_points``.
PLUGIN_GROUP_NAMESPACE = "dodaios"
LEGACY_PLUGIN_GROUP_NAMESPACES = ("jarvis",)

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

# --- MCP server names ---------------------------------------------------------
# What the app calls its own MCP servers when it registers them in another
# tool's configuration: the tools server a chat's coding CLI mounts, and the
# agents surface an outside client connects. A client derives its tool names
# from that name (``mcp__<name>__<tool>``), so the legacy names stay readable
# forever: registrations and transcripts written under them still exist.
MCP_TOOLS_SERVER_NAME = "dodaios"
LEGACY_MCP_TOOLS_SERVER_NAMES = ("jarvis",)
MCP_AGENTS_SERVER_NAME = "dodaios-agents"
LEGACY_MCP_AGENTS_SERVER_NAMES = ("jarvis-agents",)

# --- Import names --------------------------------------------------------------
# Every import name the Python package has been published under. A stored
# command such as ``python -m <name>.plugins.tool.connected_server`` names its
# module by one of them and is configuration on somebody's disk, so each name
# stays recognised for good. The name the package is imported as right now is
# never restated: code reads it off the package itself (``__name__``).
LEGACY_PACKAGE_NAMES = ("jarvis",)

__all__ = [
    "CLI_COMMAND_NAME",
    "CLI_COMMAND_NAMES",
    "CONFIG_FILE_NAME",
    "CONTROL_CLI_COMMAND_NAME",
    "CONTROL_KEY_PREFIX",
    "DEFAULT_OFFICIAL_REPO_SLUG",
    "DEFAULT_INSTALL_DIR_NAME",
    "LEGACY_DEFAULT_INSTALL_DIR_NAMES",
    "LEGACY_MANAGED_INSTALL_MARKERS",
    "DELIVERABLES_DIR_NAME",
    "LEGACY_CLI_COMMAND_NAMES",
    "LEGACY_CONFIG_FILE_NAMES",
    "LEGACY_DELIVERABLES_DIR_NAMES",
    "LEGACY_DESKTOP_OUTPUT_MIRROR_DIR_NAMES",
    "LEGACY_FALLBACK_USER_DATA_DIR_NAMES",
    "LEGACY_OBSIDIAN_VAULT_FOLDER_NAMES",
    "LEGACY_LAUNCHER_ENTRY_NAMES",
    "LEGACY_MACOS_APP_DIR_NAMES",
    "LEGACY_MACOS_APP_NAMES",
    "LEGACY_MACOS_EXECUTABLE_NAMES",
    "LEGACY_WINDOWS_AUTOSTART_DESCRIPTIONS",
    "LEGACY_WINDOWS_AUTOSTART_TASK_NAMES",
    "LEGACY_WINDOWS_BRANDED_LAUNCHER_DIR_NAMES",
    "LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES",
    "LEGACY_WINDOWS_SHORTCUT_FILE_NAMES",
    "LEGACY_WINDOWS_MUTEX_NAMES",
    "LEGACY_WINDOWS_USER_DATA_DIR_NAMES",
    "LEGACY_CONTROL_CLI_COMMAND_NAMES",
    "LEGACY_OFFICIAL_REPO_SLUGS",
    "LEGACY_PACKAGE_NAMES",
    "LEGACY_PLUGIN_GROUP_NAMESPACES",
    "DESKTOP_OUTPUT_MIRROR_DIR_NAME",
    "DISTRIBUTION_NAME",
    "DISTRIBUTION_NAMES",
    "LEGACY_DISTRIBUTION_NAMES",
    "FALLBACK_USER_DATA_DIR_NAME",
    "FISH_CONF_FILE_NAME",
    "KEYRING_SERVICE_NAME",
    "LAUNCHER_ENTRY_NAME",
    "LEGACY_KEYRING_SERVICE_NAMES",
    "LEGACY_LINUX_APP_NAMES",
    "LEGACY_LINUX_DESKTOP_ENTRY_FILE_NAMES",
    "LEGACY_LINUX_WM_CLASSES",
    "LINUX_APP_NAME",
    "LINUX_DESKTOP_ENTRY_FILE_NAME",
    "LINUX_WM_CLASS",
    "LEGACY_MARKETPLACE_EXTENSION_NAMESPACES",
    "MARKETPLACE_EXTENSION_NAMESPACE",
    "MACOS_APP_DIR_NAME",
    "MACOS_APP_DIR_NAMES",
    "MACOS_APP_NAME",
    "MACOS_AUTOSTART_LABEL",
    "MACOS_BUNDLE_ID",
    "MACOS_DMG_BUNDLE_ID",
    "MACOS_EXECUTABLE_NAME",
    "MACOS_SIGNING_IDENTITY_LABEL",
    "MANAGED_INSTALL_MARKER",
    "MANAGED_INSTALL_MARKERS",
    "MCP_AGENTS_SERVER_NAME",
    "MCP_TOOLS_SERVER_NAME",
    "LEGACY_MCP_AGENTS_SERVER_NAMES",
    "LEGACY_MCP_TOOLS_SERVER_NAMES",
    "OBSIDIAN_VAULT_FOLDER_NAME",
    "OFFICIAL_RELEASES_LATEST_API_URL",
    "OFFICIAL_REPO_GIT_URL",
    "OFFICIAL_REPO_SLUG",
    "OFFICIAL_REPO_SLUG_ENV_VAR",
    "OFFICIAL_REPO_URL",
    "PERSISTENT_COMPACT_NAME",
    "PERSISTENT_PRODUCT_NAME",
    "PERSISTENT_SLUG",
    "PLUGIN_GROUP_NAMESPACE",
    "PRODUCT_COMPACT_NAME",
    "PRODUCT_NAME",
    "PRODUCT_SLUG",
    "SESSION_COOKIE_NAME",
    "SHELL_PROFILE_MARKER",
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

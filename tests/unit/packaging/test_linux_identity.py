"""The Linux packages and the running app agree on one identity.

A desktop binds a running window to the desktop entry whose ``StartupWMClass``
equals the window's class, and shows that entry's icon for it. The class is
pinned at runtime (``dodaios.ui.icon_utils.pin_linux_wm_class``) and written
into three entries: the AppImage's and the Debian package's
(``packaging/linux/make_desktop_entry.py``), the source install's menu entry
(``ensure_linux_desktop_entry``) and the login autostart entry
(``dodaios.autostart.linux``). One of them drifting leaves the dock with a
generic icon and the app listed twice, without any error anywhere.

The package scripts only run on Linux, so their names are read from the script
text: the Debian control file is rendered from its template here.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from dodaios.autostart.linux import LinuxAutostart
from dodaios.autostart.protocol import LaunchSpec
from dodaios.core import branding
from dodaios.core.desktop_entry import read_field
from dodaios.core.installer_update import INSTALLER_ASSET_NAMES
from dodaios.ui import icon_utils

_ROOT = Path(__file__).resolve().parents[3]
_BUILD_SH = _ROOT / "packaging" / "linux" / "build.sh"
_APPRUN = _ROOT / "packaging" / "linux" / "AppRun"


def _load_make_desktop_entry() -> ModuleType:
    path = _ROOT / "packaging" / "linux" / "make_desktop_entry.py"
    spec = importlib.util.spec_from_file_location("linux_make_desktop_entry", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assignments(script: str) -> dict[str, str]:
    """``NAME="value"`` lines at the top level of a shell script."""
    return dict(re.findall(r'^([A-Z_]+)="([^"$]*)"$', script, re.MULTILINE))


def _expand(text: str, values: dict[str, str]) -> str:
    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        assert name in values, f"{name} is not a plain assignment in build.sh"
        return values[name]

    return re.sub(r"\$\{([A-Z_]+)\}", value, text)


def _control_file(version: str = "9.9.9") -> dict[str, str]:
    script = _BUILD_SH.read_text(encoding="utf-8")
    template = script.split('cat > "${DEB_ROOT}/DEBIAN/control" <<EOF\n', 1)[1]
    template = template.split("\nEOF\n", 1)[0]
    rendered = _expand(template, {**_assignments(script), "VERSION": version})
    fields: dict[str, str] = {}
    for line in rendered.splitlines():
        if line and not line.startswith(" "):
            key, _, value = line.partition(": ")
            fields[key] = value
    return fields


# --------------------------------------------------------------------------- #
# One window class everywhere                                                  #
# --------------------------------------------------------------------------- #
def test_the_runtime_window_class_is_the_class_every_entry_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pinned = inspect.signature(icon_utils.pin_linux_wm_class).parameters["name"].default
    assert pinned == icon_utils.LINUX_WM_CLASS == branding.LINUX_WM_CLASS

    package_entry = _load_make_desktop_entry().render(exec_name="Jarvis")

    apps = tmp_path / "applications"
    assert icon_utils.ensure_linux_desktop_entry(applications_dir=apps) is True
    menu_entry = (apps / branding.LINUX_DESKTOP_ENTRY_FILE_NAME).read_text(encoding="utf-8")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    LinuxAutostart().install(LaunchSpec("/usr/bin/python3", ("-m", "x"), str(tmp_path)))
    autostart_entry = (
        tmp_path / "config" / "autostart" / branding.LINUX_DESKTOP_ENTRY_FILE_NAME
    ).read_text(encoding="utf-8")

    for text in (package_entry, menu_entry, autostart_entry):
        assert read_field(text, "StartupWMClass") == pinned
        assert read_field(text, "Name") == branding.LINUX_APP_NAME


def test_the_entry_and_the_class_carry_the_current_name() -> None:
    assert branding.LINUX_WM_CLASS == "dodaios"
    assert branding.LINUX_DESKTOP_ENTRY_FILE_NAME == "dodaios.desktop"
    assert branding.LINUX_APP_NAME == "Dodaios"


def test_the_pin_sets_the_class_through_glib(monkeypatch: pytest.MonkeyPatch) -> None:
    """``pin_linux_wm_class`` hands the class to GLib, which GTK derives WM_CLASS from."""

    calls: list[str] = []

    class FakeGLib:
        @staticmethod
        def set_prgname(name: str) -> None:
            calls.append(name)

    repository = ModuleType("gi.repository")
    repository.GLib = FakeGLib  # type: ignore[attr-defined]
    gi = ModuleType("gi")
    gi.repository = repository  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)
    monkeypatch.setattr(icon_utils.sys, "platform", "linux")

    assert icon_utils.pin_linux_wm_class() is True
    assert calls == [branding.LINUX_WM_CLASS]


def test_the_package_entry_names_the_icon_the_packages_install() -> None:
    values = _assignments(_BUILD_SH.read_text(encoding="utf-8"))
    icon = values["ICON_FILE_NAME"]
    assert icon == f"{branding.LINUX_WM_CLASS}.png"
    module = _load_make_desktop_entry()
    assert read_field(module.render(), "Icon") == icon.removesuffix(".png")
    assert values["DESKTOP_FILE_NAME"] == branding.LINUX_DESKTOP_ENTRY_FILE_NAME


# --------------------------------------------------------------------------- #
# The Debian package                                                           #
# --------------------------------------------------------------------------- #
def test_the_debian_package_takes_over_from_its_earlier_name() -> None:
    control = _control_file()
    assert control["Package"] == "dodaios"
    assert control["Version"] == "9.9.9"
    # dpkg removes the earlier package while installing this one (Conflicts +
    # Replaces), and whatever depends on the earlier name stays satisfied.
    assert control["Replaces"] == "personal-jarvis"
    assert control["Conflicts"] == "personal-jarvis"
    assert control["Provides"] == "personal-jarvis"


def test_the_debian_package_installs_under_the_current_names() -> None:
    script = _BUILD_SH.read_text(encoding="utf-8")
    values = _assignments(script)
    assert values["DEB_INSTALL_DIR"] == "/opt/Dodaios"
    assert "/opt/PersonalJarvis" not in script
    assert values["SHARE_DIR_NAME"] == "dodaios"
    assert "usr/share/personal-jarvis" not in script
    # The commands: the current CLI and its earlier names, and the earlier
    # command that opens the app.
    assert '\nCLI_EXE_NAMES=("dodaios" "jarvis")\n' in script
    assert (
        'ln -sf "${DEB_INSTALL_DIR}/usr/bin/${cli_name}" "${DEB_ROOT}/usr/bin/${cli_name}"'
        in script
    )
    assert values["LEGACY_APP_COMMAND_NAME"] in branding.LEGACY_CLI_COMMAND_NAMES
    assert (
        'ln -sf "${DEB_INSTALL_DIR}/AppRun" "${DEB_ROOT}/usr/bin/${LEGACY_APP_COMMAND_NAME}"'
        in script
    )
    assert '--exec "${DEB_INSTALL_DIR}/AppRun"' in script


def test_apprun_reads_the_marker_from_the_share_dir_the_build_writes() -> None:
    values = _assignments(_BUILD_SH.read_text(encoding="utf-8"))
    apprun = _APPRUN.read_text(encoding="utf-8")
    assert f'BROWSER_UI_MARKER="${{HERE}}/usr/share/{values["SHARE_DIR_NAME"]}/browser-ui"' in (
        apprun
    )


# --------------------------------------------------------------------------- #
# Release asset names: the current one, plus the earlier one as an alias      #
# --------------------------------------------------------------------------- #
def test_the_appimage_is_built_under_its_current_name() -> None:
    """The build writes the AppImage under the current asset name only; the
    earlier name is the release's job (dual publishing), not the build's."""
    script = _BUILD_SH.read_text(encoding="utf-8")
    current, earlier = INSTALLER_ASSET_NAMES[("linux", "x64")]
    assert current == "Dodaios-Linux-x86_64.AppImage"
    assert f'APPIMAGE_PATH="${{OUT_DIR}}/{current}"' in script
    # The earlier name appears in no command, only in the comment explaining the alias.
    commands = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    assert not any(earlier in line for line in commands)


def test_the_release_also_publishes_the_appimage_under_its_earlier_name(tmp_path: Path) -> None:
    """Installs frozen before the rename only look for PersonalJarvis-*: the
    release copies the built AppImage to that name, byte for byte."""
    from scripts.ci.installer_aliases import add_aliases
    from scripts.ci.release_assets import INSTALLER_NAME_PAIRS, PLATFORM_INSTALLERS

    current, earlier = INSTALLER_ASSET_NAMES[("linux", "x64")]
    assert earlier == "PersonalJarvis-Linux-x86_64.AppImage"
    assert (current, earlier) in INSTALLER_NAME_PAIRS
    assert PLATFORM_INSTALLERS["linux"] == {current, earlier}
    workflow = (_ROOT / ".github" / "workflows" / "desktop-installers.yml").read_text(
        encoding="utf-8"
    )
    assert "python scripts/ci/installer_aliases.py installers" in workflow

    # Only the AppImage pair matters here; the other installers are stand-ins.
    for other_current, _ in INSTALLER_NAME_PAIRS:
        (tmp_path / other_current).write_bytes(b"other installer")
    (tmp_path / current).write_bytes(b"\x7fELF appimage bytes")
    written = add_aliases(tmp_path)

    assert earlier in written
    assert (tmp_path / earlier).read_bytes() == (tmp_path / current).read_bytes()


def test_the_deb_keeps_its_earlier_asset_name_while_the_package_is_dodaios() -> None:
    """The .deb file name keeps the earlier spelling; the package inside it is
    dodaios and replaces the earlier package."""
    script = _BUILD_SH.read_text(encoding="utf-8")
    values = _assignments(script)
    assert values["DEB_PACKAGE_NAME"] == "dodaios"
    assert values["LEGACY_DEB_PACKAGE_NAME"] == "personal-jarvis"
    assert 'DEB_PATH="${OUT_DIR}/personal-jarvis_${VERSION}_amd64.deb"' in script
    assert "Package: ${DEB_PACKAGE_NAME}\n" in script
    from scripts.ci.release_assets import DEB_PATTERN

    assert DEB_PATTERN.fullmatch("personal-jarvis_3.0.0_amd64.deb")
    assert DEB_PATTERN.fullmatch("dodaios_3.0.0_amd64.deb")

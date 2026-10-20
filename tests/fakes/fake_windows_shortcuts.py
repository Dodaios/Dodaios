"""Hand-built stand-in for the Windows shell shortcuts the app writes and reads.

Per AGENTS.md the project uses real fakes, never ``unittest.mock``. A real
``.lnk`` needs ``WScript.Shell`` and lands where the shell indexes it; this
fake writes a plain file whose only content is the target path, so a test can
lay out a Start menu and a Desktop in ``tmp_path`` (earlier-named shortcuts of
this install, of another install, unreadable ones) and see what the code under
test writes, reads and removes.

:meth:`FakeShortcuts.install` replaces the ``dodaios.ui.icon_utils`` writers
``dodaios.setup.desktop_integration`` calls, plus its Installed Apps registry
writer, so nothing reaches the real shell or registry.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class FakeShortcuts:
    """Shortcut files keyed by path; each one names the program it starts."""

    def __init__(self, *, launch_target: Path, shortcut_name: str) -> None:
        self.launch_target = launch_target
        self.shortcut_name = shortcut_name
        self.written: list[Path] = []
        self.read: list[Path] = []
        self.unreadable: set[Path] = set()

    @staticmethod
    def place(lnk: Path, target: Path | str) -> Path:
        """Put a shortcut at ``lnk`` that starts ``target`` (an earlier release's)."""
        lnk.parent.mkdir(parents=True, exist_ok=True)
        lnk.write_text(str(target), encoding="utf-8")
        return lnk

    def read_target(self, lnk: Path) -> str | None:
        self.read.append(lnk)
        if lnk in self.unreadable:
            return None
        return lnk.read_text(encoding="utf-8")

    def _write(self, directory: Path | None) -> bool:
        if directory is None:
            return False
        lnk = self.place(directory / self.shortcut_name, self.launch_target)
        self.written.append(lnk)
        return True

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dodaios.setup import desktop_integration
        from dodaios.ui import icon_utils

        def ensure_start_menu_shortcut(*, programs_dir: Path | None = None, **_kw: object) -> bool:
            return self._write(programs_dir)

        def ensure_desktop_shortcut(*, desktop_dir: Path | None = None, **_kw: object) -> bool:
            return self._write(desktop_dir)

        monkeypatch.setattr(icon_utils, "ensure_start_menu_shortcut", ensure_start_menu_shortcut)
        monkeypatch.setattr(icon_utils, "ensure_desktop_shortcut", ensure_desktop_shortcut)
        monkeypatch.setattr(
            icon_utils, "register_windows_app_user_model_id", lambda *_a, **_kw: True
        )
        monkeypatch.setattr(
            desktop_integration, "register_windows_installed_app", lambda *_a, **_kw: True
        )

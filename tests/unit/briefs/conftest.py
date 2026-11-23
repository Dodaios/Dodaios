"""A small project on disk for the brief pipeline's tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A folder with a few source files, an instruction file and a manifest."""
    root = tmp_path / "notes-app"
    (root / "sync").mkdir(parents=True)
    (root / "ui" / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "scripts").mkdir()
    (root / "scripts" / "done_gate.py").write_text("print('DONE')\n", encoding="utf-8")
    (root / "sync" / "client.py").write_text(
        "class UploadError(Exception):\n    pass\n\n\n"
        "def upload(note):\n    # the upload times out on a slow connection\n"
        "    raise UploadError('timed out after 10s')\n",
        encoding="utf-8",
    )
    (root / "ui" / "src" / "ReminderRail.tsx").write_text(
        "export function ReminderRail() {\n  // the reminder items in the left rail\n"
        "  return null;\n}\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_sync.py").write_text("def test_upload():\n    assert True\n", "utf-8")
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "You are done when `python scripts/done_gate.py` says DONE.\n", encoding="utf-8"
    )
    (root / "ui" / "package.json").write_text(
        '{"scripts": {"test": "vitest run", "typecheck": "tsc -b"}}', encoding="utf-8"
    )
    return root

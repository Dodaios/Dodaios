"""Issue #1057: an install without its UI build must not say "Updating" forever.

The holding page covers the few seconds a rebuild leaves ``dist/`` incomplete.
When the build is simply not installed, the same page used to poll forever and
nothing was logged. Now a build missing at startup, or for longer than the
normal rebuild window, gets one WARNING with the path and a page that says the
UI build is missing and how to get one.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from dodaios.ui.web import spa_build
from dodaios.ui.web.spa_build import (
    HOLDING_ATTRIBUTE,
    MISSING_BUILD_GRACE_S,
    MissingBuildWatch,
    holding_page_html,
)


@pytest.fixture(autouse=True)
def _fresh_global_watch(monkeypatch: pytest.MonkeyPatch) -> MissingBuildWatch:
    watch = MissingBuildWatch()
    monkeypatch.setattr(spa_build, "missing_build_watch", watch)
    from dodaios.ui.web import server as server_mod

    monkeypatch.setattr(server_mod, "missing_build_watch", watch)
    return watch


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "UI build missing" in r.getMessage()
    ]


class TestTheWatch:
    def test_a_short_rebuild_stays_quiet(self, tmp_path: Path, caplog) -> None:
        watch = MissingBuildWatch()
        index = tmp_path / "index.html"
        assert watch.observe(index, now=100.0) is False
        assert watch.observe(index, now=100.0 + MISSING_BUILD_GRACE_S - 1) is False
        assert _warnings(caplog) == []

    def test_a_build_missing_beyond_the_window_warns_once(
        self, tmp_path: Path, caplog
    ) -> None:
        watch = MissingBuildWatch()
        index = tmp_path / "dist" / "index.html"
        watch.observe(index, now=0.0)
        assert watch.observe(index, now=MISSING_BUILD_GRACE_S + 1) is True
        assert watch.observe(index, now=MISSING_BUILD_GRACE_S + 50) is True
        warnings = _warnings(caplog)
        assert len(warnings) == 1
        assert str(index) in warnings[0].getMessage()
        assert "npm run build" in warnings[0].getMessage()

    def test_a_build_missing_at_startup_is_reported_at_once(
        self, tmp_path: Path, caplog
    ) -> None:
        watch = MissingBuildWatch()
        index = tmp_path / "index.html"
        assert watch.note_startup(index, now=0.0) is True
        assert watch.observe(index, now=0.5) is True
        assert len(_warnings(caplog)) == 1

    def test_a_present_build_at_startup_is_not_reported(
        self, tmp_path: Path, caplog
    ) -> None:
        index = tmp_path / "index.html"
        index.write_text("<!doctype html>", encoding="utf-8")
        watch = MissingBuildWatch()
        assert watch.note_startup(index) is False
        assert watch.observe(index, now=1.0) is False
        assert _warnings(caplog) == []

    def test_a_complete_build_resets_the_watch(self, tmp_path: Path) -> None:
        watch = MissingBuildWatch()
        index = tmp_path / "index.html"
        watch.note_startup(index, now=0.0)
        watch.clear()
        assert watch.observe(index, now=1_000.0) is False


class TestThePage:
    def test_the_default_page_still_says_updating(self) -> None:
        page = holding_page_html()
        assert "Updating" in page
        assert "UI build missing" not in page

    def test_the_missing_build_page_is_actionable_and_keeps_polling(self) -> None:
        page = holding_page_html(build_missing=True)
        assert "UI build missing" in page
        assert "Updating" not in page
        assert "Reinstall the app" in page
        assert "npm run build" in page
        # Still the holding page, so a build that lands takes over by itself.
        assert HOLDING_ATTRIBUTE in page
        assert "location.reload()" in page
        assert "Jarvis" not in page


class TestTheServerRoute:
    @staticmethod
    def _response(monkeypatch: pytest.MonkeyPatch, dist: Path):
        from dodaios.ui.web import server as server_mod

        monkeypatch.setattr(server_mod, "DIST_DIR", dist)
        monkeypatch.setattr(server_mod, "INDEX_FILE", dist / "index.html")
        return server_mod.WebServer._spa_index_response(server_mod.WebServer)

    def test_missing_at_startup_serves_the_missing_build_page(
        self, tmp_path: Path, monkeypatch, caplog, _fresh_global_watch
    ) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        _fresh_global_watch.note_startup(dist / "index.html")
        body = self._response(monkeypatch, dist).body
        assert b"UI build missing" in body
        assert len(_warnings(caplog)) == 1

    def test_a_fresh_gap_still_says_updating(
        self, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        body = self._response(monkeypatch, dist).body
        assert b"Updating" in body
        assert _warnings(caplog) == []

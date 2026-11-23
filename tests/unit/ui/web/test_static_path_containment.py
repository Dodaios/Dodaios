"""The credential-free file routes never touch a path outside the build.

``GET`` of any path that is not an API path needs no credential, and both
servers of such paths (the boot-time holding app and the real app's SPA
catch-all) used to join the request path onto the build folder and ask the
filesystem about the result before checking where it pointed. A request path
with a leading slash, a backslash or a drive letter makes that join an
absolute path; on Windows it can be a network path, which the system contacts
with the user's login just to answer whether it is a file. Any page the user
has open can make the browser send such a request.

The name is now refused before any filesystem call.
"""
from __future__ import annotations

import pathlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.ui.web import fast_bootstrap
from dodaios.ui.web.fast_bootstrap import FastBootstrap, dist_file

_OUTSIDE_NAMES = [
    "//files.example/share/logo.png",
    "/files.example/share/logo.png",
    "\\\\files.example\\share\\logo.png",
    "\\files.example\\share\\logo.png",
    "sub\\..\\..\\secret.txt",
    "C:/Windows/win.ini",
    "C:secret.txt",
    "assets/app.js:stream",
    "nul\x00.png",
    "",
]


@pytest.fixture
def touched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every path the code under test asks the filesystem about."""
    seen: list[str] = []
    real_resolve = pathlib.Path.resolve
    real_is_file = pathlib.Path.is_file

    def resolve(self: Path, *args: object, **kwargs: object) -> Path:
        seen.append(str(self))
        return real_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    def is_file(self: Path, *args: object, **kwargs: object) -> bool:
        seen.append(str(self))
        return real_is_file(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pathlib.Path, "resolve", resolve)
    monkeypatch.setattr(pathlib.Path, "is_file", is_file)
    return seen


def _outside(paths: list[str], root: Path) -> list[str]:
    inside = str(root)
    return [p for p in paths if p != inside and not p.startswith(inside)]


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = (tmp_path / "dist").resolve()
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("private", encoding="utf-8")
    return root


@pytest.mark.parametrize("name", _OUTSIDE_NAMES)
def test_outside_name_is_refused_before_the_filesystem_is_asked(
    dist: Path, touched: list[str], name: str
) -> None:
    assert dist_file(dist, name) is None
    assert touched == []


def test_parent_walk_is_refused_after_resolving(dist: Path) -> None:
    assert dist_file(dist, "../secret.txt") is None
    assert dist_file(dist, "assets/../../secret.txt") is None


def test_real_build_file_is_served(dist: Path) -> None:
    assert dist_file(dist, "assets/app.js") == dist / "assets" / "app.js"
    assert dist_file(dist, "index.html") == dist / "index.html"
    assert dist_file(dist, "assets/missing.js") is None


@pytest.mark.parametrize(
    "request_path",
    [
        "/%5C%5Cfiles.example%5Cshare%5Clogo.png",
        "///files.example/share/logo.png",
        "/C:/Windows/win.ini",
    ],
)
def test_boot_time_server_never_asks_about_an_outside_path(
    dist: Path, touched: list[str], request_path: str
) -> None:
    bootstrap = FastBootstrap(dist_dir=dist)
    decoded = request_path.replace("%5C", "\\")

    served = bootstrap._resolve_static_file(decoded)

    assert served in (None, dist / "index.html")
    assert _outside(touched, dist) == []


@pytest.mark.parametrize(
    "request_path",
    [
        "/%5C%5Cfiles.example%5Cshare%5Clogo.png",
        "///files.example/share/logo.png",
        "/C:/Windows/win.ini",
    ],
)
def test_app_catch_all_never_asks_about_an_outside_path(
    dist: Path, monkeypatch: pytest.MonkeyPatch, request_path: str
) -> None:
    from dodaios.ui.web import server as server_module

    monkeypatch.setattr(server_module, "DIST_DIR", dist)
    asked: list[tuple[Path, str]] = []
    real = fast_bootstrap.dist_file

    def spy(root: Path, rel: str) -> Path | None:
        asked.append((root, rel))
        return real(root, rel)

    monkeypatch.setattr(server_module, "dist_file", spy)
    cfg = JarvisConfig()
    cfg.ui.dev_mode = False  # the SPA catch-all exists only in production mode
    client = TestClient(server_module.WebServer(cfg, bus=EventBus()).app)

    response = client.get(request_path)

    assert response.status_code in (200, 404)
    assert "private" not in response.text
    assert asked, "the catch-all must resolve files through dist_file"
    for root, rel in asked:
        assert real(root, rel) is None

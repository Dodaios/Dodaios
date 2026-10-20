"""Route + guard tests for the in-app updater (jarvis/ui/web/update_routes.py).

Covers the safety-critical contract: an unmanaged checkout (dev tree / manual
clone) never sees an update and can never be self-reset, version comparison is
fail-closed on an unknown running version, and the network check is fail-open.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import jarvis.ui.web.update_routes as u
from jarvis.ui.web.update_routes import router as update_router


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    # The status + release caches are module-global; clear them so each test
    # sees a fresh check.
    u._status_cache = None
    u._status_cache_until = 0.0
    u._status_cache_root = None
    u._last_good_release = None


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(update_router)
    return TestClient(app)


def _patch_managed(monkeypatch: pytest.MonkeyPatch, root: Path | None) -> None:
    async def _fake() -> Path | None:
        return root

    monkeypatch.setattr(u, "_resolve_managed_repo", _fake)


def _patch_latest(monkeypatch: pytest.MonkeyPatch, result: dict | None) -> None:
    async def _fake() -> dict | None:
        return result

    monkeypatch.setattr(u, "_fetch_latest_release", _fake)


# --------------------------------------------------------------------------- #
# Version comparison + remote normalization
# --------------------------------------------------------------------------- #
def test_is_newer_basic() -> None:
    assert u._is_newer("1.0.2", "1.0.1")
    assert u._is_newer("2.0.0", "1.9.9")
    assert not u._is_newer("1.0.1", "1.0.1")
    assert not u._is_newer("1.0.0", "1.0.1")


def test_is_newer_fail_closed_on_unknown() -> None:
    # If we can't tell what we're running, never offer an update.
    assert not u._is_newer("1.0.2", "unknown")
    assert not u._is_newer("1.0.2", "")
    assert not u._is_newer("", "1.0.1")


def test_versions_equal_is_normalized_and_fail_closed() -> None:
    assert u._versions_equal("1.0.2", "1.0.2")
    assert u._versions_equal("1.0.2", "1.0.2+build.1") is False
    assert not u._versions_equal("invalid", "invalid")


def test_remote_is_official_accepts_current_and_legacy_repo() -> None:
    # https, ssh, and a local path on either slash style all resolve.
    assert u._remote_is_official("https://github.com/Dodaios/Dodaios.git")
    assert u._remote_is_official("git@github.com:Dodaios/Dodaios.git")
    assert u._remote_is_official("C:\\x\\Dodaios\\Dodaios")
    # A checkout cloned before the rename is still this repository.
    assert u._remote_is_official("https://github.com/PersonalJarvis/PersonalJarvis.git")
    assert u._remote_is_official("git@github.com:PersonalJarvis/PersonalJarvis.git")
    # A different repo is rejected...
    assert not u._remote_is_official("https://github.com/someone/fork.git")
    # ...and so is a look-alike fork whose name merely starts with the slug...
    assert not u._remote_is_official("https://github.com/Dodaios/DodaiosEvil.git")
    assert not u._remote_is_official(
        "https://github.com/PersonalJarvis/PersonalJarvisEvil.git"
    )
    # ...or one under a different owner with the right repo name.
    assert not u._remote_is_official("https://github.com/evil/Dodaios.git")


def test_remote_override_still_rejects_lookalike_repos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(u, "_OFFICIAL_REPO_SLUG", "RenamedOrg/RenamedRepo")
    assert u._remote_is_official("https://github.com/RenamedOrg/RenamedRepo.git")
    assert not u._remote_is_official(
        "https://github.com/RenamedOrg/RenamedRepoEvil.git"
    )
    assert not u._remote_is_official("https://github.com/evil/RenamedRepo.git")
    assert not u._remote_is_official(
        "https://github.com/Dodaios/Dodaios.git"
    )


# --------------------------------------------------------------------------- #
# GET /api/update/status
# --------------------------------------------------------------------------- #
def test_status_unmanaged_hides_button(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_managed(monkeypatch, None)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    body = client.get("/api/update/status").json()
    assert body["managed"] is False
    assert body["update_available"] is False


def test_status_newer_available(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(
        monkeypatch,
        {
            "version": "1.0.2",
            "notes": "New stuff",
            "published_at": "2026-07-03T00:00:00Z",
            "release_url": "https://example/releases/v1.0.2",
        },
    )
    body = client.get("/api/update/status").json()
    assert body["managed"] is True
    assert body["update_available"] is True
    assert body["latest"] == "1.0.2"
    assert body["notes"] == "New stuff"


def test_status_same_version_no_update(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.2")
    _patch_latest(
        monkeypatch,
        {"version": "1.0.2", "notes": "", "published_at": None, "release_url": None},
    )
    body = client.get("/api/update/status").json()
    assert body["managed"] is True
    assert body["update_available"] is False
    assert body["notes"] is None


def test_status_network_error_is_fail_open(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, None)  # GitHub unreachable
    body = client.get("/api/update/status").json()
    assert body["managed"] is True
    assert body["update_available"] is False
    assert body.get("check_failed") is True


# --------------------------------------------------------------------------- #
# POST /api/update/apply
# --------------------------------------------------------------------------- #
def test_apply_refuses_unmanaged_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_managed(monkeypatch, None)
    # Even a spoofed client can never trigger a self-reset on a dev tree.
    assert client.post("/api/update/apply").status_code == 403


def test_apply_happy_path_pulls_and_signals_restart(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    (tmp_path / ".jarvis-managed-install").write_text(
        '{"profile": "full"}\n', encoding="utf-8"
    )
    sentinel = tmp_path / "running-checkout.txt"
    sentinel.write_text("old", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(
        monkeypatch,
        {
            "version": "1.0.2",
            "tag": "v1.0.2",
            "notes": "",
            "published_at": None,
            "release_url": None,
        },
    )

    async def _fake_git(args, *, cwd, timeout_s=60.0, on_stderr_line=None):
        calls.append(args)
        return 0, "", ""

    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        calls.append(args)
        if args == ["rev-parse", "HEAD"]:
            return "a" * 40
        if args == ["rev-parse", "FETCH_HEAD^{commit}"]:
            return "b" * 40
        if args == ["show", f"{'b' * 40}:jarvis/__init__.py"]:
            return '__version__ = "1.0.2"'
        return None

    monkeypatch.setattr(u, "_git", _fake_git)
    monkeypatch.setattr(u, "_git_output", _fake_git_output)
    body = client.post("/api/update/apply").json()
    assert body["ok"] is True
    assert body["prepared"] is True
    assert body["restart_required"] is True
    assert body["version"] == "1.0.2"
    assert body["release_tag"] == "v1.0.2"
    assert body["deps_pending"] is True
    assert body["ui_bundle_pending"] is True
    assert body["desktop_integration_pending"] is True
    assert body["desktop_integration_ok"] is None
    assert body["desktop_integration_warning"] is None
    # ``--progress`` makes git report object counters through a pipe, which
    # is what drives the download phase of the progress bar.
    assert [
        "fetch",
        "--progress",
        "--depth",
        "1",
        "origin",
        "refs/tags/v1.0.2",
    ] in calls
    assert not any(call[:2] == ["reset", "--hard"] for call in calls)
    assert not any(call[:2] == ["remote", "set-url"] for call in calls)
    assert sentinel.read_text(encoding="utf-8") == "old"

    pending = json.loads(
        (tmp_path / u._PENDING_UPDATE_NAME).read_text(encoding="utf-8")
    )
    assert pending["previous_revision"] == "a" * 40
    assert pending["target_revision"] == "b" * 40
    assert pending["profile"] == "full"


def test_apply_rewrites_legacy_origin_before_fetch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, {"version": "1.0.2", "tag": "v1.0.2"})
    calls: list[list[str]] = []

    async def _fake_git(args, *, cwd, timeout_s=60.0, on_stderr_line=None):
        calls.append(args)
        return 0, "", ""

    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        calls.append(args)
        if args == ["remote", "get-url", "origin"]:
            return "https://github.com/PersonalJarvis/PersonalJarvis.git"
        if args == ["rev-parse", "HEAD"]:
            return "a" * 40
        if args == ["rev-parse", "FETCH_HEAD^{commit}"]:
            return "b" * 40
        if args == ["show", f"{'b' * 40}:jarvis/__init__.py"]:
            return '__version__ = "1.0.2"'
        return None

    monkeypatch.setattr(u, "_git", _fake_git)
    monkeypatch.setattr(u, "_git_output", _fake_git_output)
    body = client.post("/api/update/apply").json()
    assert body["ok"] is True
    rewrite = ["remote", "set-url", "origin", u.OFFICIAL_REPO_GIT_URL]
    fetch = ["fetch", "--progress", "--depth", "1", "origin", "refs/tags/v1.0.2"]
    assert rewrite in calls
    assert calls.index(rewrite) < calls.index(fetch)


def test_apply_leaves_current_origin_untouched(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, {"version": "1.0.2", "tag": "v1.0.2"})
    calls: list[list[str]] = []

    async def _fake_git(args, *, cwd, timeout_s=60.0, on_stderr_line=None):
        calls.append(args)
        return 0, "", ""

    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        calls.append(args)
        if args == ["remote", "get-url", "origin"]:
            return "https://github.com/Dodaios/Dodaios.git"
        if args == ["rev-parse", "HEAD"]:
            return "a" * 40
        if args == ["rev-parse", "FETCH_HEAD^{commit}"]:
            return "b" * 40
        if args == ["show", f"{'b' * 40}:jarvis/__init__.py"]:
            return '__version__ = "1.0.2"'
        return None

    monkeypatch.setattr(u, "_git", _fake_git)
    monkeypatch.setattr(u, "_git_output", _fake_git_output)
    assert client.post("/api/update/apply").json()["ok"] is True
    assert not any(call[:2] == ["remote", "set-url"] for call in calls)


def test_apply_fails_when_legacy_origin_cannot_be_rewritten(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, {"version": "1.0.2", "tag": "v1.0.2"})

    async def _fake_git(args, *, cwd, timeout_s=60.0, on_stderr_line=None):
        if args[:2] == ["remote", "set-url"]:
            return 1, "", "denied"
        return 0, "", ""

    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        if args == ["remote", "get-url", "origin"]:
            return "git@github.com:PersonalJarvis/PersonalJarvis.git"
        if args == ["rev-parse", "HEAD"]:
            return "a" * 40
        return None

    monkeypatch.setattr(u, "_git", _fake_git)
    monkeypatch.setattr(u, "_git_output", _fake_git_output)
    response = client.post("/api/update/apply")
    assert response.status_code == 500
    assert not (tmp_path / u._PENDING_UPDATE_NAME).exists()


def test_apply_git_fetch_failure_is_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, {"version": "1.0.2", "tag": "v1.0.2"})

    async def _fake_git(args, *, cwd, timeout_s=60.0, on_stderr_line=None):
        return 1, "", "network down"

    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        return "a" * 40

    monkeypatch.setattr(u, "_git", _fake_git)
    monkeypatch.setattr(u, "_git_output", _fake_git_output)
    assert client.post("/api/update/apply").status_code == 502


def test_apply_preserves_headless_profile_for_deferred_installer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    (tmp_path / ".jarvis-managed-install").write_text(
        '{"profile": "headless"}\n', encoding="utf-8"
    )
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, {"version": "1.0.2", "tag": "v1.0.2"})

    async def _fake_git(args, *, cwd, timeout_s=60.0, on_stderr_line=None):
        return 0, "", ""

    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        if args == ["rev-parse", "HEAD"]:
            return "1" * 40
        if args == ["rev-parse", "FETCH_HEAD^{commit}"]:
            return "2" * 40
        if args == ["show", f"{'2' * 40}:jarvis/__init__.py"]:
            return '__version__ = "1.0.2"'
        return None

    monkeypatch.setattr(u, "_git", _fake_git)
    monkeypatch.setattr(u, "_git_output", _fake_git_output)
    body = client.post("/api/update/apply").json()
    assert body["install_profile"] == "headless"
    assert body["desktop_integration_pending"] is False
    pending = json.loads(
        (tmp_path / u._PENDING_UPDATE_NAME).read_text(encoding="utf-8")
    )
    assert pending["profile"] == "headless"


def test_apply_refuses_when_no_new_release(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.2")
    _patch_latest(monkeypatch, {"version": "1.0.2", "tag": "v1.0.2"})

    response = client.post("/api/update/apply")

    assert response.status_code == 409
    assert not (tmp_path / u._PENDING_UPDATE_NAME).exists()


def _write_manifest(root: Path, target: str = "b" * 40) -> None:
    (root / u._PENDING_UPDATE_NAME).write_text(
        json.dumps(
            {
                "schema": 1,
                "previous_revision": "a" * 40,
                "target_revision": target,
                "profile": "full",
                "created_at": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _patch_git_show_version(
    monkeypatch: pytest.MonkeyPatch, revision: str, version: str
) -> None:
    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        if args == ["show", f"{revision}:jarvis/__init__.py"]:
            return f'__version__ = "{version}"'
        return None

    monkeypatch.setattr(u, "_git_output", _fake_git_output)


def test_apply_falls_back_to_cached_release_when_refetch_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The status check succeeded earlier; the click-time refetch hits the
    # shared-IP rate limit. The cached answer must keep the update working.
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, None)
    u._last_good_release = {"version": "1.0.2", "tag": "v1.0.2"}

    async def _fake_git(args, *, cwd, timeout_s=60.0, on_stderr_line=None):
        return 0, "", ""

    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        if args == ["rev-parse", "HEAD"]:
            return "a" * 40
        if args == ["rev-parse", "FETCH_HEAD^{commit}"]:
            return "b" * 40
        if args == ["show", f"{'b' * 40}:jarvis/__init__.py"]:
            return '__version__ = "1.0.2"'
        return None

    monkeypatch.setattr(u, "_git", _fake_git)
    monkeypatch.setattr(u, "_git_output", _fake_git_output)
    body = client.post("/api/update/apply").json()
    assert body["ok"] is True
    assert body["version"] == "1.0.2"


def test_apply_offline_reuses_staged_manifest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # GitHub fully unreachable, nothing cached — but an earlier click already
    # staged a validated transaction. Re-offering it lets the restart finish
    # the update offline instead of failing with a 502.
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, None)
    _write_manifest(tmp_path)
    _patch_git_show_version(monkeypatch, "b" * 40, "1.0.2")

    body = client.post("/api/update/apply").json()
    assert body["ok"] is True
    assert body["prepared"] is True
    assert body["version"] == "1.0.2"
    assert body["release_tag"] == "v1.0.2"


def test_apply_offline_without_staged_manifest_is_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, None)

    response = client.post("/api/update/apply")
    assert response.status_code == 502
    assert "GitHub" in response.json()["detail"]


def test_apply_offline_ignores_stale_manifest_for_older_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A leftover manifest whose target is NOT newer than the running version
    # (e.g. the update already installed) must not be re-offered.
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.2")
    _patch_latest(monkeypatch, None)
    _write_manifest(tmp_path)
    _patch_git_show_version(monkeypatch, "b" * 40, "1.0.2")

    assert client.post("/api/update/apply").status_code == 502


def test_status_reports_pending_update_and_last_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(
        monkeypatch,
        {"version": "1.0.2", "notes": "", "published_at": None, "release_url": None},
    )
    _write_manifest(tmp_path)
    _patch_git_show_version(monkeypatch, "b" * 40, "1.0.2")
    (tmp_path / u._UPDATE_RESULT_NAME).write_text(
        '{"ok": false, "rolled_back": true, "completed_at": 123}\n',
        encoding="utf-8",
    )

    body = client.get("/api/update/status").json()
    assert body["pending_update"] == {
        "version": "1.0.2",
        "target_revision": "b" * 40,
    }
    assert body["last_result"] == {
        "ok": False,
        "rolled_back": True,
        "completed_at": 123,
    }


def test_status_hides_stale_manifest_for_non_newer_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A manifest surviving a crashed finalize (the checkout already ON the
    # target) must not render a "Finish update" offer for the running version —
    # the status overlay honors the same never-offer-non-newer rule as apply.
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.2")
    _patch_latest(
        monkeypatch,
        {"version": "1.0.2", "notes": "", "published_at": None, "release_url": None},
    )
    _write_manifest(tmp_path)
    _patch_git_show_version(monkeypatch, "b" * 40, "1.0.2")

    body = client.get("/api/update/status").json()
    assert body["update_available"] is False
    assert body["pending_update"] is None


def test_status_cache_hit_still_reports_fresh_pending_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The network result is cached for 30 min, but a transaction staged in the
    # meantime (or a relauncher verdict) must show up on the very next poll.
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(
        monkeypatch,
        {"version": "1.0.2", "notes": "", "published_at": None, "release_url": None},
    )
    first = client.get("/api/update/status").json()
    assert first["pending_update"] is None

    _write_manifest(tmp_path)
    _patch_git_show_version(monkeypatch, "b" * 40, "1.0.2")
    second = client.get("/api/update/status").json()
    assert second["pending_update"] == {
        "version": "1.0.2",
        "target_revision": "b" * 40,
    }


def test_apply_invalidates_status_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(
        monkeypatch,
        {"version": "1.0.2", "tag": "v1.0.2", "notes": "", "published_at": None},
    )
    client.get("/api/update/status")
    assert u._status_cache is not None

    async def _fake_git(args, *, cwd, timeout_s=60.0, on_stderr_line=None):
        return 0, "", ""

    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        if args == ["rev-parse", "HEAD"]:
            return "a" * 40
        if args == ["rev-parse", "FETCH_HEAD^{commit}"]:
            return "b" * 40
        if args == ["show", f"{'b' * 40}:jarvis/__init__.py"]:
            return '__version__ = "1.0.2"'
        return None

    monkeypatch.setattr(u, "_git", _fake_git)
    monkeypatch.setattr(u, "_git_output", _fake_git_output)
    assert client.post("/api/update/apply").json()["ok"] is True
    assert u._status_cache is None


def test_pending_update_write_replaces_old_result(tmp_path: Path) -> None:
    result = tmp_path / u._UPDATE_RESULT_NAME
    result.write_text('{"ok": false}\n', encoding="utf-8")

    u._write_pending_update(
        tmp_path,
        previous_revision="a" * 40,
        target_revision="b" * 40,
        profile="full",
    )

    assert not result.exists()
    assert not (tmp_path / f"{u._PENDING_UPDATE_NAME}.tmp").exists()
    payload = json.loads(
        (tmp_path / u._PENDING_UPDATE_NAME).read_text(encoding="utf-8")
    )
    assert payload["schema"] == 1


def test_legacy_marker_falls_back_to_desktop_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".jarvis-managed-install").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(u.sys, "platform", "win32")
    assert u._managed_install_profile(tmp_path) == "full"


def test_legacy_linux_marker_distinguishes_desktop_from_headless(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".jarvis-managed-install").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(u.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert u._managed_install_profile(tmp_path) == "headless"

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert u._managed_install_profile(tmp_path) == "full"


# --------------------------------------------------------------------------- #
# Release check across the repository rename
# --------------------------------------------------------------------------- #
def _serve_release_api(monkeypatch: pytest.MonkeyPatch, handler) -> list[str]:
    """Route the updater's real httpx client through an in-process transport."""
    import httpx

    seen: list[str] = []

    def _recording(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    real_client = httpx.AsyncClient

    def _client(**kwargs):
        return real_client(transport=httpx.MockTransport(_recording), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    return seen


async def test_release_check_follows_a_renamed_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    moved = "https://api.github.com/repositories/1255092568/releases/latest"

    def _handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == u._RELEASES_LATEST_API:
            return httpx.Response(301, headers={"location": moved})
        assert str(request.url) == moved
        return httpx.Response(200, json={"tag_name": "v9.9.9", "assets": []})

    seen = _serve_release_api(monkeypatch, _handler)
    release = await u._fetch_latest_release()
    assert release is not None and release["version"] == "9.9.9"
    assert seen == [u._RELEASES_LATEST_API, moved]


@pytest.mark.parametrize(
    "location",
    [
        "https://example.invalid/repos/Dodaios/Dodaios/releases/latest",
        "http://api.github.com/repositories/1/releases/latest",
    ],
)
async def test_release_check_refuses_a_redirect_off_the_github_api(
    monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == u._RELEASES_LATEST_API:
            return httpx.Response(301, headers={"location": location})
        return httpx.Response(200, json={"tag_name": "v9.9.9", "assets": []})

    seen = _serve_release_api(monkeypatch, _handler)
    assert await u._fetch_latest_release() is None
    assert seen == [u._RELEASES_LATEST_API]
    assert u._last_good_release is None


# --------------------------------------------------------------------------- #
# The version is read where the TARGET revision says it lives
# --------------------------------------------------------------------------- #
def _patch_git_show(
    monkeypatch: pytest.MonkeyPatch, files: dict[str, str]
) -> list[list[str]]:
    """Serve ``git show <rev>:<path>`` from ``files``; record every question."""
    asked: list[list[str]] = []

    async def _fake_git_output(args, *, cwd, timeout_s=15.0):
        asked.append(args)
        if args == ["rev-parse", "HEAD"]:
            return "a" * 40
        if args == ["rev-parse", "FETCH_HEAD^{commit}"]:
            return "b" * 40
        if args[0] == "show":
            return files.get(args[1])
        return None

    async def _fake_git(args, *, cwd, timeout_s=60.0, on_stderr_line=None):
        asked.append(args)
        return 0, "", ""

    monkeypatch.setattr(u, "_git", _fake_git)
    monkeypatch.setattr(u, "_git_output", _fake_git_output)
    return asked


def _moved_contract(**overrides: object) -> str:
    return json.dumps({"schema": 1, "version_file": "newpkg/__init__.py", **overrides})


async def test_version_at_revision_follows_the_targets_update_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "c" * 40
    asked = _patch_git_show(
        monkeypatch,
        {
            f"{revision}:install/update-contract.json": _moved_contract(),
            f"{revision}:newpkg/__init__.py": '__version__ = "3.0.0"',
        },
    )

    assert await u._version_at_revision(tmp_path, revision) == "3.0.0"
    # The package moved: its old location is not even looked at.
    assert ["show", f"{revision}:jarvis/__init__.py"] not in asked


async def test_version_at_revision_without_a_contract_reads_the_default_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "c" * 40
    asked = _patch_git_show(
        monkeypatch, {f"{revision}:jarvis/__init__.py": '__version__ = "2.9.9"'}
    )

    assert await u._version_at_revision(tmp_path, revision) == "2.9.9"
    assert asked[0] == ["show", f"{revision}:install/update-contract.json"]


@pytest.mark.parametrize(
    "contract",
    [
        "not json",
        json.dumps({"schema": 99, "version_file": "newpkg/__init__.py"}),
        json.dumps({"schema": 1, "version_file": "../../outside/__init__.py"}),
        json.dumps({"schema": 1, "version_file": "/etc/passwd"}),
    ],
)
async def test_version_at_revision_never_follows_a_contract_it_cannot_trust(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, contract: str
) -> None:
    revision = "c" * 40
    asked = _patch_git_show(
        monkeypatch,
        {
            f"{revision}:install/update-contract.json": contract,
            f"{revision}:newpkg/__init__.py": '__version__ = "6.6.6"',
            f"{revision}:jarvis/__init__.py": '__version__ = "2.9.9"',
        },
    )

    assert await u._version_at_revision(tmp_path, revision) == "2.9.9"
    shown = [args[1].split(":", 1)[1] for args in asked if args[0] == "show"]
    assert shown == ["install/update-contract.json", "jarvis/__init__.py"]


async def test_version_at_revision_still_falls_back_to_pyproject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "c" * 40
    _patch_git_show(
        monkeypatch,
        {
            f"{revision}:install/update-contract.json": _moved_contract(),
            f"{revision}:pyproject.toml": '[project]\nversion = "3.1.0"\n',
        },
    )
    assert await u._version_at_revision(tmp_path, revision) == "3.1.0"


def _stage_moved_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, tree_version: str
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    (tmp_path / ".jarvis-managed-install").write_text('{"profile": "full"}\n', encoding="utf-8")
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, {"version": "1.0.2", "tag": "v1.0.2"})
    _patch_git_show(
        monkeypatch,
        {
            f"{'b' * 40}:install/update-contract.json": _moved_contract(),
            f"{'b' * 40}:newpkg/__init__.py": f'__version__ = "{tree_version}"',
        },
    )


def test_apply_stages_a_release_that_moved_its_version_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stage_moved_release(monkeypatch, tmp_path, tree_version="1.0.2")

    body = client.post("/api/update/apply").json()

    assert body["ok"] is True
    assert body["version"] == "1.0.2"
    pending = json.loads((tmp_path / u._PENDING_UPDATE_NAME).read_text(encoding="utf-8"))
    assert pending["target_revision"] == "b" * 40


def test_apply_still_refuses_a_moved_release_whose_version_disagrees(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The safety property survives the move: tag bytes must match the release."""
    _stage_moved_release(monkeypatch, tmp_path, tree_version="1.0.3")

    response = client.post("/api/update/apply")

    assert response.status_code == 502
    assert not (tmp_path / u._PENDING_UPDATE_NAME).exists()


def test_apply_refuses_a_moved_release_whose_version_cannot_be_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_managed(monkeypatch, tmp_path)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    _patch_latest(monkeypatch, {"version": "1.0.2", "tag": "v1.0.2"})
    # The contract names a version file the revision does not contain.
    _patch_git_show(
        monkeypatch, {f"{'b' * 40}:install/update-contract.json": _moved_contract()}
    )

    assert client.post("/api/update/apply").status_code == 502
    assert not (tmp_path / u._PENDING_UPDATE_NAME).exists()


def test_version_on_disk_follows_the_checked_out_contract(tmp_path: Path) -> None:
    (tmp_path / "jarvis").mkdir()
    (tmp_path / "jarvis" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    assert u._version_on_disk(tmp_path) == "1.0.0"

    (tmp_path / "newpkg").mkdir()
    (tmp_path / "newpkg" / "__init__.py").write_text('__version__ = "2.0.0"\n', encoding="utf-8")
    (tmp_path / "install").mkdir()
    (tmp_path / "install" / "update-contract.json").write_text(
        _moved_contract(), encoding="utf-8"
    )
    assert u._version_on_disk(tmp_path) == "2.0.0"

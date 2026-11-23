"""Integration test: the updater's real git operations against a local repo.

A real bare upstream and installed clone prove that the managed guard requires
the marker plus official-slug origin, and that apply fetches the exact published
tag without mutating the running checkout. Only the release-API edge is mocked:
the release metadata and the two small documents that state its signed commit,
which a throwaway key signs for real.
"""
from __future__ import annotations

import asyncio
import base64
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException

import dodaios.ui.web.update_routes as u
from dodaios.core.branding import DEFAULT_OFFICIAL_REPO_SLUG
from dodaios.core.release_commit import (
    PAYLOAD_COMMIT_ASSET_NAME,
    PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME,
)
from tests.fakes.fake_installer_update import FakeAssetFetcher

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _git_output(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_upstream_and_install(tmp_path: Path) -> tuple[Path, Path, Path]:
    # The upstream path deliberately contains the official slug so the real
    # origin-URL guard passes against a purely local remote.
    owner, name = DEFAULT_OFFICIAL_REPO_SLUG.split("/")
    upstream = tmp_path / owner / f"{name}.git"
    upstream.parent.mkdir(parents=True)
    _git(["init", "--bare", "-b", "main", str(upstream)], tmp_path)

    seed = tmp_path / "seed"
    _git(["clone", str(upstream), str(seed)], tmp_path)
    _git(["config", "user.email", "t@example.com"], seed)
    _git(["config", "user.name", "Tester"], seed)
    (seed / "dodaios").mkdir()
    init_py = seed / "dodaios" / "__init__.py"
    init_py.write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (seed / "requirements.txt").write_text("pkg==1\n", encoding="utf-8")
    _git(["add", "-A"], seed)
    _git(["commit", "-m", "A"], seed)
    _git(["push", "origin", "main"], seed)

    install = tmp_path / "install"
    _git(["clone", str(upstream), str(install)], tmp_path)
    (install / ".jarvis-managed-install").write_text("{}\n", encoding="utf-8")
    return upstream, seed, install


def test_managed_guard_passes_with_real_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _upstream, _seed, install = _make_upstream_and_install(tmp_path)
    monkeypatch.setattr(u, "_repo_root", lambda: install)
    resolved = asyncio.run(u._resolve_managed_repo())
    assert resolved == install

    # Remove the marker → guard must fail-closed even though origin is official.
    (install / ".jarvis-managed-install").unlink()
    assert asyncio.run(u._resolve_managed_repo()) is None


def _publish_release(seed: Path, version: str = "9.9.10") -> str:
    """Commit a version bump upstream, tag it and return the tagged commit."""
    (seed / "dodaios" / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    _git(["add", "-A"], seed)
    _git(["commit", "-m", f"release {version}"], seed)
    _git(["tag", f"v{version}"], seed)
    _git(["push", "origin", "main"], seed)
    _git(["push", "origin", f"v{version}"], seed)
    return _git_output(["rev-parse", "HEAD"], seed)


def _offer_release(
    monkeypatch: pytest.MonkeyPatch, install: Path, signed_commit: str, version: str = "9.9.10"
) -> None:
    """Offer ``v<version>`` to ``install``, its commit stated by a throwaway release key."""
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(
        private.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).decode("ascii")
    statement = f"{signed_commit}\n".encode("ascii")
    fetcher = FakeAssetFetcher(
        texts={
            PAYLOAD_COMMIT_ASSET_NAME: statement.decode("ascii"),
            PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME: base64.b64encode(
                private.sign(statement)
            ).decode("ascii"),
        }
    )
    base = f"https://github.com/{DEFAULT_OFFICIAL_REPO_SLUG}/releases/download/v{version}"

    async def _latest() -> dict[str, object]:
        return {
            "version": version,
            "tag": f"v{version}",
            "assets": [
                {"name": name, "browser_download_url": f"{base}/{name}", "size": 64}
                for name in (PAYLOAD_COMMIT_ASSET_NAME, PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME)
            ],
        }

    monkeypatch.setattr(u, "_repo_root", lambda: install)
    monkeypatch.setattr(u, "_running_version", lambda: "9.9.9")
    monkeypatch.setattr(u, "_fetch_latest_release", _latest)
    monkeypatch.setattr("dodaios.core.update_manifest.PINNED_PUBLIC_KEYS", (public,))
    monkeypatch.setattr("dodaios.core.release_commit.HttpxAssetFetcher", lambda: fetcher)


def test_real_apply_fetches_and_pins_without_mutating_live_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _upstream, seed, install = _make_upstream_and_install(tmp_path)

    # Publish a new upstream commit B (bumped version), signed by the release key.
    released = _publish_release(seed)

    # Before: the installed checkout is still on A.
    assert '9.9.9' in (install / "dodaios" / "__init__.py").read_text(encoding="utf-8")

    _offer_release(monkeypatch, install, released)
    # No request: a managed apply never quits the app itself, so it needs none.
    result = asyncio.run(u.update_apply(None))

    assert result["ok"] is True
    assert result["prepared"] is True
    assert result["restart_required"] is True
    assert result["version"] == "9.9.10"
    # The running checkout stays on A until the old process has exited.
    assert '9.9.9' in (install / "dodaios" / "__init__.py").read_text(encoding="utf-8")
    pending = (install / u._PENDING_UPDATE_NAME).read_text(encoding="utf-8")
    assert _git_output(["rev-parse", "HEAD"], install) in pending
    assert _git_output(["rev-parse", "FETCH_HEAD^{commit}"], install) in pending
    assert released in pending


def test_real_apply_refuses_a_tag_moved_off_the_signed_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _upstream, seed, install = _make_upstream_and_install(tmp_path)
    released = _publish_release(seed)

    # After the release key signed commit B, someone with push access puts
    # another commit under the same tag. It still claims the release's version.
    (seed / "requirements.txt").write_text("pkg==1\nextra==1\n", encoding="utf-8")
    _git(["add", "-A"], seed)
    _git(["commit", "-m", "not the release"], seed)
    _git(["tag", "--force", "v9.9.10"], seed)
    _git(["push", "--force", "origin", "v9.9.10"], seed)
    moved = _git_output(["rev-parse", "HEAD"], seed)
    assert moved != released

    _offer_release(monkeypatch, install, released)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(u.update_apply(None))

    assert refused.value.status_code == 502
    assert moved[:12] in str(refused.value.detail)
    assert released[:12] in str(refused.value.detail)
    # Nothing is staged, so a restart installs nothing.
    assert not (install / u._PENDING_UPDATE_NAME).exists()
    assert '9.9.9' in (install / "dodaios" / "__init__.py").read_text(encoding="utf-8")

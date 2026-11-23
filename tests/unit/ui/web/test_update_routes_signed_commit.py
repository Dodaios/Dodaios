"""A managed update installs only the commit the release key signed.

The in-app update of a git checkout fetches the tag of the newest release. A
tag can be moved by whoever can push to the repository, so the updater also
reads the release's ``payload-commit.txt`` and its signature
(``dodaios/core/release_commit.py``) and stages nothing unless the release key
signed exactly the commit the tag resolved to.

Every case signs with a throwaway Ed25519 key made inside the test; the one
exception checks a statement a real release published against the pinned key.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import dodaios.ui.web.update_routes as u
from dodaios.core.installer_update import InstallerAsset
from dodaios.core.release_commit import (
    MAX_PAYLOAD_COMMIT_BYTES,
    PAYLOAD_COMMIT_ASSET_NAME,
    PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME,
    ReleaseCommitError,
    SignedCommitAssets,
    fetch_signed_commit,
    select_signed_commit_assets,
    signed_commit,
)
from dodaios.core.update_manifest import MAX_SIGNATURE_BYTES
from dodaios.ui.web.update_routes import router as update_router
from tests.fakes.fake_installer_update import FakeAssetFetcher

PREVIOUS = "a" * 40
TARGET = "b" * 40
OTHER = "c" * 40
BASE_URL = "https://github.com/Dodaios/Dodaios/releases/download/v1.0.2"


def _key_pair() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, base64.b64encode(der).decode("ascii")


def _sign(private: Ed25519PrivateKey, data: bytes) -> str:
    return base64.b64encode(private.sign(data)).decode("ascii")


def _statement(revision: str = TARGET) -> bytes:
    """The file as the release workflow writes it: one revision and a line break."""
    return f"{revision}\n".encode("ascii")


def _entry(name: str, url: str | None = None) -> dict[str, Any]:
    return {"name": name, "browser_download_url": url or f"{BASE_URL}/{name}", "size": 64}


def _pair_entries() -> list[dict[str, Any]]:
    return [_entry(PAYLOAD_COMMIT_ASSET_NAME), _entry(PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME)]


def _release(assets: list[dict[str, Any]] | None) -> dict[str, Any]:
    release: dict[str, Any] = {
        "version": "1.0.2",
        "tag": "v1.0.2",
        "notes": "",
        "published_at": None,
        "release_url": None,
    }
    if assets is not None:
        release["assets"] = assets
    return release


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    u._status_cache = None
    u._status_cache_until = 0.0
    u._status_cache_root = None
    u._last_good_release = None


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(update_router)
    return TestClient(app)


class _Install:
    """A managed checkout whose git answers are scripted, and what it was asked."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[list[str]] = []
        self.fetcher = FakeAssetFetcher()

    @property
    def fetched(self) -> bool:
        return any(call[:1] == ["fetch"] for call in self.calls)

    @property
    def staged(self) -> dict[str, Any] | None:
        path = self.root / u._PENDING_UPDATE_NAME
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def _managed_install(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    release: dict[str, Any] | None,
    *,
    documents: dict[str, str] | None = None,
    public_key: str | None = None,
    tag_commit: str = TARGET,
) -> _Install:
    """A managed checkout on 1.0.1 that is offered ``release``.

    ``documents`` are the bodies the release serves, by file name. The tag of
    the release resolves to ``tag_commit`` in the checkout.
    """
    install = _Install(root)
    (root / ".jarvis-managed-install").write_text('{"profile": "full"}\n', encoding="utf-8")

    async def _root() -> Path:
        return root

    async def _latest() -> dict[str, Any] | None:
        return release

    async def _git(args, *, cwd, timeout_s=60.0, on_stderr_line=None, stall_timeout_s=None):
        install.calls.append(args)
        return 0, "", ""

    async def _git_output(args, *, cwd, timeout_s=15.0):
        install.calls.append(args)
        if args == ["rev-parse", "HEAD"]:
            return PREVIOUS
        if args == ["rev-parse", "FETCH_HEAD^{commit}"]:
            return tag_commit
        if args == ["show", f"{tag_commit}:dodaios/__init__.py"]:
            return '__version__ = "1.0.2"'
        return None

    monkeypatch.setattr(u, "_resolve_managed_repo", _root)
    monkeypatch.setattr(u, "_fetch_latest_release", _latest)
    monkeypatch.setattr(u, "_running_version", lambda: "1.0.1")
    monkeypatch.setattr(u, "_git", _git)
    monkeypatch.setattr(u, "_git_output", _git_output)
    install.fetcher.texts = dict(documents or {})
    monkeypatch.setattr("dodaios.core.release_commit.HttpxAssetFetcher", lambda: install.fetcher)
    if public_key is not None:
        monkeypatch.setattr("dodaios.core.update_manifest.PINNED_PUBLIC_KEYS", (public_key,))
    return install


def _signed_documents(private: Ed25519PrivateKey, revision: str = TARGET) -> dict[str, str]:
    data = _statement(revision)
    return {
        PAYLOAD_COMMIT_ASSET_NAME: data.decode("ascii"),
        PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME: _sign(private, data),
    }


# --------------------------------------------------------------------------- #
# POST /api/update/apply on a managed checkout
# --------------------------------------------------------------------------- #
def test_apply_stages_the_commit_the_release_key_signed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    private, public = _key_pair()
    install = _managed_install(
        monkeypatch,
        tmp_path,
        _release(_pair_entries()),
        documents=_signed_documents(private),
        public_key=public,
    )

    response = client.post("/api/update/apply")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert install.staged is not None
    assert install.staged["target_revision"] == TARGET
    assert install.fetcher.text_urls == [
        f"{BASE_URL}/{PAYLOAD_COMMIT_ASSET_NAME}",
        f"{BASE_URL}/{PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME}",
    ]


@pytest.mark.parametrize(
    "assets",
    [
        None,
        [],
        [_entry(PAYLOAD_COMMIT_ASSET_NAME)],
        [_entry(PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME)],
        # A plain-http address is not a source the updater reads from.
        [
            _entry(PAYLOAD_COMMIT_ASSET_NAME, "http://example.invalid/payload-commit.txt"),
            _entry(PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME),
        ],
    ],
    ids=["no-assets", "empty-assets", "no-signature", "no-statement", "http-address"],
)
def test_apply_refuses_a_release_without_the_signed_commit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    assets: list[dict[str, Any]] | None,
) -> None:
    install = _managed_install(monkeypatch, tmp_path, _release(assets))

    response = client.post("/api/update/apply")

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert PAYLOAD_COMMIT_ASSET_NAME in detail
    assert "v1.0.2" in detail
    # The progress panel cuts a reason at 300 characters; the whole sentence fits.
    assert len(detail) <= 300
    # Refused from the release metadata alone: nothing is downloaded or staged.
    assert install.fetched is False
    assert install.fetcher.text_urls == []
    assert install.staged is None


def test_apply_refuses_a_commit_another_key_signed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _release_key, public = _key_pair()
    someone_else = Ed25519PrivateKey.generate()
    install = _managed_install(
        monkeypatch,
        tmp_path,
        _release(_pair_entries()),
        documents=_signed_documents(someone_else),
        public_key=public,
    )

    response = client.post("/api/update/apply")

    assert response.status_code == 502
    assert "not signed by the Dodaios release key" in response.json()["detail"]
    assert install.staged is None


def test_apply_refuses_a_tag_that_points_at_another_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The release key signed TARGET; the tag in the repository was moved.
    private, public = _key_pair()
    install = _managed_install(
        monkeypatch,
        tmp_path,
        _release(_pair_entries()),
        documents=_signed_documents(private, TARGET),
        public_key=public,
        tag_commit=OTHER,
    )

    response = client.post("/api/update/apply")

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert OTHER[:12] in detail and TARGET[:12] in detail
    assert install.staged is None


def test_apply_refuses_a_signed_file_that_names_no_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Genuinely signed by the release key, but not a statement about a commit.
    private, public = _key_pair()
    data = b"#!/bin/sh\necho hello\n"
    install = _managed_install(
        monkeypatch,
        tmp_path,
        _release(_pair_entries()),
        documents={
            PAYLOAD_COMMIT_ASSET_NAME: data.decode("ascii"),
            PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME: _sign(private, data),
        },
        public_key=public,
    )

    response = client.post("/api/update/apply")

    assert response.status_code == 502
    assert "does not name a commit" in response.json()["detail"]
    assert install.staged is None


def test_apply_refuses_when_the_signed_commit_cannot_be_downloaded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install = _managed_install(monkeypatch, tmp_path, _release(_pair_entries()))
    install.fetcher.fail_text = httpx.ConnectError("no route to host")

    response = client.post("/api/update/apply")

    assert response.status_code == 502
    assert f"could not download {PAYLOAD_COMMIT_ASSET_NAME}" in response.json()["detail"]
    assert install.staged is None


def test_a_remembered_release_is_checked_like_a_live_one(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The release API is unreachable, so apply falls back to the answer the
    # status check remembered. That answer gets no easier treatment.
    install = _managed_install(monkeypatch, tmp_path, None)
    u._last_good_release = _release([])

    response = client.post("/api/update/apply")

    assert response.status_code == 502
    assert PAYLOAD_COMMIT_ASSET_NAME in response.json()["detail"]
    assert install.staged is None


def test_the_terminal_update_refuses_an_unsigned_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # ``dodaios update`` stages through the same function as the button.
    install = _managed_install(monkeypatch, tmp_path, _release([]))

    with pytest.raises(HTTPException) as refused:
        asyncio.run(u.stage_managed_update())

    assert refused.value.status_code == 502
    assert install.staged is None


# --------------------------------------------------------------------------- #
# dodaios.core.release_commit
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("revision", [TARGET, "d" * 64], ids=["sha1", "sha256"])
def test_a_signed_statement_gives_its_commit(revision: str) -> None:
    private, public = _key_pair()
    data = _statement(revision)

    assert signed_commit(data, _sign(private, data), public_keys=(public,)) == revision


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"main\n",
        ("B" * 40 + "\n").encode("ascii"),
        ("b" * 39 + "\n").encode("ascii"),
        (TARGET + " " + OTHER + "\n").encode("ascii"),
        (TARGET + "\n" + OTHER + "\n").encode("ascii"),
        b"bbbb\xc3\xa9\n",
    ],
    ids=[
        "empty",
        "branch-name",
        "upper-case",
        "too-short",
        "two-on-a-line",
        "two-lines",
        "non-ascii",
    ],
)
def test_a_signed_file_that_is_not_one_revision_is_refused(data: bytes) -> None:
    private, public = _key_pair()

    with pytest.raises(ReleaseCommitError, match="does not name a commit"):
        signed_commit(data, _sign(private, data), public_keys=(public,))


def test_an_oversized_statement_is_refused_before_any_check() -> None:
    private, public = _key_pair()
    data = b"b" * (MAX_PAYLOAD_COMMIT_BYTES + 1)

    with pytest.raises(ReleaseCommitError, match="too large"):
        signed_commit(data, _sign(private, data), public_keys=(public,))


@pytest.mark.parametrize(
    "signature",
    ["", "not base64 !", base64.b64encode(b"short").decode("ascii")],
    ids=["empty", "not-base64", "wrong-length"],
)
def test_a_malformed_signature_is_refused(signature: str) -> None:
    _private, public = _key_pair()

    with pytest.raises(ReleaseCommitError, match=PAYLOAD_COMMIT_ASSET_NAME):
        signed_commit(_statement(), signature, public_keys=(public,))


def test_a_changed_statement_no_longer_verifies() -> None:
    private, public = _key_pair()
    signature = _sign(private, _statement(TARGET))

    with pytest.raises(ReleaseCommitError, match="not signed by the Dodaios release key"):
        signed_commit(_statement(OTHER), signature, public_keys=(public,))


def test_the_statement_a_real_release_published_verifies_with_the_pinned_key() -> None:
    # v5.7.0, as downloaded from its release: the format the release workflow
    # writes is the format this verifier reads, against the key it really pins.
    data = b"3a52cd0be1177ff2660f6dc65dbaac11b641e9cb\n"
    signature = (
        "y9klz8L6p6p/jXJ1TirQuCOkfnHx0oGCsBU8tfc+jaRSIIETWWifp+YgA3kLuFeQxRklCvbQeuBJyq2wbMkMAA=="
    )

    assert signed_commit(data, signature) == "3a52cd0be1177ff2660f6dc65dbaac11b641e9cb"
    with pytest.raises(ReleaseCommitError):
        signed_commit(data.replace(b"3a52", b"3a53"), signature)


def test_half_a_pair_is_no_pair() -> None:
    assert select_signed_commit_assets([]) is None
    assert select_signed_commit_assets([_entry(PAYLOAD_COMMIT_ASSET_NAME)]) is None
    only_signature = ["junk", _entry(PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME)]
    assert select_signed_commit_assets(only_signature) is None
    found = select_signed_commit_assets(_pair_entries())
    assert found is not None
    assert found.statement.name == PAYLOAD_COMMIT_ASSET_NAME
    assert found.signature.name == PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME


class _CappedFetcher:
    """Answers like the real fetcher: a body over the caller's cap is refused."""

    def __init__(self, bodies: dict[str, str]) -> None:
        self.bodies = bodies
        self.caps: dict[str, int] = {}

    async def get_text(self, url: str, *, max_bytes: int) -> str:
        from dodaios.core.installer_update import InstallerUpdateError

        name = url.rsplit("/", 1)[-1]
        self.caps[name] = max_bytes
        body = self.bodies[name]
        if len(body.encode("utf-8")) > max_bytes:
            raise InstallerUpdateError(f"release manifest is larger than {max_bytes} bytes")
        return body

    async def download(self, *args: Any, **kwargs: Any) -> int:  # pragma: no cover - unused
        raise AssertionError("the signed commit is never downloaded to a file")


def _pair() -> SignedCommitAssets:
    return SignedCommitAssets(
        statement=InstallerAsset(
            PAYLOAD_COMMIT_ASSET_NAME, f"{BASE_URL}/{PAYLOAD_COMMIT_ASSET_NAME}", 41
        ),
        signature=InstallerAsset(
            PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME,
            f"{BASE_URL}/{PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME}",
            88,
        ),
    )


async def test_both_documents_are_fetched_under_a_size_cap() -> None:
    private, public = _key_pair()
    fetcher = _CappedFetcher(_signed_documents(private))

    assert await fetch_signed_commit(_pair(), fetcher=fetcher, public_keys=(public,)) == TARGET
    assert fetcher.caps == {
        PAYLOAD_COMMIT_ASSET_NAME: MAX_PAYLOAD_COMMIT_BYTES,
        PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME: MAX_SIGNATURE_BYTES,
    }


async def test_an_oversized_download_is_refused_by_name() -> None:
    private, public = _key_pair()
    documents = _signed_documents(private)
    documents[PAYLOAD_COMMIT_ASSET_NAME] = "b" * (MAX_PAYLOAD_COMMIT_BYTES + 1)

    with pytest.raises(ReleaseCommitError, match=PAYLOAD_COMMIT_ASSET_NAME):
        await fetch_signed_commit(
            _pair(), fetcher=_CappedFetcher(documents), public_keys=(public,)
        )

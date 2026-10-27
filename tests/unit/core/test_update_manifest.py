"""The signed, version-bound update manifest (issue #810).

Every case signs with a throwaway Ed25519 key made inside the test; the real
release key never leaves the ``release-signing`` environment. What is pinned:

* the verifier accepts exactly what the release workflow produces (including a
  signature made by ``openssl pkeyutl``, the workflow's own tool),
* a wrong key, a tampered manifest, a replayed older version and a swapped
  checksum manifest are each refused before any installer byte is fetched,
* the key pinned in the app is the published offline-ceremony key.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dodaios.core.installer_update import (
    CHECKSUMS_ASSET_NAME,
    InstallerAsset,
    InstallerUpdateError,
    SignedManifestAssets,
    download_and_verify,
)
from dodaios.core.update_manifest import (
    MANIFEST_SCHEMA,
    PINNED_PUBLIC_KEYS,
    UPDATE_MANIFEST_ASSET_NAME,
    UPDATE_MANIFEST_SIGNATURE_ASSET_NAME,
    UpdateManifestError,
    build_manifest,
    parse_manifest,
    verify_update_manifest,
)
from scripts.ci import release_assets
from scripts.ci import update_manifest as manifest_cli
from tests.fakes.fake_installer_update import FakeAssetFetcher

ROOT = Path(__file__).resolve().parents[3]
PAYLOAD = b"an installer stand-in"
SETUP = "Dodaios-Setup-x64.exe"
CHECKSUMS = f"{hashlib.sha256(PAYLOAD).hexdigest()}  {SETUP}\n".encode()


def _key_pair() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, base64.b64encode(public).decode("ascii")


def _sign(private: Ed25519PrivateKey, data: bytes) -> str:
    return base64.b64encode(private.sign(data)).decode("ascii")


# --------------------------------------------------------------------------- #
# The document and its signature
# --------------------------------------------------------------------------- #
def test_build_is_canonical_and_parses_back() -> None:
    data = build_manifest(version="4.2.0", tag="v4.2.0", checksums=CHECKSUMS)
    assert data == build_manifest(version="v4.2.0", tag="v4.2.0", checksums=CHECKSUMS)
    assert b" " not in data and data.isascii()
    parsed = parse_manifest(data)
    assert parsed.version == "4.2.0"
    assert parsed.tag == "v4.2.0"
    assert parsed.checksums_sha256 == hashlib.sha256(CHECKSUMS).hexdigest()


def test_build_refuses_a_tag_for_another_version() -> None:
    with pytest.raises(UpdateManifestError):
        build_manifest(version="4.2.0", tag="v4.1.0", checksums=CHECKSUMS)


def test_a_valid_manifest_verifies() -> None:
    private, public = _key_pair()
    data = build_manifest(version="4.2.0", tag="v4.2.0", checksums=CHECKSUMS)
    verified = verify_update_manifest(
        data,
        _sign(private, data),
        checksums=CHECKSUMS,
        expected_version="4.2.0",
        public_keys=(public,),
    )
    assert verified.tag == "v4.2.0"


def test_any_pinned_key_may_sign_so_a_rotation_can_overlap() -> None:
    old_private, old_public = _key_pair()
    _new_private, new_public = _key_pair()
    data = build_manifest(version="4.2.0", tag="v4.2.0", checksums=CHECKSUMS)
    verify_update_manifest(
        data,
        _sign(old_private, data),
        checksums=CHECKSUMS,
        expected_version="v4.2.0",
        public_keys=(new_public, old_public),
    )


@pytest.mark.parametrize(
    "defect", ["wrong_key", "tampered", "replayed", "other_checksums", "garbage_sig", "short_sig"]
)
def test_every_defect_is_refused(defect: str) -> None:
    private, public = _key_pair()
    version = "4.2.0"
    data = build_manifest(version=version, tag="v4.2.0", checksums=CHECKSUMS)
    signature = _sign(private, data)
    checksums = CHECKSUMS
    if defect == "wrong_key":
        signature = _sign(Ed25519PrivateKey.generate(), data)
    elif defect == "tampered":
        data = data.replace(b"4.2.0", b"4.3.0")
    elif defect == "replayed":
        # A genuine, signed manifest of an older release served as the newer one.
        data = build_manifest(version="4.1.0", tag="v4.1.0", checksums=CHECKSUMS)
        signature = _sign(private, data)
    elif defect == "other_checksums":
        checksums = CHECKSUMS.replace(SETUP.encode(), b"Evil-Setup.exe")
    elif defect == "garbage_sig":
        signature = "not base64 at all!"
    else:
        signature = base64.b64encode(b"x" * 10).decode()
    with pytest.raises(UpdateManifestError):
        verify_update_manifest(
            data,
            signature,
            checksums=checksums,
            expected_version=version,
            public_keys=(public,),
        )


def test_a_signature_over_something_else_is_not_a_manifest() -> None:
    """The release key also signs install scripts; those never parse as a manifest."""
    private, public = _key_pair()
    script = b"#!/bin/sh\necho install\n"
    with pytest.raises(UpdateManifestError):
        verify_update_manifest(
            script,
            _sign(private, script),
            checksums=CHECKSUMS,
            expected_version="4.2.0",
            public_keys=(public,),
        )
    with pytest.raises(UpdateManifestError, match="schema"):
        parse_manifest(b'{"schema":"other","version":"4.2.0"}')
    assert MANIFEST_SCHEMA.startswith("dodaios-update-manifest/")


def test_the_pinned_key_is_the_published_offline_ceremony_key() -> None:
    pem = (ROOT / "install" / "keys" / "offline-ceremony.pub").read_text(encoding="ascii")
    body = "".join(line for line in pem.splitlines() if not line.startswith("-----"))
    assert PINNED_PUBLIC_KEYS == (body,)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is not installed")
def test_a_signature_made_like_the_workflow_makes_it_verifies(tmp_path: Path) -> None:
    """``openssl pkeyutl -sign -rawin`` + ``base64 -w0`` is what the release job runs."""
    private, public = _key_pair()
    key = tmp_path / "release.key"
    key.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    manifest = tmp_path / UPDATE_MANIFEST_ASSET_NAME
    manifest.write_bytes(build_manifest(version="4.2.0", tag="v4.2.0", checksums=CHECKSUMS))
    raw = tmp_path / "sig.raw"
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            str(key),
            "-rawin",
            "-in",
            str(manifest),
            "-out",
            str(raw),
        ],
        check=True,
        capture_output=True,
    )
    verify_update_manifest(
        manifest.read_bytes(),
        base64.b64encode(raw.read_bytes()).decode("ascii"),
        checksums=CHECKSUMS,
        expected_version="4.2.0",
        public_keys=(public,),
    )


# --------------------------------------------------------------------------- #
# The updater refuses before downloading the installer
# --------------------------------------------------------------------------- #
def _asset(name: str) -> InstallerAsset:
    return InstallerAsset(name=name, url=f"https://example.invalid/{name}", size=len(PAYLOAD))


def _signed(version: str = "4.2.0") -> SignedManifestAssets:
    return SignedManifestAssets(
        manifest=_asset(UPDATE_MANIFEST_ASSET_NAME),
        signature=_asset(UPDATE_MANIFEST_SIGNATURE_ASSET_NAME),
        version=version,
    )


def _fetcher(manifest: bytes, signature: str) -> FakeAssetFetcher:
    return FakeAssetFetcher(
        manifest=CHECKSUMS.decode("ascii"),
        payload=PAYLOAD,
        texts={
            UPDATE_MANIFEST_ASSET_NAME: manifest.decode("ascii"),
            UPDATE_MANIFEST_SIGNATURE_ASSET_NAME: signature,
        },
    )


async def test_a_signed_release_downloads_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private, public = _key_pair()
    monkeypatch.setattr("dodaios.core.update_manifest.PINNED_PUBLIC_KEYS", (public,))
    data = build_manifest(version="4.2.0", tag="v4.2.0", checksums=CHECKSUMS)
    fetcher = _fetcher(data, _sign(private, data))

    result = await download_and_verify(
        _asset(SETUP),
        _asset(CHECKSUMS_ASSET_NAME),
        dest_dir=tmp_path,
        fetcher=fetcher,
        signed=_signed(),
    )

    assert result.read_bytes() == PAYLOAD


@pytest.mark.parametrize("defect", ["unsigned_by_release_key", "replayed_version"])
async def test_a_bad_signed_manifest_stops_before_the_installer_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    private, public = _key_pair()
    monkeypatch.setattr("dodaios.core.update_manifest.PINNED_PUBLIC_KEYS", (public,))
    data = build_manifest(version="4.1.0", tag="v4.1.0", checksums=CHECKSUMS)
    signer = Ed25519PrivateKey.generate() if defect == "unsigned_by_release_key" else private
    fetcher = _fetcher(data, _sign(signer, data))

    with pytest.raises(InstallerUpdateError, match=UPDATE_MANIFEST_ASSET_NAME):
        await download_and_verify(
            _asset(SETUP),
            _asset(CHECKSUMS_ASSET_NAME),
            dest_dir=tmp_path,
            fetcher=fetcher,
            signed=_signed("4.2.0" if defect == "replayed_version" else "4.1.0"),
        )

    assert fetcher.download_urls == []
    assert not (tmp_path / SETUP).exists()


# --------------------------------------------------------------------------- #
# The release pipeline's side
# --------------------------------------------------------------------------- #
def test_the_ci_script_builds_and_checks_the_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manifest_cli, "_package_version", lambda: "4.2.0")
    checksums = tmp_path / CHECKSUMS_ASSET_NAME
    checksums.write_bytes(CHECKSUMS)
    out = tmp_path / UPDATE_MANIFEST_ASSET_NAME
    args = ["--tag", "v4.2.0", "--checksums", str(checksums)]

    assert manifest_cli.main(["build", *args, "--out", str(out)]) == 0
    assert manifest_cli.main(["check", *args, "--manifest", str(out)]) == 0
    # A tag for another version is refused at build time.
    assert (
        manifest_cli.main(
            ["build", "--tag", "v9.9.9", "--checksums", str(checksums), "--out", str(out)]
        )
        == 1
    )
    # A checksum manifest changed after signing no longer matches.
    checksums.write_bytes(CHECKSUMS + CHECKSUMS)
    assert manifest_cli.main(["check", *args, "--manifest", str(out)]) == 1


def test_release_finalization_checks_the_signed_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    private, public = _key_pair()
    monkeypatch.setattr("dodaios.core.update_manifest.PINNED_PUBLIC_KEYS", (public,))
    text = CHECKSUMS.decode("ascii")
    data = build_manifest(version="4.2.0", tag="v4.2.0", checksums=CHECKSUMS)

    assert release_assets.update_manifest_errors("v4.2.0", text, data, _sign(private, data)) == []
    assert release_assets.update_manifest_errors("v4.3.0", text, data, _sign(private, data))
    assert release_assets.update_manifest_errors("v4.2.0", text + text, data, _sign(private, data))
    forged = _sign(Ed25519PrivateKey.generate(), data)
    assert release_assets.update_manifest_errors("v4.2.0", text, data, forged)


def test_the_desktop_upload_requires_the_signed_manifest() -> None:
    for name in (UPDATE_MANIFEST_ASSET_NAME, UPDATE_MANIFEST_SIGNATURE_ASSET_NAME):
        assert name in release_assets.DESKTOP_ASSETS
        assert name not in release_assets.SIGNING_ASSETS


def test_only_the_tag_signing_job_reads_the_release_key() -> None:
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "desktop-installers.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]
    sign = jobs["sign-update-manifest"]
    assert sign["environment"] == "release-signing"
    assert sign["if"] == "github.ref_type == 'tag'"
    assert sign["permissions"] == {"contents": "read"}
    readers = [name for name, job in jobs.items() if "WAVE2_OFFLINE_KEY_B64" in yaml.safe_dump(job)]
    assert readers == ["sign-update-manifest"]
    assert "sign-update-manifest" in jobs["release"]["needs"]
    assert jobs["release"]["name"] == release_assets.PUBLISHER_JOBS["desktop-installers.yml"]

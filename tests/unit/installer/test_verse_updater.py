"""Verse channel, signed checksums and resumable download (WP22.5, A22.3, A22.5)."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from dodaios.core import installer_update as iu
from dodaios.core.update_manifest import build_manifest
from scripts.unreal import package

TAG = "v4.2.1"
BASE_URL = "https://example.invalid/releases/download/v4.2.1/"


def test_the_size_cap_is_raised_for_an_installer_that_carries_the_verse() -> None:
    assert iu.MAX_INSTALLER_BYTES >= 3_000_000_000
    assert iu.MAX_VERSE_BYTES >= 2_000_000_000
    assert iu.MAX_VERSE_DELTA_BYTES >= 300_000_000


@pytest.mark.parametrize(
    ("platform_name", "machine", "expected"),
    [
        ("win32", "AMD64", "Win64"),
        ("linux", "x86_64", "Linux"),
        ("darwin", "arm64", None),
        ("linux", "aarch64", None),
    ],
)
def test_verse_platform(platform_name: str, machine: str, expected: str | None) -> None:
    assert iu.verse_platform(platform_name, machine) == expected


def test_verse_root_follows_the_platform_data_folder(tmp_path: Path) -> None:
    assert iu.verse_root({"DODAIOS_VERSE_ROOT": str(tmp_path)}) == tmp_path
    win = iu.verse_root({"LOCALAPPDATA": "C:/Local"}, "win32")
    assert win.as_posix() == "C:/Local/Dodaios/verse"
    linux = iu.verse_root({"XDG_DATA_HOME": "/data"}, "linux")
    assert linux.as_posix() == "/data/dodaios/verse"


def _asset(name: str, size: int = 10) -> dict:
    return {"name": name, "browser_download_url": BASE_URL + name, "size": size}


SIGNED = [
    _asset(iu.VERSE_CHECKSUMS_ASSET_NAME),
    _asset(iu.VERSE_MANIFEST_ASSET_NAME),
    _asset(iu.VERSE_MANIFEST_SIGNATURE_ASSET_NAME),
]


def test_no_gpu_means_no_download() -> None:
    assets = [_asset("Verse-Win64-4.2.1.tar"), *SIGNED]
    kwargs = {"version": TAG, "installed": None, "platform_name": "win32", "machine": "AMD64"}
    assert iu.select_verse_update(assets, gpu_supported=False, **kwargs) is None
    assert iu.select_verse_update(assets, gpu_supported=True, **kwargs).kind == "full"


def test_the_delta_is_preferred_and_the_full_payload_is_its_fallback() -> None:
    assets = [
        _asset("Verse-Win64-4.2.1.tar"),
        _asset("Verse-Win64-4.2.0-to-4.2.1.delta.tar"),
        _asset("Verse-Linux-4.2.0-to-4.2.1.delta.tar"),
        *SIGNED,
    ]
    plan = iu.select_verse_update(
        assets,
        version=TAG,
        installed="4.2.0",
        gpu_supported=True,
        platform_name="win32",
        machine="AMD64",
    )
    assert plan.kind == "delta"
    assert plan.payload.name == "Verse-Win64-4.2.0-to-4.2.1.delta.tar"
    assert plan.fallback.name == "Verse-Win64-4.2.1.tar"
    assert plan.signed.version == "4.2.1"
    # No delta from an older base: the full payload.
    older = iu.select_verse_update(
        assets,
        version=TAG,
        installed="4.1.0",
        gpu_supported=True,
        platform_name="win32",
        machine="AMD64",
    )
    assert older.kind == "full" and older.fallback is None


def test_up_to_date_unshipped_or_unsigned() -> None:
    kwargs = {"gpu_supported": True, "platform_name": "linux", "machine": "x86_64"}
    full = [_asset("Verse-Linux-4.2.1.tar")]
    assert iu.select_verse_update(full + SIGNED, version=TAG, installed="4.2.1", **kwargs) is None
    assert iu.select_verse_update(SIGNED, version=TAG, installed=None, **kwargs) is None
    with pytest.raises(iu.VerseUpdateError, match="without its signed checksum manifest"):
        iu.select_verse_update(full, version=TAG, installed=None, **kwargs)
    mac = dict(kwargs, platform_name="darwin", machine="arm64")
    assert iu.select_verse_update(full + SIGNED, version=TAG, installed=None, **mac) is None


# --------------------------------------------------------------- download
class Release:
    """A release served from memory, signed with a test key pinned for the test."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, files: dict[str, bytes]) -> None:
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        monkeypatch.setattr(
            "dodaios.core.update_manifest.PINNED_PUBLIC_KEYS", (base64.b64encode(public).decode(),)
        )
        sums = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items()
        ).encode()
        manifest = build_manifest(version="4.2.1", tag=TAG, checksums=sums)
        self.files = {
            **files,
            iu.VERSE_CHECKSUMS_ASSET_NAME: sums,
            iu.VERSE_MANIFEST_ASSET_NAME: manifest,
            iu.VERSE_MANIFEST_SIGNATURE_ASSET_NAME: base64.b64encode(key.sign(manifest)),
        }
        self.drops: dict[str, list[int]] = {}
        self.ranges: list[str] = []

    def assets(self) -> list[dict]:
        return [_asset(name, len(data)) for name, data in self.files.items()]


class FakeFetcher:
    """Serves a :class:`Release`; ``drops[name]`` cuts transfers after N bytes once each."""

    def __init__(self, release: Release) -> None:
        self.release = release

    def _name(self, url: str) -> str:
        return url.rsplit("/", 1)[-1]

    async def get_text(self, url: str, *, max_bytes: int) -> str:
        return self.release.files[self._name(url)].decode()

    async def download(self, url, dest, *, max_bytes, on_progress=None) -> int:
        return await self.download_resume(url, dest, offset=0, max_bytes=max_bytes)

    async def download_resume(self, url, dest, *, offset, max_bytes, on_progress=None) -> int:
        name = self._name(url)
        data = self.release.files[name]
        self.release.ranges.append(f"{name}@{offset}")
        drops = self.release.drops.get(name, [])
        cut = drops.pop(0) if drops else None
        _write(
            Path(dest), data[offset:cut] if cut is not None else data[offset:], append=bool(offset)
        )
        if cut is not None:
            raise httpx.ReadError("connection reset")
        return len(data)


def _write(path: Path, data: bytes, *, append: bool) -> None:
    with path.open("ab" if append else "wb") as handle:
        handle.write(data)


async def _no_sleep(_s: float) -> None:
    return None


def _payloads(tmp_path: Path) -> dict[str, bytes]:
    old = tmp_path / "old"
    new = tmp_path / "new"
    for folder, chunk in ((old, b"hangar-1" * 4000), (new, b"hangar-2" * 4100)):
        (folder / "Verse/Content/Paks").mkdir(parents=True)
        (folder / "Verse.exe").write_bytes(b"launcher")
        (folder / "Verse/Content/Paks/pakchunk0-Windows.utoc").write_bytes(b"core" * 1000)
        (folder / "Verse/Content/Paks/pakchunk4-Windows.ucas").write_bytes(chunk)
    package.make_full(old, version="4.2.0", platform="Win64", out=tmp_path / "old.tar")
    full = tmp_path / "Verse-Win64-4.2.1.tar"
    package.make_full(new, version="4.2.1", platform="Win64", out=full)
    delta = tmp_path / "Verse-Win64-4.2.0-to-4.2.1.delta.tar"
    package.make_delta(
        package.read_payload_tree(tmp_path / "old.tar"), new, version="4.2.1", out=delta
    )
    return {full.name: full.read_bytes(), delta.name: delta.read_bytes()}


@pytest.fixture
def installed(tmp_path: Path) -> Path:
    payloads = _payloads(tmp_path)
    root = tmp_path / "root"
    iu.install_verse_full(root, tmp_path / "old.tar")
    (tmp_path / "payloads").mkdir()
    for name, data in payloads.items():
        (tmp_path / "payloads" / name).write_bytes(data)
    return root


def _release(monkeypatch, tmp_path: Path) -> Release:
    folder = tmp_path / "payloads"
    return Release(monkeypatch, {p.name: p.read_bytes() for p in sorted(folder.iterdir())})


async def test_a_dropped_download_resumes_where_it_stopped(
    monkeypatch, tmp_path: Path, installed: Path
) -> None:
    release = _release(monkeypatch, tmp_path)
    name = "Verse-Win64-4.2.0-to-4.2.1.delta.tar"
    release.drops[name] = [1000, 5000]
    monkeypatch.setattr(iu, "VERSE_RESUME_BACKOFF_S", 0)
    result = await iu.update_verse(
        release.assets(),
        version=TAG,
        gpu_supported=True,
        root=installed,
        fetcher=FakeFetcher(release),
        platform_name="win32",
        machine="AMD64",
    )
    assert result["status"] == "updated" and result["kind"] == "delta"
    assert result["version"] == "4.2.1"
    assert [r for r in release.ranges if r.startswith(name)] == [
        f"{name}@0",
        f"{name}@1000",
        f"{name}@5000",
    ]
    assert iu.verify_verse_tree(iu.verse_version_dir(installed, "4.2.1")) == []
    assert not list((installed / "downloads").iterdir())


async def test_a_tampered_payload_is_refused_before_it_is_installed(
    monkeypatch, tmp_path: Path, installed: Path
) -> None:
    release = _release(monkeypatch, tmp_path)
    name = "Verse-Win64-4.2.0-to-4.2.1.delta.tar"
    release.files[name] = release.files[name][:-10] + b"x" * 10
    del release.files["Verse-Win64-4.2.1.tar"]
    with pytest.raises(iu.VerseUpdateError, match="failed its SHA-256 check"):
        await iu.update_verse(
            release.assets(),
            version=TAG,
            gpu_supported=True,
            root=installed,
            fetcher=FakeFetcher(release),
            platform_name="win32",
            machine="AMD64",
        )
    assert iu.verse_current(installed)["version"] == "4.2.0"


async def test_a_bad_delta_falls_back_to_the_full_payload(
    monkeypatch, tmp_path: Path, installed: Path
) -> None:
    release = _release(monkeypatch, tmp_path)
    release.files["Verse-Win64-4.2.0-to-4.2.1.delta.tar"] = b"not a tar"
    # Re-sign so the digest matches the broken bytes: the apply step must catch it.
    release = Release(
        monkeypatch, {k: v for k, v in release.files.items() if k.startswith("Verse-")}
    )
    result = await iu.update_verse(
        release.assets(),
        version=TAG,
        gpu_supported=True,
        root=installed,
        fetcher=FakeFetcher(release),
        platform_name="win32",
        machine="AMD64",
    )
    assert result["kind"] == "full" and result["version"] == "4.2.1"
    assert iu.verse_current(installed)["previous"] == "4.2.0"


async def test_a_signature_from_another_key_is_refused(
    monkeypatch, tmp_path: Path, installed: Path
) -> None:
    release = _release(monkeypatch, tmp_path)
    other = Ed25519PrivateKey.generate()
    release.files[iu.VERSE_MANIFEST_SIGNATURE_ASSET_NAME] = base64.b64encode(
        other.sign(release.files[iu.VERSE_MANIFEST_ASSET_NAME])
    )
    with pytest.raises(iu.InstallerUpdateError, match="not signed by the Dodaios release key"):
        await iu.update_verse(
            release.assets(),
            version=TAG,
            gpu_supported=True,
            root=installed,
            fetcher=FakeFetcher(release),
            platform_name="win32",
            machine="AMD64",
        )
    assert iu.verse_current(installed)["version"] == "4.2.0"


async def test_gpu_less_machines_are_untouched(tmp_path: Path) -> None:
    result = await iu.update_verse([], version=TAG, gpu_supported=False, root=tmp_path / "r")
    assert result == {"status": "unsupported", "version": None}
    assert not (tmp_path / "r").exists()


async def test_give_up_after_the_resume_budget_and_keep_the_part(
    monkeypatch, tmp_path: Path, installed: Path
) -> None:
    release = _release(monkeypatch, tmp_path)
    name = "Verse-Win64-4.2.1.tar"
    release.drops[name] = [100 * (i + 1) for i in range(iu.VERSE_RESUME_ATTEMPTS)]
    plan = iu.select_verse_update(
        release.assets(),
        version=TAG,
        installed=None,
        gpu_supported=True,
        platform_name="win32",
        machine="AMD64",
    )
    with pytest.raises(iu.VerseUpdateError, match="resumes where this one stopped"):
        await iu.download_verse_payload(
            plan, dest_dir=tmp_path / "dl", fetcher=FakeFetcher(release), sleep=_no_sleep
        )
    part = tmp_path / "dl" / f"{name}.part"
    assert part.stat().st_size == 100 * iu.VERSE_RESUME_ATTEMPTS


# --------------------------------------------------- HTTP ranges, for real
def _range_transport(data: bytes, seen: list[str], *, ranges: bool = True):
    def handler(request: httpx.Request) -> httpx.Response:
        header = request.headers.get("range", "")
        seen.append(header)
        if header and ranges:
            start = int(header.removeprefix("bytes=").rstrip("-"))
            if start >= len(data):
                return httpx.Response(416)
            return httpx.Response(206, content=data[start:])
        return httpx.Response(200, content=data)

    return httpx.MockTransport(handler)


async def test_httpx_fetcher_resumes_with_a_range_request(tmp_path: Path) -> None:
    data = bytes(range(256)) * 40
    dest = tmp_path / "x.part"
    dest.write_bytes(data[:1234])
    seen: list[str] = []
    fetcher = iu.HttpxAssetFetcher(transport=_range_transport(data, seen))
    size = await fetcher.download_resume(
        "https://example.invalid/x", dest, offset=1234, max_bytes=10**6
    )
    assert seen == ["bytes=1234-"]
    assert size == len(data) and dest.read_bytes() == data


async def test_httpx_fetcher_restarts_when_the_server_ignores_ranges(tmp_path: Path) -> None:
    data = b"abc" * 1000
    dest = tmp_path / "x.part"
    dest.write_bytes(b"zzz")
    fetcher = iu.HttpxAssetFetcher(transport=_range_transport(data, [], ranges=False))
    await fetcher.download_resume("https://example.invalid/x", dest, offset=3, max_bytes=10**6)
    assert dest.read_bytes() == data


async def test_httpx_fetcher_treats_416_as_complete(tmp_path: Path) -> None:
    data = b"done"
    dest = tmp_path / "x.part"
    dest.write_bytes(data)
    fetcher = iu.HttpxAssetFetcher(transport=_range_transport(data, []))
    assert (
        await fetcher.download_resume("https://example.invalid/x", dest, offset=4, max_bytes=10**6)
        == 4
    )


async def test_httpx_fetcher_enforces_the_cap_across_the_resume(tmp_path: Path) -> None:
    data = b"y" * 5000
    dest = tmp_path / "x.part"
    dest.write_bytes(data[:4000])
    fetcher = iu.HttpxAssetFetcher(transport=_range_transport(data, []))
    with pytest.raises(iu.InstallerUpdateError, match="exceeded 4500 bytes"):
        await fetcher.download_resume(
            "https://example.invalid/x", dest, offset=4000, max_bytes=4500
        )

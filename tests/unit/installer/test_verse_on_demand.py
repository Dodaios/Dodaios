"""The Verse as an optional on-demand download (WP22.5, WP22.6, acceptance A22.7).

Runs the real installer against a local HTTP server that speaks like a GitHub
release (listing, assets, byte ranges) and can drop a connection mid-file:

- a fresh install reads ``not_installed`` and no installer carries the Verse;
- the download from the card installs and the installed Verse launches;
- an interrupted download resumes with a byte range instead of starting over;
- a tampered package or manifest is rejected and nothing is installed;
- uninstall frees the folder and returns to ``not_installed``;
- only an installed Verse updates, by delta when one fits.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from dodaios.core import installer_update
from dodaios.verse_host.install import VerseInstaller, VerseInstallError, layout
from dodaios.verse_host.install import manifest as vm
from dodaios.verse_host.install.download import HttpFetcher
from scripts.unreal import package

REPO = Path(__file__).resolve().parents[3]
LAUNCH_SCRIPT = b"print('verse up')\n"


# --------------------------------------------------------------- signing
@dataclass
class Signer:
    key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)

    @property
    def public_keys(self) -> list[str]:
        der = self.key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        return [base64.b64encode(der).decode("ascii")]

    def sign(self, data: bytes) -> bytes:
        return base64.b64encode(self.key.sign(data))


# ------------------------------------------------------------ the server
@dataclass
class Release:
    tag: str
    assets: dict[str, bytes]


@dataclass
class FakeGitHub:
    releases: list[Release] = field(default_factory=list)
    #: asset name -> bytes after which the next GET of it drops the connection
    drop_once: dict[str, int] = field(default_factory=dict)
    #: asset name -> replacement bytes served instead of the published ones
    tamper: dict[str, bytes] = field(default_factory=dict)
    requests: list[tuple[str, str | None]] = field(default_factory=list)
    base: str = ""

    def listing(self) -> bytes:
        rows = []
        for release in self.releases:
            rows.append(
                {
                    "tag_name": release.tag,
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "name": name,
                            "size": len(data),
                            "browser_download_url": f"{self.base}/dl/{release.tag}/{name}",
                        }
                        for name, data in release.assets.items()
                    ],
                }
            )
        return json.dumps(rows).encode()

    def asset(self, tag: str, name: str) -> bytes | None:
        for release in self.releases:
            if release.tag == tag and name in release.assets:
                return self.tamper.get(name, release.assets[name])
        return None

    def downloaded(self, name: str) -> list[str | None]:
        return [rng for path, rng in self.requests if path.endswith("/" + name)]


def _handler(hub: FakeGitHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            rng = self.headers.get("Range")
            hub.requests.append((self.path, rng))
            if self.path == "/releases":
                return self._send(200, hub.listing())
            match = re.fullmatch(r"/dl/([^/]+)/([^/]+)", self.path)
            data = hub.asset(*match.groups()) if match else None
            if data is None:
                return self._send(404, b"not found")
            name = match.group(2)
            start = 0
            if rng:
                start = int(re.fullmatch(r"bytes=(\d+)-", rng).group(1))
                if start >= len(data):
                    return self._send(416, b"")
            body = data[start:]
            self.send_response(206 if rng else 200)
            self.send_header("Content-Length", str(len(body)))
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.end_headers()
            cut = hub.drop_once.pop(name, None)
            if cut is not None:
                self.wfile.write(body[:cut])
                self.wfile.flush()
                # A clean close (FIN) with the body short of Content-Length:
                # the client sees a connection that dropped mid-file.
                self.close_connection = True
                return
            self.wfile.write(body)

        def _send(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


@pytest.fixture
def hub() -> Iterator[FakeGitHub]:
    state = FakeGitHub()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    state.base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------ the release
def _stage(folder: Path, version: str, *, hangar: bytes) -> Path:
    files = {
        "launch.py": LAUNCH_SCRIPT,
        "Verse.exe": b"launcher",
        "Verse/Content/Paks/pakchunk0-Windows.ucas": b"core" * 4000,
        "Verse/Content/Paks/pakchunk4-Windows.ucas": hangar,
        "Verse/version.txt": version.encode(),
    }
    for rel, data in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return folder


def _publish(
    tmp: Path,
    signer: Signer,
    version: str,
    *,
    hangar: bytes,
    previous: Path | None = None,
) -> tuple[Release, Path]:
    out = tmp / f"release-{version}"
    out.mkdir()
    stage = _stage(tmp / f"stage-{version}", version, hangar=hangar)
    full = out / vm.full_asset_name("Win64", version)
    package.make_full(stage, version=version, platform="Win64", out=full, entry="launch.py")
    deltas = []
    if previous is not None:
        old_tree = package.read_payload_tree(previous)
        delta = out / vm.delta_asset_name("Win64", old_tree["version"], version)
        package.make_delta(old_tree, stage, version=version, out=delta, entry="launch.py")
        deltas.append(delta)
    manifest = package.make_release_manifest(full, deltas, tag=f"v{version}")
    assets = {p.name: p.read_bytes() for p in (full, *deltas)}
    assets[vm.manifest_asset_name("Win64")] = manifest
    assets[vm.signature_asset_name("Win64")] = signer.sign(manifest)
    return Release(tag=f"v{version}", assets=assets), full


@pytest.fixture
def signer() -> Signer:
    return Signer()


def _installer(hub: FakeGitHub, signer: Signer, root: Path, **kwargs) -> VerseInstaller:
    options = {
        "root": root,
        "fetcher": HttpFetcher(allow_loopback_http=True),
        "listing_url": f"{hub.base}/releases",
        "app_version": "9.9.9",
        "platform": "Win64",
        "public_keys": signer.public_keys,
        "gpu_supported": True,
    }
    options.update(kwargs)
    return VerseInstaller(**options)


def _run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ A22.7
def test_a_fresh_install_reads_not_installed(tmp_path: Path) -> None:
    installer = VerseInstaller(root=tmp_path / "verse", platform="Win64", app_version="4.2.0")
    assert installer.install_state() == {"status": "not_installed", "version": None}
    assert not (tmp_path / "verse").exists()  # asking never creates anything


def test_no_installer_or_app_update_carries_the_verse() -> None:
    # The update size cap is the one from before the Verse (A22.7: installer
    # size unchanged); the Verse never rides in an installer download.
    assert installer_update.MAX_INSTALLER_BYTES == 1_500_000_000
    source = (REPO / "dodaios/core/installer_update.py").read_text(encoding="utf-8")
    assert "verse" not in source.lower()
    word = re.compile(r"\bverse\b|unreal", re.IGNORECASE)
    for rel in (
        "dodaios.spec",
        "packaging/windows/Dodaios.iss",
        "packaging/windows/build.ps1",
        "packaging/linux/build.sh",
    ):
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        assert not word.search(text), f"{rel} mentions the Verse; installers must not carry it"
    assert not list((REPO / "packaging").rglob("stage_verse*"))


def test_a_machine_without_gpu_is_never_offered_the_download(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, _ = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    installer = _installer(hub, signer, tmp_path / "verse", gpu_supported=lambda: False)
    assert installer.install_state()["status"] == "unsupported"
    with pytest.raises(VerseInstallError, match="cannot run the Verse"):
        _run(installer.offer())
    assert hub.requests == []
    mac = _installer(hub, signer, tmp_path / "verse", platform=None)
    assert mac.install_state()["status"] == "unsupported"


def test_the_card_shows_the_size_before_the_download(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    offer = _run(_installer(hub, signer, tmp_path / "verse").offer())
    assert offer["version"] == "4.2.0"
    assert offer["download_bytes"] == full.stat().st_size
    assert offer["install_bytes"] > 0
    # Only the listing, the manifest and its signature: no package bytes yet.
    assert all("/dl/" not in path or "manifest" in path for path, _ in hub.requests)


def test_download_installs_and_the_installed_verse_launches(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    root = tmp_path / "verse"
    installer = _installer(hub, signer, root)
    seen: list[dict] = []

    async def go() -> dict:
        installer.start_install()
        assert installer.install_state()["status"] == "installing"
        while installer.busy():
            seen.append(installer.progress())
            await asyncio.sleep(0.01)
        return await installer.wait()

    result = _run(go())
    assert result["status"] == "installed" and result["version"] == "4.2.0"
    done = installer.progress()
    assert done["phase"] == "done" and done["percent"] == 100.0
    assert done["total_bytes"] == full.stat().st_size
    state = installer.install_state()
    assert state["status"] == "installed" and state["version"] == "4.2.0"
    assert not list((root / "downloads").iterdir())  # the package is not kept twice
    launched = subprocess.run(
        [sys.executable, *installer.launch_command()],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert launched.returncode == 0 and launched.stdout.strip() == "verse up"


def test_an_interrupted_download_resumes_where_it_stopped(
    hub: FakeGitHub, signer: Signer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("dodaios.verse_host.install.download.RESUME_BACKOFF_S", 0.0)
    release, full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    size = full.stat().st_size
    hub.drop_once[full.name] = size // 3
    installer = _installer(hub, signer, tmp_path / "verse")
    assert _run(installer.install())["version"] == "4.2.0"
    ranges = hub.downloaded(full.name)
    assert ranges[0] is None and ranges[1] == f"bytes={size // 3}-"
    assert installer.install_state()["status"] == "installed"


def test_a_download_stopped_by_an_app_restart_resumes_on_the_next_start(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    root = tmp_path / "verse"
    half = full.stat().st_size // 2
    (root / "downloads").mkdir(parents=True)
    (root / "downloads" / f"{full.name}.part").write_bytes(full.read_bytes()[:half])
    installer = _installer(hub, signer, root)
    assert _run(installer.install())["status"] == "installed"
    assert hub.downloaded(full.name) == [f"bytes={half}-"]


def test_cancel_keeps_the_partial_download_for_the_next_start(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    root = tmp_path / "verse"
    installer = _installer(hub, signer, root)
    gate = asyncio.Event

    async def go() -> None:
        stalled = gate()
        real = installer._fetcher.download_range

        async def stall(url, dest, *, offset, max_bytes, on_chunk=None):
            dest.write_bytes(full.read_bytes()[:1000])
            stalled.set()
            await asyncio.sleep(3600)
            return await real(url, dest, offset=offset, max_bytes=max_bytes, on_chunk=on_chunk)

        installer._fetcher.download_range = stall  # type: ignore[method-assign]
        installer.start_install()
        await stalled.wait()
        installer.cancel()
        await installer.wait()

    _run(go())
    assert installer.progress()["phase"] == "cancelled"
    assert (root / "downloads" / f"{full.name}.part").stat().st_size == 1000
    assert installer.install_state()["status"] == "not_installed"
    fresh = _installer(hub, signer, root)
    assert _run(fresh.install())["status"] == "installed"
    assert hub.downloaded(full.name) == ["bytes=1000-"]


def test_cancel_while_unpacking_waits_for_the_install_to_finish(
    hub: FakeGitHub, signer: Signer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.verse_host.install import payload

    release, _ = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    root = tmp_path / "verse"
    installer = _installer(hub, signer, root)
    entered = threading.Event()
    release_worker = threading.Event()
    real_install = payload.install_full
    calls: list[int] = []

    def slow_install(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release_worker.wait(30)
        return real_install(*args, **kwargs)

    monkeypatch.setattr(payload, "install_full", slow_install)

    async def go() -> dict | None:
        installer.start_install()
        assert await asyncio.to_thread(entered.wait, 30)
        assert installer.progress()["phase"] == "installing"
        # The card's cancel is refused while unpacking.
        assert installer.cancel()["phase"] == "installing"
        await asyncio.sleep(0.05)
        assert installer.busy()
        # Even a hard cancel of the task (app shutdown) waits for the worker.
        installer._task.cancel()
        await asyncio.sleep(0.05)
        assert installer.busy()
        with pytest.raises(VerseInstallError, match="cancel it first"):
            installer.uninstall()
        installer.start_install()  # joins the running job, never a second unpack
        release_worker.set()
        return await installer.wait()

    _run(go())
    assert calls == [1]
    assert not installer.busy()
    state = installer.install_state()
    assert state["status"] == "installed" and state["version"] == "4.2.0"
    assert not list((root / "downloads").iterdir())
    assert installer.uninstall()["status"] == "not_installed"
    assert installer.install_state() == {"status": "not_installed", "version": None}


def test_a_superseded_partial_download_is_removed(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    old, old_full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    new, _ = _publish(tmp_path, signer, "4.2.1", hangar=b"h2" * 5000)
    root = tmp_path / "verse"
    downloads = root / "downloads"
    downloads.mkdir(parents=True)
    # 4.2.0 was interrupted half way (and an old finished package lies around).
    (downloads / f"{old_full.name}.part").write_bytes(old_full.read_bytes()[:500])
    (downloads / old_full.name).write_bytes(b"stale")
    hub.releases = [new, old]
    installer = _installer(hub, signer, root)
    assert _run(installer.install())["version"] == "4.2.1"
    assert not list(downloads.iterdir())


def test_a_tampered_package_is_rejected_and_nothing_is_installed(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    data = bytearray(full.read_bytes())
    data[len(data) // 2] ^= 0xFF  # one flipped byte, same size
    hub.tamper[full.name] = bytes(data)
    root = tmp_path / "verse"
    installer = _installer(hub, signer, root)

    async def go() -> None:
        installer.start_install()
        await installer.wait()

    _run(go())
    progress = installer.progress()
    assert progress["phase"] == "failed" and "NOT installed" in progress["error"]
    assert installer.install_state()["status"] == "not_installed"
    assert not (root / "versions").exists()
    assert not list((root / "downloads").iterdir())  # the bad bytes are gone


def test_a_tampered_or_foreign_manifest_is_rejected(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    name = vm.manifest_asset_name("Win64")
    honest = release.assets[name]
    # Someone swaps in their own package and edits its digest into the manifest.
    hub.tamper[name] = honest.replace(json.loads(honest)["full"]["sha256"].encode(), b"0" * 64, 1)
    installer = _installer(hub, signer, tmp_path / "verse")
    with pytest.raises(VerseInstallError, match="not signed by the Dodaios release key"):
        _run(installer.install())
    # A manifest signed by any other key is refused the same way.
    hub.tamper.clear()
    other = Signer()
    release.assets[vm.signature_asset_name("Win64")] = other.sign(honest)
    with pytest.raises(VerseInstallError, match="not signed by the Dodaios release key"):
        _run(installer.install())
    assert hub.downloaded(full.name) == []  # no package byte before the signature holds
    assert installer.install_state()["status"] == "not_installed"


def test_a_signed_manifest_replayed_on_another_release_is_refused(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, _ = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    release.tag = "v4.3.0"
    hub.releases = [release]
    with pytest.raises(VerseInstallError, match="refusing a replay"):
        _run(_installer(hub, signer, tmp_path / "verse").install())


def test_uninstall_returns_to_not_installed(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, _ = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]
    root = tmp_path / "verse"
    installer = _installer(hub, signer, root)
    _run(installer.install())
    assert installer.install_state()["status"] == "installed"
    result = installer.uninstall()
    assert result["status"] == "not_installed" and result["freed_bytes"] > 0
    assert installer.install_state() == {"status": "not_installed", "version": None}
    assert not root.exists()
    with pytest.raises(VerseInstallError, match="not installed"):
        installer.launch_command()


def test_a_release_newer_than_the_app_is_skipped(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    old, _ = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    new, _ = _publish(tmp_path, signer, "4.3.0", hangar=b"h2" * 5000)
    hub.releases = [new, old]
    installer = _installer(hub, signer, tmp_path / "verse", app_version="4.2.5")
    assert _run(installer.offer())["version"] == "4.2.0"


def test_only_an_installed_verse_updates_and_it_takes_the_delta(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    old, old_full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [old]
    root = tmp_path / "verse"
    installer = _installer(hub, signer, root)
    with pytest.raises(VerseInstallError, match="only an installed Verse updates"):
        _run(installer.update())
    _run(installer.install())
    assert _run(installer.update()) == {"status": "current", "version": "4.2.0"}

    new, new_full = _publish(tmp_path, signer, "4.3.0", hangar=b"h2" * 5000, previous=old_full)
    hub.releases = [new, old]
    result = _run(installer.update())
    assert result["status"] == "updated" and result["kind"] == "delta"
    assert result["version"] == "4.3.0" and result["previous"] == "4.2.0"
    assert hub.downloaded(new_full.name) == []  # the full package was never fetched
    state = installer.install_state()
    assert state["status"] == "installed" and state["version"] == "4.3.0"


def test_a_corrupted_delta_falls_back_to_the_full_package(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    old, old_full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [old]
    root = tmp_path / "verse"
    installer = _installer(hub, signer, root)
    _run(installer.install())
    new, new_full = _publish(tmp_path, signer, "4.3.0", hangar=b"h2" * 5000, previous=old_full)
    hub.releases = [new, old]
    delta_name = vm.delta_asset_name("Win64", "4.2.0", "4.3.0")
    hub.tamper[delta_name] = b"x" * len(new.assets[delta_name])
    result = _run(installer.update())
    assert result["status"] == "updated" and result["kind"] == "full"
    assert layout.read_current(root)["version"] == "4.3.0"


def test_too_little_disk_space_is_said_before_any_download(
    hub: FakeGitHub, signer: Signer, tmp_path: Path
) -> None:
    release, full = _publish(tmp_path, signer, "4.2.0", hangar=b"h1" * 5000)
    hub.releases = [release]

    class Tiny:
        free = 10

    installer = _installer(hub, signer, tmp_path / "verse", disk_usage=lambda _p: Tiny())
    with pytest.raises(VerseInstallError, match="GB free"):
        _run(installer.install())
    assert hub.downloaded(full.name) == []


def test_the_fetcher_refuses_plain_http_outside_tests(hub: FakeGitHub, tmp_path: Path) -> None:
    with pytest.raises(VerseInstallError, match="non-https"):
        _run(HttpFetcher().get_text(f"{hub.base}/releases", max_bytes=1000))

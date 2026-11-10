#!/usr/bin/env python3
"""End-to-end run of the in-app Verse download against a local HTTP source (A22.7).

Takes a real full package (``package.py full``) and optionally deltas, signs the
release manifest with a throwaway Ed25519 key, serves a GitHub-shaped release
list plus the assets over a local range-capable HTTP server, then drives the
real :class:`VerseInstaller` the launcher card drives:

    not_installed -> offer -> download with progress -> verify -> install
    -> launch -> uninstall -> not_installed

The app itself is never started and no production key is touched: the installer
is given the throwaway public key, exactly as the unit tests do.

    python scripts/unreal/ondemand_e2e.py --full Verse-Win64-4.2.0.tar [--launch-seconds 15]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dodaios.verse_host.install import manifest as verse_manifest
from dodaios.verse_host.install.download import HttpFetcher
from dodaios.verse_host.install.service import VerseInstaller
from scripts.unreal import package

TAG_RE = re.compile(r"^Verse-(?P<platform>\w+)-(?P<version>\d+\.\d+\.\d+)\.tar$")


def new_key() -> tuple[Any, str]:
    """A throwaway Ed25519 key and its DER public key as the installer pins it."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, base64.b64encode(der).decode("ascii")


def make_handler(files: dict[str, Path], listing: Any) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path.startswith("/releases"):
                body = json.dumps(listing()).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            path = files.get(self.path.lstrip("/"))
            if path is None:
                self.send_error(404)
                return
            size = path.stat().st_size
            start, end, status = 0, size - 1, 200
            header = self.headers.get("Range")
            if header and (match := re.match(r"bytes=(\d+)-(\d*)", header)):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
                status = 206
            self.send_response(status)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as handle:
                handle.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = handle.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        do_HEAD = do_GET  # noqa: N815

    return Handler


def start_verse(command: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - the installed Verse is the thing under test
        [*command, "-nullrhi", "-unattended", "-nosound", "-NoSplash"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_verse(process: subprocess.Popen[bytes], root: Path) -> None:
    """Stop the launcher stub and the game it spawned (found by its path under ``root``)."""
    import psutil

    if process.poll() is None:
        process.terminate()
    for other in psutil.process_iter(["exe"]):
        exe = other.info.get("exe") or ""
        if exe and Path(exe).is_relative_to(root):
            other.kill()
            other.wait(timeout=15)


async def drive(
    installer: VerseInstaller, report: dict[str, Any], launch_seconds: float | None
) -> None:
    states: list[dict[str, Any]] = []

    def note(label: str, state: dict[str, Any]) -> None:
        entry = {"step": label, "status": state.get("status"), "version": state.get("version")}
        states.append(entry)
        print(f"[e2e] {label}: {state.get('status')} {state.get('version') or ''}")

    note("fresh", installer.install_state())
    offer = await installer.offer()
    report["offer"] = offer
    print(f"[e2e] offer: {offer}")
    installer.start_install()
    seen: list[dict[str, Any]] = []
    while installer.busy():
        progress = installer.progress()
        if not seen or progress != seen[-1]:
            seen.append(dict(progress))
        await asyncio.sleep(0.05)
    result = await installer.wait()
    report["install_result"] = result
    report["progress_samples"] = len(seen)
    report["progress_phases"] = sorted({str(p.get("phase")) for p in seen})
    report["progress_max_bytes"] = max((int(p.get("done_bytes") or 0) for p in seen), default=0)
    note("installed", installer.install_state())
    command = installer.launch_command()
    report["launch_command"] = command
    if launch_seconds is not None:
        started = time.monotonic()
        process = await asyncio.to_thread(start_verse, command)
        await asyncio.sleep(launch_seconds)
        report["launch_alive_after_s"] = process.poll() is None
        report["launch_seconds"] = round(time.monotonic() - started, 1)
        await asyncio.to_thread(stop_verse, process, installer.root)
    note("launched", installer.install_state())
    removed = installer.uninstall()
    report["uninstall_result"] = removed
    note("uninstalled", installer.install_state())
    report["states"] = states


def run(options: argparse.Namespace) -> int:
    full: Path = options.full.resolve()
    match = TAG_RE.match(full.name)
    if not match:
        print(f"{full.name} is not Verse-<Platform>-<version>.tar", file=sys.stderr)
        return 2
    platform, version = match.group("platform"), match.group("version")
    tag = f"v{version}"
    data = package.make_release_manifest(full, [], tag=tag)
    private, public = new_key()
    signature = base64.b64encode(private.sign(data)).decode("ascii")
    work = Path(tempfile.mkdtemp(prefix="verse-e2e-"))
    manifest_path = work / verse_manifest.manifest_asset_name(platform)
    manifest_path.write_bytes(data)
    sig_path = work / verse_manifest.signature_asset_name(platform)
    sig_path.write_text(signature)
    files = {full.name: full, manifest_path.name: manifest_path, sig_path.name: sig_path}
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(files, lambda: []))
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def listing() -> list[dict[str, Any]]:
        return [
            {
                "tag_name": tag,
                "draft": False,
                "prerelease": False,
                "assets": [
                    {"name": n, "browser_download_url": f"{base}/{n}", "size": p.stat().st_size}
                    for n, p in files.items()
                ],
            }
        ]

    server.RequestHandlerClass = make_handler(files, listing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = work / "verse-root"
    installer = VerseInstaller(
        root=root,
        fetcher=HttpFetcher(allow_loopback_http=True),
        listing_url=f"{base}/releases",
        app_version=version,
        platform=platform,
        gpu_supported=True,
        public_keys=[public],
    )
    report: dict[str, Any] = {"package": full.name, "package_bytes": full.stat().st_size}
    started = time.monotonic()
    try:
        asyncio.run(drive(installer, report, None if options.no_launch else options.launch_seconds))
        report["ok"] = [s["status"] for s in report["states"]] == [
            "not_installed",
            "installed",
            "installed",
            "not_installed",
        ] and (options.no_launch or report.get("launch_alive_after_s", False))
    finally:
        server.shutdown()
    report["total_s"] = round(time.monotonic() - started, 1)
    if options.out:
        options.out.parent.mkdir(parents=True, exist_ok=True)
        options.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--launch-seconds", type=float, default=15.0)
    parser.add_argument("--no-launch", action="store_true", help="skip starting the game")
    parser.add_argument("--out", type=Path)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

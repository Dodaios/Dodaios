"""The optional, on-demand Verse install (docs/verse/unreal/work-packages.md WP22).

The installer, a plain ``git clone`` and app updates never carry the Unreal
Verse. It is its own signed package per platform on the release, downloaded
only when the user asks for it, resumably, checked against the signed
manifest, and unpacked into the user data folder. Settings can remove it
again. Only an installed Verse receives (delta) updates.

    installer = VerseInstaller(gpu_supported=probe.supported)
    installer.install_state()     # {"status": "not_installed", ...}
    await installer.offer()       # {"version", "download_bytes", "install_bytes"}
    installer.start_install()     # background task; installer.progress() for the bar
    installer.cancel()            # the .part stays, the next start resumes
    installer.uninstall()         # back to not_installed
"""

from __future__ import annotations

from dodaios.verse_host.install.layout import (
    VERSE_ROOT_ENV,
    VerseInstallError,
    default_root,
    read_current,
    verse_platform,
)
from dodaios.verse_host.install.manifest import (
    ReleaseManifest,
    build_release_manifest,
    parse_release_manifest,
    verify_release_manifest,
)
from dodaios.verse_host.install.service import VerseInstaller, VerseRelease, find_release

__all__ = [
    "VERSE_ROOT_ENV",
    "ReleaseManifest",
    "VerseInstallError",
    "VerseInstaller",
    "VerseRelease",
    "build_release_manifest",
    "default_root",
    "find_release",
    "parse_release_manifest",
    "read_current",
    "verify_release_manifest",
    "verse_platform",
]

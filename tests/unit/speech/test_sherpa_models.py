"""Download and unpacking of the local speech model bundles.

A downloaded archive is untrusted input. It may only write below its own
staging folder, on every supported interpreter: CPython before 3.11.4 has no
``tarfile`` extraction filter, and unpacking there used to fall back to a plain
``extractall``. A pinned bundle must also be the file it was pinned to.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from dodaios.speech import local_models, sherpa_models
from dodaios.speech.local_models import SHERPA_BUNDLES, SherpaBundle

MODEL_ID = "test-voice"
FILES = {
    "test-voice/voice.onnx": b"weights",
    "test-voice/tokens.txt": b"a 1\n",
    "test-voice/espeak-ng-data/lang/de": b"rules",
}


def _regular(name: str, data: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


def _special(name: str, kind: bytes, linkname: str = "") -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = linkname
    return info, b""


def _archive(path: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> Path:
    with tarfile.open(path, "w:bz2") as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data) if data else None)
    return path


def _bundle_archive(path: Path, extra: list[tuple[tarfile.TarInfo, bytes]] | None = None) -> Path:
    members = [_regular(name, data) for name, data in FILES.items()]
    return _archive(path, members + (extra or []))


@pytest.fixture
def no_tar_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """``tarfile`` as CPython 3.11.0 to 3.11.3 ships it: no extraction filters.

    ``extractall`` knows no ``filter`` argument there and writes every member
    where its name points.
    """
    real = tarfile.TarFile.extractall

    def extractall(self, path=".", members=None, *, numeric_owner=False, **kwargs):
        if kwargs:
            unknown = next(iter(kwargs))
            raise TypeError(f"extractall() got an unexpected keyword argument '{unknown}'")
        return real(self, path, members, numeric_owner=numeric_owner, filter="fully_trusted")

    monkeypatch.setattr(tarfile.TarFile, "extractall", extractall)
    monkeypatch.delattr(tarfile, "data_filter")


def _staging(tmp_path: Path) -> Path:
    staging = tmp_path / "models" / ".staging"
    staging.mkdir(parents=True)
    return staging


def _everything_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# --------------------------------------------------------------------------- #
# Unpacking
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("filters", ["with-filter", "without-filter"])
def test_a_bundle_is_unpacked_without_its_wrapper_folder(
    tmp_path: Path, request: pytest.FixtureRequest, filters: str
) -> None:
    if filters == "without-filter":
        request.getfixturevalue("no_tar_filter")
    staging = _staging(tmp_path)
    archive = _bundle_archive(staging / "bundle.tar.bz2")

    sherpa_models._extract_archive(archive, staging)

    assert (staging / "voice.onnx").read_bytes() == b"weights"
    assert (staging / "tokens.txt").read_bytes() == b"a 1\n"
    assert (staging / "espeak-ng-data" / "lang" / "de").read_bytes() == b"rules"
    assert not (staging / "_unpacked").exists()


ESCAPES = ("parent-traversal", "absolute-path", "symlink", "hardlink", "fifo", "device")


def _escaping_member(kind: str, tmp_path: Path) -> tuple[tarfile.TarInfo, bytes]:
    """A member that reaches for something outside the folder it is unpacked into.

    Every target lies inside ``tmp_path``, so a regression writes into the
    test's own folder and nowhere else.
    """
    if kind == "parent-traversal":
        return _regular("test-voice/../../../escaped.txt", b"out")
    if kind == "absolute-path":
        return _regular((tmp_path / "escaped-absolute.txt").as_posix(), b"out")
    if kind == "symlink":
        return _special("test-voice/link", tarfile.SYMTYPE, "../../../escaped.txt")
    if kind == "hardlink":
        return _special("test-voice/hard", tarfile.LNKTYPE, "../../../escaped.txt")
    if kind == "fifo":
        return _special("test-voice/pipe", tarfile.FIFOTYPE)
    return _special("test-voice/dev", tarfile.CHRTYPE)


@pytest.mark.parametrize("kind", ESCAPES)
def test_without_the_tar_filter_nothing_leaves_the_staging_folder(
    tmp_path: Path, no_tar_filter: None, kind: str
) -> None:
    staging = _staging(tmp_path)
    archive = _bundle_archive(staging / "bundle.tar.bz2", [_escaping_member(kind, tmp_path)])

    with pytest.raises(RuntimeError, match="not unpacked"):
        sherpa_models._extract_archive(archive, staging)

    # Whatever was written is below the staging folder, which the caller removes.
    outside = {p for p in _everything_under(tmp_path) if not p.startswith("models/.staging/")}
    assert outside == set()


def test_with_the_tar_filter_a_traversing_member_is_refused(tmp_path: Path) -> None:
    if not hasattr(tarfile, "data_filter"):
        pytest.skip("this interpreter has no extraction filters")
    staging = _staging(tmp_path)
    archive = _bundle_archive(
        staging / "bundle.tar.bz2", [_escaping_member("parent-traversal", tmp_path)]
    )

    with pytest.raises(tarfile.TarError):
        sherpa_models._extract_archive(archive, staging)

    assert not (tmp_path / "models" / "escaped.txt").exists()


def test_a_type_error_while_unpacking_is_not_read_as_a_missing_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The filter exists here; a TypeError from inside the extraction must
    # surface, never start a second, unfiltered pass over the same archive.
    if not hasattr(tarfile, "data_filter"):
        pytest.skip("this interpreter has no extraction filters")
    calls: list[dict[str, object]] = []

    def extractall(self, path=".", members=None, **kwargs):
        calls.append(kwargs)
        raise TypeError("broken member")

    monkeypatch.setattr(tarfile.TarFile, "extractall", extractall)
    staging = _staging(tmp_path)
    archive = _bundle_archive(staging / "bundle.tar.bz2")

    with pytest.raises(TypeError, match="broken member"):
        sherpa_models._extract_archive(archive, staging)

    assert calls == [{"filter": "data"}]


# --------------------------------------------------------------------------- #
# Pinned bundles
# --------------------------------------------------------------------------- #
def _offer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, served: bytes, *, sha256: str
) -> list[str]:
    """Register a test bundle whose download yields ``served``; returns the URLs asked."""
    asked: list[str] = []

    def _download(url: str, target: Path, *, timeout_s: float = 60.0) -> None:
        asked.append(url)
        target.write_bytes(served)

    monkeypatch.setitem(
        local_models.SHERPA_BUNDLES,
        MODEL_ID,
        SherpaBundle(
            model_id=MODEL_ID,
            label="Test voice",
            required_files=("voice.onnx", "tokens.txt", "espeak-ng-data"),
            archive_url="https://example.invalid/test-voice.tar.bz2",
            sha256=sha256,
        ),
    )
    monkeypatch.setattr(sherpa_models, "_download_file", _download)
    return asked


def test_a_pinned_bundle_that_matches_is_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    served = _bundle_archive(tmp_path / "upstream.tar.bz2").read_bytes()
    _offer(monkeypatch, tmp_path, served, sha256=hashlib.sha256(served).hexdigest())

    target = sherpa_models.download_sherpa_model(MODEL_ID, data_dir=str(tmp_path))

    assert target == tmp_path / "models" / MODEL_ID
    assert (target / "voice.onnx").read_bytes() == b"weights"


def test_a_pinned_bundle_that_changed_is_not_unpacked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pinned = _bundle_archive(tmp_path / "pinned.tar.bz2").read_bytes()
    changed = _bundle_archive(
        tmp_path / "changed.tar.bz2", [_regular("test-voice/extra.bin", b"new")]
    ).read_bytes()
    _offer(monkeypatch, tmp_path, changed, sha256=hashlib.sha256(pinned).hexdigest())
    unpacked: list[Path] = []
    monkeypatch.setattr(
        sherpa_models, "_extract_archive", lambda archive, staging: unpacked.append(archive)
    )

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        sherpa_models.download_sherpa_model(MODEL_ID, data_dir=str(tmp_path))

    assert unpacked == []
    models = tmp_path / "models"
    assert not (models / MODEL_ID).exists()
    # No staging folder of the refused download stays behind.
    assert [p.name for p in models.iterdir()] == []


def test_an_unpinned_bundle_is_still_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    served = _bundle_archive(tmp_path / "upstream.tar.bz2").read_bytes()
    _offer(monkeypatch, tmp_path, served, sha256="")

    target = sherpa_models.download_sherpa_model(MODEL_ID, data_dir=str(tmp_path))

    assert (target / "tokens.txt").exists()


def test_every_pin_is_a_sha256() -> None:
    pinned = {bundle.model_id: bundle.sha256 for bundle in SHERPA_BUNDLES.values() if bundle.sha256}

    assert pinned, "at least the two default German and English voices are pinned"
    for model_id, digest in pinned.items():
        assert len(digest) == 64 and set(digest) <= set("0123456789abcdef"), model_id
        assert SHERPA_BUNDLES[model_id].archive_url, model_id


def test_an_archive_pinned_twice_has_one_digest() -> None:
    # The voice engine's model store pins some of the same upstream archives.
    # One file has one digest: renewing a pin in one list only is a mistake.
    from dodaios.voice_engine.models import REGISTRY

    engine_pins = {source.url: source.sha256 for source in REGISTRY.values() if source.sha256}
    shared = [
        bundle
        for bundle in SHERPA_BUNDLES.values()
        if bundle.sha256 and bundle.archive_url in engine_pins
    ]

    assert {bundle.model_id for bundle in shared} >= {
        "vits-piper-de_DE-thorsten-medium",
        "vits-piper-en_US-ryan-medium",
    }
    for bundle in shared:
        assert bundle.sha256 == engine_pins[bundle.archive_url], bundle.model_id

"""Limits of the memory bundle import (ADR-0044).

A bundle someone hands over is untrusted input. The import reads the files a
bundle consists of and nothing else, and it stops at a file count and a size
no real vault comes near, before the archive can fill memory.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from dodaios.memory.vault import MemoryVault, portable
from dodaios.memory.vault.portable import (
    BundleError,
    bundle_files,
    export_bundle,
    import_bundle,
    read_bundle,
)


def _clock() -> str:
    return "2026-03-01T10:00:00+00:00"


@pytest.fixture
def source(tmp_path) -> MemoryVault:
    v = MemoryVault(tmp_path / "a.db", clock=_clock)
    v.remember("I live in Berlin.", "profile", entities=["Berlin"])
    v.remember("Prefers German replies.", "preference", pinned=True)
    yield v
    v.close()


def _zip(files: dict[str, bytes], *, junk: int = 0) -> bytes:
    """A zip of ``files`` plus ``junk`` empty entries no bundle has."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        for index in range(junk):
            zf.writestr(f"junk/{index:07d}", b"")
    return buffer.getvalue()


def _with_extras(files: dict[str, bytes]) -> dict[str, bytes]:
    """A bundle as the "everything" download and an archive tool leave it."""
    return {
        **files,
        "memories.json": b'{"memories": []}',
        "readable/MEMORY.md": b"# My memory\n",
        "__MACOSX/._manifest.json": b"\x00\x05\x16\x07",
        "notes/holiday.bin": b"\x00" * 4096,
    }


def test_only_the_files_of_a_bundle_are_read(source) -> None:
    files = bundle_files(source)

    read = read_bundle(_zip(_with_extras(files)))

    assert set(read) == set(files)
    assert read == files


def test_a_file_no_bundle_has_is_never_opened(source, monkeypatch: pytest.MonkeyPatch) -> None:
    files = bundle_files(source)
    data = _zip(_with_extras(files))
    opened: list[str] = []
    real_open = zipfile.ZipFile.open

    def recording_open(self, name, *args, **kwargs):
        opened.append(name if isinstance(name, str) else name.filename)
        return real_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", recording_open)

    read_bundle(data)

    assert sorted(opened) == sorted(files)


@pytest.mark.parametrize("entries", [20_000, 70_000], ids=["many", "zip64-many"])
def test_a_huge_entry_list_is_refused_before_the_archive_is_opened(
    source, monkeypatch: pytest.MonkeyPatch, entries: int
) -> None:
    # Opening an archive builds one object per entry. A list this long is
    # refused from its declared size alone, so that never starts.
    data = _zip(bundle_files(source), junk=entries)

    def never_opened(*args, **kwargs):
        raise AssertionError("the archive was opened")

    monkeypatch.setattr(zipfile, "ZipFile", never_opened)

    with pytest.raises(BundleError, match="too many files"):
        read_bundle(data)


def test_the_entry_count_is_capped_when_the_list_size_cannot_be_told(
    source, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(portable, "_declared_directory_bytes", lambda data: None, raising=False)
    data = _zip(bundle_files(source), junk=2001)

    with pytest.raises(BundleError, match="too many files"):
        read_bundle(data)


def test_a_bundle_that_unpacks_too_large_in_total_is_refused(
    source, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = bundle_files(source)
    total = sum(len(data) for data in files.values())
    monkeypatch.setattr(portable, "MAX_BUNDLE_TOTAL_BYTES", total - 1, raising=False)

    with pytest.raises(BundleError, match="bundle too large"):
        read_bundle(_zip(files))

    # One byte more room and the same bundle is read.
    monkeypatch.setattr(portable, "MAX_BUNDLE_TOTAL_BYTES", total, raising=False)
    assert set(read_bundle(_zip(files))) == set(files)


def test_a_single_file_over_the_limit_is_refused(source, monkeypatch: pytest.MonkeyPatch) -> None:
    files = bundle_files(source)
    largest = max(len(data) for data in files.values())
    monkeypatch.setattr(portable, "MAX_BUNDLE_FILE_BYTES", largest - 1, raising=False)

    with pytest.raises(BundleError, match="file too large in bundle"):
        read_bundle(_zip(files))


def test_a_file_larger_than_its_header_says_is_refused(
    source, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = bundle_files(source)
    data = _zip(files)
    real_open = zipfile.ZipFile.open

    def lying_open(self, name, *args, **kwargs):
        info = name if isinstance(name, zipfile.ZipInfo) else self.getinfo(name)
        if info.filename == "entities.jsonl":
            return io.BytesIO(b"x" * (info.file_size + 100))
        return real_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", lying_open)

    with pytest.raises(BundleError, match="larger than declared"):
        read_bundle(data)


def test_a_checksum_line_for_a_file_this_version_does_not_read_is_skipped(source) -> None:
    # A later format may list more files. They are not read here, so their
    # lines cannot fail the bundle; every file that is read is still checked.
    files = bundle_files(source)
    extended = dict(files)
    extended["CHECKSUMS"] = files["CHECKSUMS"] + (b"0" * 64 + b"  attachments/photo.bin\n")

    assert set(read_bundle(_zip(extended))) == set(files)

    tampered = dict(extended)
    tampered["entities.jsonl"] = files["entities.jsonl"] + b'{"id": "x"}\n'
    with pytest.raises(BundleError, match="checksum mismatch"):
        read_bundle(_zip(tampered))


def test_a_folder_import_reads_only_the_bundle_files(source, tmp_path) -> None:
    folder = export_bundle(source, tmp_path / "bundle")
    (folder / "notes.txt").write_text("not part of a bundle", encoding="utf-8")
    (folder / "items" / "README.txt").write_text("nor this", encoding="utf-8")
    (folder / "extra" / "deep").mkdir(parents=True)
    (folder / "extra" / "deep" / "blob.bin").write_bytes(b"\x00" * 4096)

    assert set(read_bundle(folder)) == set(bundle_files(source))


def test_a_folder_import_keeps_the_size_limit(
    source, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = export_bundle(source, tmp_path / "bundle")
    monkeypatch.setattr(portable, "MAX_BUNDLE_TOTAL_BYTES", 10, raising=False)

    with pytest.raises(BundleError, match="bundle too large"):
        read_bundle(folder)


def test_a_wrapped_bundle_with_extras_still_imports(source, tmp_path) -> None:
    files = _with_extras(bundle_files(source))
    wrapped = {f"my-memory/{name}": data for name, data in files.items()}

    with MemoryVault(tmp_path / "b.db", clock=_clock) as target:
        report = import_bundle(target, _zip(wrapped))

        assert report.added == 2 and not report.errors
        assert {m.text for m in target.list()} == {"I live in Berlin.", "Prefers German replies."}

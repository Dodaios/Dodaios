"""Export and import of the personal memory vault (ADR-0044)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from dodaios.memory.vault import MemoryVault
from dodaios.memory.vault.portable import (
    BundleError,
    export_bundle,
    export_markdown,
    export_zip_bytes,
    import_bundle,
    read_bundle,
)


def _clock() -> str:
    return "2026-03-01T10:00:00+00:00"


@pytest.fixture
def source(tmp_path) -> MemoryVault:
    v = MemoryVault(tmp_path / "a.db", clock=_clock)
    old = v.remember("I live in Hamburg.", "profile", entities=["Hamburg"]).memory
    v.supersede(old.id, "I live in Berlin.", entities=["Berlin"])
    v.remember("Prefers German replies.", "preference", pinned=True)
    gone = v.remember("Secret crush on Alex.", "relationship", entities=["Alex"]).memory
    v.forget(gone.id)
    yield v
    v.close()


def test_folder_round_trip_is_lossless_and_idempotent(source, tmp_path):
    bundle = export_bundle(source, tmp_path / "bundle")
    assert (bundle / "manifest.json").exists()
    assert (bundle / "items" / "profile.jsonl").exists()

    with MemoryVault(tmp_path / "b.db", clock=_clock) as target:
        first = import_bundle(target, bundle)
        assert first.added == 3 and not first.errors
        assert {m.text for m in target.list()} == {"I live in Berlin.", "Prefers German replies."}
        current = next(m for m in target.list() if m.kind == "profile")
        assert [m.text for m in target.history(current.id)] == [
            "I live in Hamburg.",
            "I live in Berlin.",
        ]
        assert any(m.pinned for m in target.list())

        second = import_bundle(target, bundle)
        assert second.added == 0 and second.skipped == 3
        assert target.stats()["all_versions"] == 3


def test_tombstones_travel_and_erase_on_the_other_side(source, tmp_path):
    with MemoryVault(tmp_path / "b.db", clock=_clock) as target:
        target.remember("Secret crush on Alex.", "relationship")
        import_bundle(target, export_zip_bytes(source))
        assert target.search("Alex") == []
        assert target.remember(
            "Secret crush on Alex.", "relationship", origin="inferred"
        ).action == ("blocked")


def test_zip_file_export_and_wrapped_folder_zip(source, tmp_path):
    path = export_bundle(source, tmp_path / "memory.zip")
    assert read_bundle(path)["manifest.json"]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in read_bundle(path).items():
            zf.writestr(f"my-memory/{name}", data)
    assert "manifest.json" in read_bundle(buffer.getvalue())


def test_tampered_bundle_is_rejected(source, tmp_path):
    bundle = export_bundle(source, tmp_path / "bundle")
    items = bundle / "items" / "profile.jsonl"
    items.write_text(
        items.read_text(encoding="utf-8").replace("Berlin", "Munich"), encoding="utf-8"
    )
    with pytest.raises(BundleError, match="checksum"):
        read_bundle(bundle)


def test_foreign_or_unsafe_bundles_are_rejected(tmp_path):
    with pytest.raises(BundleError):
        read_bundle(b"not a zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "other", "version": "1"}))
    with pytest.raises(BundleError, match="format"):
        read_bundle(buffer.getvalue())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(BundleError, match="unsafe"):
        read_bundle(buffer.getvalue())


def test_markdown_export_lists_current_memories(source, tmp_path):
    out = export_markdown(source, tmp_path / "md")
    index = (out / "MEMORY.md").read_text(encoding="utf-8")
    assert "[About me](profile.md)" in index
    profile = (out / "profile.md").read_text(encoding="utf-8")
    assert "I live in Berlin." in profile and "Hamburg" not in profile
    assert "Alex" not in "".join(p.read_text(encoding="utf-8") for p in out.iterdir())

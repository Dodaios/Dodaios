"""The search model: one identity, a checked download, a guarded session."""
from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from dodaios.core.paths import repo_root
from dodaios.memory.wiki import semantic_model
from dodaios.memory.wiki.semantic_model import ModelFile, SemanticEncoder

FILES = {"tokenizer.json": b"vocabulary", "onnx/model_quantized.onnx": b"weights" * 100}


@pytest.fixture()
def small_model(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Shrink the pinned files so a test can download and store them."""
    entries = tuple(
        ModelFile(path, len(data), hashlib.sha256(data).hexdigest())
        for path, data in FILES.items()
    )
    monkeypatch.setattr(semantic_model, "MODEL_FILES", entries)
    monkeypatch.setattr(semantic_model, "DOWNLOAD_BYTES", sum(item.size for item in entries))
    return dict(FILES)


class _FakeStream:
    """What ``httpx.stream`` hands back, serving bytes from a dict."""

    def __init__(self, served: dict[str, bytes], requested: list[str], url: str) -> None:
        requested.append(url)
        self._data = next(data for path, data in served.items() if url.endswith(path))

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, _chunk_size: int) -> Any:
        yield self._data[: len(self._data) // 2]
        yield self._data[len(self._data) // 2 :]


def _serve(monkeypatch: pytest.MonkeyPatch, served: dict[str, bytes]) -> list[str]:
    requested: list[str] = []

    def stream(_method: str, url: str, **_kwargs: Any) -> _FakeStream:
        return _FakeStream(served, requested, url)

    monkeypatch.setattr(httpx, "stream", stream)
    return requested


def test_python_and_browser_use_the_same_model_revision() -> None:
    source = (
        repo_root()
        / "dodaios/ui/web/frontend/src/components/agentic/sidePanel/agentSearch.ts"
    ).read_text(encoding="utf-8")
    model = re.search(r'AGENT_SEARCH_MODEL = "([^"]+)"', source)
    revision = re.search(r'AGENT_SEARCH_REVISION = "([^"]+)"', source)
    assert model and revision
    assert semantic_model.MODEL_REPO == model.group(1)
    assert semantic_model.MODEL_REVISION == revision.group(1)


def test_the_model_is_present_only_when_every_file_is_complete(
    tmp_path: Path, small_model: dict[str, bytes]
) -> None:
    assert not semantic_model.model_present(tmp_path)
    root = semantic_model.model_dir(tmp_path)
    (root / "onnx").mkdir(parents=True)
    (root / "tokenizer.json").write_bytes(small_model["tokenizer.json"])
    (root / "onnx" / "model_quantized.onnx").write_bytes(b"cut off")
    assert not semantic_model.model_present(tmp_path), "a partial file is not the model"
    (root / "onnx" / "model_quantized.onnx").write_bytes(small_model["onnx/model_quantized.onnx"])
    assert semantic_model.model_present(tmp_path)


def test_download_fetches_the_pinned_revision_and_reports_progress(
    tmp_path: Path, small_model: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    requested = _serve(monkeypatch, small_model)
    seen: list[tuple[int, int]] = []

    semantic_model.download_model(tmp_path, progress=lambda done, total: seen.append((done, total)))

    assert semantic_model.model_present(tmp_path)
    assert all(semantic_model.MODEL_REVISION in url for url in requested)
    assert seen[-1] == (semantic_model.DOWNLOAD_BYTES, semantic_model.DOWNLOAD_BYTES)
    assert not list(semantic_model.model_dir(tmp_path).rglob("*.part"))


def test_download_skips_files_that_are_already_there(
    tmp_path: Path, small_model: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, small_model)
    semantic_model.download_model(tmp_path)
    requested = _serve(monkeypatch, small_model)

    semantic_model.download_model(tmp_path)

    assert requested == []


def test_a_damaged_download_is_refused_and_leaves_nothing_behind(
    tmp_path: Path, small_model: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, {**small_model, "tokenizer.json": b"vocabulerY"})

    with pytest.raises(RuntimeError, match="checksum"):
        semantic_model.download_model(tmp_path)

    assert not semantic_model.model_present(tmp_path)
    assert not list(semantic_model.model_dir(tmp_path).rglob("*"))[1:], "no file, no .part"


def test_a_file_larger_than_the_pinned_one_is_cut_off(
    tmp_path: Path, small_model: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, {**small_model, "tokenizer.json": b"vocabulary" * 1000})

    with pytest.raises(RuntimeError, match="larger than the pinned file"):
        semantic_model.download_model(tmp_path)

    assert not list(semantic_model.model_dir(tmp_path).rglob("*.part"))


def test_a_download_that_is_told_to_stop_leaves_no_half_file(
    tmp_path: Path, small_model: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, small_model)

    class Stop(Exception):
        pass

    def progress(_done: int, _total: int) -> None:
        raise Stop

    with pytest.raises(Stop):
        semantic_model.download_model(tmp_path, progress=progress)

    assert not semantic_model.model_present(tmp_path)
    assert not list(semantic_model.model_dir(tmp_path).rglob("*.part"))


class _Tokenizer:
    def encode(self, text: str, *, max_tokens: int) -> list[int]:
        return [0, *range(10, 10 + len(text.split())), 2][:max_tokens]


class _Session:
    """Returns, per token, a vector whose first value is the token id."""

    def __init__(self) -> None:
        self.batches: list[int] = []

    def run(self, _outputs: Any, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        ids = feeds["input_ids"]
        self.batches.append(ids.shape[0])
        hidden = np.zeros((*ids.shape, semantic_model.EMBEDDING_DIMENSIONS), dtype=np.float32)
        hidden[:, :, 0] = ids
        hidden[:, :, 1] = 1.0
        return [hidden]


class _StubEncoder(SemanticEncoder):
    """The real encoder with the native session swapped for a recording one."""

    def __init__(self) -> None:
        super().__init__()
        self.loads = 0
        self.session = _Session()

    def _load(self) -> tuple[Any, Any]:
        self.loads += 1
        self._tokenizer = _Tokenizer()
        self._session = self.session
        self._input_names = frozenset({"input_ids", "attention_mask"})
        return self._session, self._tokenizer


def test_vectors_are_unit_length_and_ignore_padding() -> None:
    encoder = _StubEncoder()
    vectors = encoder.encode(["one", "one two three four"])
    assert vectors.shape == (2, semantic_model.EMBEDDING_DIMENSIONS)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    # "one" is ids [0, 10, 2]: mean 4. Padding to five tokens must not drag it down.
    alone = encoder.encode(["one"])
    assert np.allclose(vectors[0], alone[0])


def test_many_texts_are_encoded_in_small_batches() -> None:
    encoder = _StubEncoder()
    vectors = encoder.encode([f"text {n}" for n in range(19)])
    assert vectors.shape[0] == 19
    assert encoder.session.batches == [8, 8, 3]
    assert encoder.loads == 1


def test_the_turn_path_never_waits_for_a_model_that_is_not_loaded() -> None:
    encoder = _StubEncoder()
    assert encoder.encode(["question"], wait=False) is None
    encoder._loader.join(timeout=5)
    assert encoder.loaded
    assert encoder.encode(["question"], wait=False) is not None


def test_a_second_caller_does_not_enter_the_session() -> None:
    encoder = _StubEncoder()
    encoder.encode(["warm"])
    encoder._gate.lock.acquire()
    try:
        assert encoder.encode(["question"], wait=False) is None
    finally:
        encoder._gate.lock.release()
    assert encoder.encode(["question"], wait=False) is not None


def test_a_session_that_stopped_answering_is_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    encoder = _StubEncoder()
    encoder.encode(["warm"])
    wedged = encoder._gate
    wedged.lock.acquire()  # a caller that never comes back
    wedged.held_since = 0.0
    monkeypatch.setattr(semantic_model.time, "monotonic", lambda: 10_000.0)

    assert encoder.encode(["question"], wait=False) is None
    assert encoder._gate is not wedged, "the fresh path gets a fresh lock"
    assert not encoder.loaded

    assert encoder.encode(["question"]) is not None
    assert encoder.loads == 2

    # The stuck caller coming back late must not disturb the new holder.
    encoder._gate.held_since = 123.0
    wedged.held_since = None
    wedged.lock.release()
    assert encoder._gate.held_since == 123.0


def test_close_never_waits_for_a_caller_inside_the_session() -> None:
    encoder = _StubEncoder()
    encoder.encode(["warm"])
    encoder._gate.lock.acquire()  # someone is encoding, or stuck
    try:
        encoder.close()  # returns at once instead of queueing behind it
    finally:
        encoder._gate.lock.release()
    assert not encoder.loaded


def test_a_closed_encoder_stays_closed() -> None:
    encoder = _StubEncoder()
    encoder.encode(["warm"])
    encoder.close()

    assert encoder.encode(["question"], wait=False) is None
    with pytest.raises(RuntimeError, match="switched off"):
        encoder.encode(["question"])
    encoder.warm_up()
    assert not encoder.loaded
    assert encoder.loads == 1, "nothing reloads a model the user switched off"


def test_concurrent_callers_are_serialised() -> None:
    encoder = _StubEncoder()
    inside = 0
    peak = 0
    guard = threading.Lock()
    original = encoder.session.run

    def run(outputs: Any, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        nonlocal inside, peak
        with guard:
            inside += 1
            peak = max(peak, inside)
        try:
            return original(outputs, feeds)
        finally:
            with guard:
                inside -= 1

    encoder.session.run = run  # type: ignore[method-assign]
    threads = [threading.Thread(target=encoder.encode, args=(["a b c"],)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert peak == 1

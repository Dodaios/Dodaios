"""The local sentence encoder behind the wiki's semantic search.

One multilingual model, the same one the terminal search in the Agentic IDE
runs in the browser: 384-dimensional sentence vectors for about fifty
languages, quantized, 135 MB on disk. It is not part of the install. The user
switches semantic search on, the two files are fetched once from the pinned
revision, checked against their SHA-256, and from then on everything runs on
this machine; no page text ever leaves it.

Three things live here because they describe the same artefact:

* where the model sits on disk and whether it is complete (:func:`model_dir`,
  :func:`model_present`),
* how it gets there (:func:`download_model`),
* how text becomes vectors (:class:`SemanticEncoder`).

The encoder owns a native inference session. A native session must never be
entered by two callers at once, and a caller on the turn path must never queue
behind a slow one (AP-24): :meth:`SemanticEncoder.encode` therefore takes a
per-instance lock, the turn path asks without waiting, and
:meth:`SemanticEncoder.recover` drops a session that stopped answering so the
next call builds a fresh one.
"""
from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dodaios.memory.wiki.db_path import resolve_wiki_db_path

log = logging.getLogger(__name__)

#: Model identity. ``tests/unit/memory/wiki/test_semantic_model.py`` pins these
#: to the constants of the browser-side terminal search so the app never ends
#: up with two different search models.
MODEL_REPO = "Xenova/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "2c4055b12046f11709e9df2c122e59ffbdc2f900"
EMBEDDING_DIMENSIONS = 384

#: The model reads at most this many tokens of one text.
MAX_TOKENS = 128

_FILE_URL = "https://huggingface.co/{repo}/resolve/{revision}/{path}"
_CHUNK_BYTES = 1 << 20

#: Texts encoded per inference call. Small on purpose: one call is the unit a
#: waiting query has to sit out, and a batch pads every text to its longest.
_BATCH_SIZE = 8

#: A lock held this long is not a slow batch any more, it is a session that
#: stopped answering. A batch of eight texts takes well under ten seconds on a
#: slow laptop core.
_WEDGE_SECONDS = 120.0

#: Pause between two batches of one call. A lock that is released and taken
#: again at once by the same thread can starve every other caller for a whole
#: index run; this gap is what lets a waiting query or page update in.
_YIELD_SECONDS = 0.002


@dataclass(frozen=True, slots=True)
class ModelFile:
    """One file of the pinned model revision."""

    path: str
    size: int
    sha256: str


MODEL_FILES: tuple[ModelFile, ...] = (
    ModelFile(
        "tokenizer.json",
        17_082_913,
        "b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441",
    ),
    ModelFile(
        "onnx/model_quantized.onnx",
        118_308_126,
        "66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc",
    ),
)

DOWNLOAD_BYTES = sum(item.size for item in MODEL_FILES)


def model_dir(data_dir: str | Path | None = None) -> Path:
    """Folder that holds the model, next to the wiki database."""
    return resolve_wiki_db_path(data_dir).parent / "models" / "wiki-semantic-search"


def model_present(data_dir: str | Path | None = None) -> bool:
    """True when every model file is on disk with its full size.

    Size, not hash: this runs on status polls, and hashing 135 MB there would
    be the heavy work a status read must not do. The hash is checked once, at
    download time, before a file is moved into place.
    """
    root = model_dir(data_dir)
    try:
        return all((root / item.path).stat().st_size == item.size for item in MODEL_FILES)
    except OSError:  # a missing file is the answer "not present", not a fault
        return False


def runtime_available() -> bool:
    """True when this install can run the model at all.

    The inference runtime ships with the base install wherever a prebuilt
    package exists for the platform. Where none exists the switch says so
    instead of offering a download that could never be used.
    """
    try:
        return (
            importlib.util.find_spec("onnxruntime") is not None
            and importlib.util.find_spec("numpy") is not None
        )
    except Exception as exc:  # noqa: BLE001 - a broken sys.path is "not available"
        log.debug("semantic search runtime probe failed: %s", exc)
        return False


def download_model(
    data_dir: str | Path | None = None,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Fetch the model files that are missing. Raises with a usable message.

    Each file is streamed to a ``.part`` sibling, hashed while it arrives and
    moved into place only when the hash matches, so an interrupted or tampered
    download can never be mistaken for the model. ``progress`` receives the
    bytes fetched so far and the total over all files.
    """
    import httpx

    root = model_dir(data_dir)
    done = 0
    for item in MODEL_FILES:
        target = root / item.path
        try:
            if target.stat().st_size == item.size:
                done += item.size
                continue
        except OSError:  # not on disk yet, which is what this function is here to fix
            pass
        target.parent.mkdir(parents=True, exist_ok=True)
        # The process id keeps two running copies of the app from writing
        # into each other's half-finished file.
        partial = target.with_name(f"{target.name}.{os.getpid()}.part")
        digest = hashlib.sha256()
        received = 0
        url = _FILE_URL.format(repo=MODEL_REPO, revision=MODEL_REVISION, path=item.path)
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(_CHUNK_BYTES):
                        received += len(chunk)
                        if received > item.size:
                            raise RuntimeError(
                                f"{item.path} is larger than the pinned file. Try again."
                            )
                        handle.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if progress is not None:
                            progress(done, DOWNLOAD_BYTES)
            if digest.hexdigest() != item.sha256:
                raise RuntimeError(
                    f"{item.path} arrived damaged (checksum mismatch). Try again."
                )
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)


@dataclass(slots=True)
class _Gate:
    """The session's lock and the moment its current holder took it.

    One object, so that replacing a session that stopped answering replaces
    both at once: a thread still stuck in the old session keeps the old gate
    and can never clear the timestamp of whoever holds the new one.
    """

    lock: threading.Lock = field(default_factory=threading.Lock)
    held_since: float | None = None


class SemanticEncoder:
    """Text to unit-length sentence vectors, on this machine's CPU."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = data_dir
        self._gate = _Gate()
        self._session: Any = None
        self._tokenizer: Any = None
        self._input_names: frozenset[str] = frozenset()
        self._loader: threading.Thread | None = None
        self._closed = False

    @property
    def loaded(self) -> bool:
        return self._session is not None

    def warm_up(self) -> None:
        """Load the model on a background thread; returns at once."""
        if self._closed or self._session is not None:
            return
        if self._loader is not None and self._loader.is_alive():
            return
        self._loader = threading.Thread(
            target=self._load_quietly, name="wiki-semantic-load", daemon=True
        )
        self._loader.start()

    def encode(self, texts: Sequence[str], *, wait: bool = True) -> Any | None:
        """Vectors for *texts* as a ``(len(texts), 384)`` float32 array.

        ``wait=False`` is the turn path's contract: when the model is not
        loaded yet or another caller is inside the session, return ``None``
        right away. The caller then answers without semantic hits; a turn
        never waits for a model.
        """
        import numpy as np

        if not texts:
            return np.zeros((0, EMBEDDING_DIMENSIONS), dtype=np.float32)
        if not wait and self._session is None:
            self.warm_up()
            return None
        rows: list[Any] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            if start:
                time.sleep(_YIELD_SECONDS)
            batch = self._encode_batch(texts[start : start + _BATCH_SIZE], wait=wait)
            if batch is None:
                return None
            rows.append(batch)
        return np.concatenate(rows, axis=0)

    def recover(self) -> None:
        """Drop a session that stopped answering, together with its lock.

        A thread stuck inside the old session keeps the old objects alive and
        can never block the fresh path; the next ``encode`` loads a new model
        under a new lock.
        """
        log.warning("Semantic search encoder stopped answering; rebuilding it on next use.")
        self._session = None
        self._tokenizer = None
        self._gate = _Gate()

    def close(self) -> None:
        """Retire this encoder and let go of the model. Never waits.

        It does not take the session lock: whoever is inside the session keeps
        its own references and finishes its batch, and a session that stopped
        answering must not be able to hold a shutdown up. A closed encoder
        stays closed; switching the search on again builds a new one.
        """
        self._closed = True
        self._session = None
        self._tokenizer = None

    def _encode_batch(self, texts: Sequence[str], *, wait: bool) -> Any | None:
        import numpy as np

        gate = self._gate
        if not gate.lock.acquire(blocking=wait):
            held_since = gate.held_since
            if held_since is not None and time.monotonic() - held_since > _WEDGE_SECONDS:
                self.recover()
            return None
        try:
            gate.held_since = time.monotonic()
            if self._closed:
                if wait:
                    raise RuntimeError("semantic search was switched off")
                return None
            session, tokenizer = self._session, self._tokenizer
            if session is None or tokenizer is None:
                session, tokenizer = self._load()
            encoded = [tokenizer.encode(text, max_tokens=MAX_TOKENS) for text in texts]
            width = max(len(ids) for ids in encoded)
            input_ids = np.zeros((len(encoded), width), dtype=np.int64)
            mask = np.zeros((len(encoded), width), dtype=np.int64)
            for row, ids in enumerate(encoded):
                input_ids[row, : len(ids)] = ids
                mask[row, : len(ids)] = 1
            feeds = {"input_ids": input_ids, "attention_mask": mask}
            if "token_type_ids" in self._input_names:
                feeds["token_type_ids"] = np.zeros_like(input_ids)
            hidden = session.run(None, feeds)[0]
            weights = mask[:, :, None].astype(np.float32)
            pooled = (hidden * weights).sum(axis=1) / weights.sum(axis=1)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            return (pooled / np.maximum(norms, 1e-12)).astype(np.float32)
        finally:
            gate.held_since = None
            gate.lock.release()

    def _load_quietly(self) -> None:
        try:
            with self._gate.lock:
                if self._session is None and not self._closed:
                    self._load()
        except Exception as exc:  # noqa: BLE001 - the next encode retries and reports
            log.warning("Semantic search model could not be loaded: %s", exc)

    def _load(self) -> tuple[Any, Any]:
        """Build the session and tokenizer; the caller holds the gate."""
        import onnxruntime

        from dodaios.memory.wiki.semantic_tokenizer import UnigramTokenizer

        root = model_dir(self._data_dir)
        options = onnxruntime.SessionOptions()
        # Two threads at most: retrieval shares the machine with speech
        # recognition and must not take every core for a background index run.
        options.intra_op_num_threads = min(2, os.cpu_count() or 1)
        options.inter_op_num_threads = 1
        started = time.monotonic()
        tokenizer = UnigramTokenizer.from_file(root / "tokenizer.json")
        session = onnxruntime.InferenceSession(
            str(root / "onnx" / "model_quantized.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = frozenset(item.name for item in session.get_inputs())
        if not self._closed:
            self._tokenizer = tokenizer
            self._session = session
        log.info("Semantic search model loaded in %.1fs", time.monotonic() - started)
        return session, tokenizer


__all__ = [
    "DOWNLOAD_BYTES",
    "EMBEDDING_DIMENSIONS",
    "MAX_TOKENS",
    "MODEL_FILES",
    "MODEL_REPO",
    "MODEL_REVISION",
    "ModelFile",
    "SemanticEncoder",
    "download_model",
    "model_dir",
    "model_present",
    "runtime_available",
]

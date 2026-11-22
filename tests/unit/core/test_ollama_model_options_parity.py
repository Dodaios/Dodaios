"""Parity test for the layers that share the per-model Ollama option vocabulary
(five-layer pattern, AP-4).

1. ``dodaios/core/config.py::OLLAMA_MODEL_OPTION_KEYS``      — the tuple (source of truth)
2. ``dodaios/core/config.py::OllamaModelOptions``            — the Pydantic fields
3. ``dodaios/brain/ollama_profiles.py::BAKEABLE_KEYS``       — a subset the profile bakes
4. the route body (``OllamaModelOptionsBody`` in ``local_models_routes.py``)
   — checked when that module exists, so the chunk that adds the routes
   inherits the gate without touching this file.

A drift shows up here as one failing test instead of a knob the sheet offers
and the writer refuses, or a key the writer accepts and the plugin never reads.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from dodaios.brain.ollama_profiles import BAKEABLE_KEYS
from dodaios.core.config import OLLAMA_MODEL_OPTION_KEYS, OllamaModelOptions

REPO_ROOT = Path(__file__).resolve().parents[3]
def test_the_tuple_has_no_duplicates() -> None:
    assert len(set(OLLAMA_MODEL_OPTION_KEYS)) == len(OLLAMA_MODEL_OPTION_KEYS)


def test_pydantic_fields_match_the_tuple_in_order() -> None:
    assert tuple(OllamaModelOptions.model_fields) == OLLAMA_MODEL_OPTION_KEYS


def test_bakeable_keys_are_a_subset_of_the_tuple() -> None:
    assert set(BAKEABLE_KEYS) <= set(OLLAMA_MODEL_OPTION_KEYS)
    # The per-request channel is exactly the complement.
    assert set(OLLAMA_MODEL_OPTION_KEYS) - set(BAKEABLE_KEYS) == {
        "num_predict",
        "temperature",
        "keep_alive",
        "think",
    }


def test_route_body_matches_when_the_routes_exist() -> None:
    """Chunk 4 adds ``OllamaModelOptionsBody``; until then this is a no-op."""
    try:
        module = importlib.import_module("dodaios.ui.web.local_models_routes")
    except ImportError:
        return
    body = getattr(module, "OllamaModelOptionsBody", None)
    if body is None:
        return
    assert tuple(body.model_fields) == OLLAMA_MODEL_OPTION_KEYS

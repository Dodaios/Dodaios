"""Geometry collections from `SM_<Piece>_Frac` exports (art-pipeline 13).

Reserved entry point of the frozen layout (art-pipeline 10.1). It lands with
WP06 (its first spike proves this route); until then `run()` fails loudly instead of doing nothing.
"""

from __future__ import annotations

OWNER_NOTE = (
    "verse_pipeline.geometry_collections lands with WP06 (its first spike proves this route)"
)


def run(*_args, **_kwargs) -> dict:
    raise NotImplementedError(OWNER_NOTE)

"""Texture import from `verse.import/1` texture records (art-pipeline 6.4).

Reserved entry point of the frozen layout (art-pipeline 10.1). It lands with
the first package that creates a texture set; until then `run()` fails
loudly instead of doing nothing.
"""

from __future__ import annotations

OWNER_NOTE = (
    "verse_pipeline.import_textures lands with the first package that creates a texture set"
)


def run(*_args, **_kwargs) -> dict:
    raise NotImplementedError(OWNER_NOTE)

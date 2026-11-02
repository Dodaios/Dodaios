"""Ownership of changed assets and external actors (art-pipeline 9).

Reserved entry point of the frozen layout (art-pipeline 10.1). It lands with
WP10 with the `unreal-build` lane; until then `run()` fails loudly instead of doing nothing.
"""

from __future__ import annotations

OWNER_NOTE = "verse_pipeline.validate_ownership lands with WP10 with the unreal-build lane"


def run(*_args, **_kwargs) -> dict:
    raise NotImplementedError(OWNER_NOTE)

"""Material instances from `verse.mi/1` recipes (art-pipeline 7).

Reserved entry point of the frozen layout (art-pipeline 10.1). It lands with
WP14, once the master materials exist; until then `run()` fails loudly instead of doing nothing.
"""

from __future__ import annotations

OWNER_NOTE = "verse_pipeline.materials lands with WP14, once the master materials exist"


def run(*_args, **_kwargs) -> dict:
    raise NotImplementedError(OWNER_NOTE)

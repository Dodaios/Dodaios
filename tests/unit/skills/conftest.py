"""Skills-suite import ordering guard.

Several modules under ``dodaios.skills.authoring`` / ``dodaios.core.self_mod``
participate in a latent import cycle
(``self_mod`` -> ``config`` -> ``brain`` -> ``voice.echo_confirmation`` ->
``self_mod``). The cycle is harmless once ``dodaios.core.config`` has finished
loading first, which is what happens implicitly when the full suite runs. But a
test module that imports ``dodaios.skills.authoring`` in isolation triggers the
cycle before ``config`` is warm and fails collection with a confusing
``cannot import name 'PendingMutation'`` error.

Importing ``dodaios.core.config`` here — at skills-suite collection time, before
any test module is imported — resolves the cycle deterministically for every
skills test, isolated or not. Importing config has no side effects (it only
defines classes/functions).
"""
from __future__ import annotations

import dodaios.core.config  # noqa: F401  (import-for-side-effect: warm the cycle)

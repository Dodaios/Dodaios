"""WP14 editor Python: the masters, the weapon import finish, the A14 checks and lookdev.

These modules run inside the headless Unreal editor next to
`verse_pipeline` (they import it for paths and records). They live with
WP14's art because WP14 owns them; the pipeline entry points that call
them (`import_art.py`, `verse_pipeline.cli`) belong to the integration owner.
The pure parts (graph text, plans, checks) are tested with pytest.
"""

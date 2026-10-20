"""Build and export both drones; writes their manifest entries to the cache.

Run: python scripts/verse/blender.py run --no-lock art/verse/characters/build_drones.py
"""

from characters import common as C
from characters import drones

C.reset_scene()
entries = drones.build_drones(C.OUT_DIR)
drones.write_manifest(entries, C.CACHE / "drones_manifest.json")
for e in entries.values():
    print(f"[drones] {e['id']}: {e['triangles']} tris, {e['bytes']} bytes", list(e["clips"]))

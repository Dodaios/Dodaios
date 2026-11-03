"""The Unreal hangar arena (WP11) as code: layout, nav, flow and placements.

Pure Python (numpy and scipy, no bpy, no unreal). `layout` holds every box of
the hangar shell, the five arena zones and the armoury in plan metres;
`nav` turns the walk surfaces into a 2.5D grid graph; `flow` measures
sightlines, spawn distances and time to contact on it; `placements` writes
the `verse.placement/1` documents (art-pipeline 4). The spec the numbers
come from is docs/verse/unreal/arena.md.
"""

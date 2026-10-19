---
name: game-art-pipeline
description: Develop or redesign Dodaios world art, buildings, characters and 3D assets through an authored Blender reference scene, runtime review and controlled asset rollout. Use for game-art production and world redesign, not ordinary UI copy or behaviour-only bug fixes.
---

`docs/agent-society/game-art-pipeline.md` is the binding production standard; read it before planning. Start a study with `python scripts/art_pipeline.py init <study-id>`, keep the editable Blender sources, export through the manifest-driven exporter, and leave shipped assets untouched until the reference is verified in the running app. No user sign-off is needed between the reference and the family rollout. Never revive a rejected design or promote review GLBs into the production catalog.

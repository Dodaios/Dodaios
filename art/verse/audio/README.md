# Verse audio (WP19)

Sound for the Unreal Verse, built as code. Nothing recorded is committed:
synthesised sounds are computed here, CC0 recordings are read from the files
the ledger (`art/verse/LICENSES.md`) cites, and only the imported `.uasset`
files under `unreal/Verse/Content/Verse/Audio/` enter git (Git LFS).

| File | Job |
|---|---|
| `dsp.py` | Seeded DSP primitives (noise, filters, modes, room responses) |
| `recipes.py` | One recipe per sound family: weapon layers, bolts, impacts on the 8 materials, footsteps per surface, foley, reloads, melee, finisher, destruction per piece class, debris, drones, gadgets, beds, UI |
| `build_audio.py` | Renders every variant of `unreal/Verse/Data/audio/cues.json` into `art/verse/.cache/audio/` (ignored) |
| `import_audio.py` | Build, then import under the machine lock (`editor/import_sounds.py` in the headless editor) into `SW_*` sound waves and `DA_AudioCues`, then the licence audit |
| `loudness.py` | ITU-R BS.1770-4 integrated loudness and true peak |
| `reference_mix.py` | Renders the reference duel replay (`Data/audio/reference_duel.json`) with the runtime mix rules and checks A19.4 (-16 LUFS within 1 LU, true peak at most -1 dBTP) |
| `audit_licences.py` | A19.6: every sound cites `own` or ledger rows whose SHA-256 matches |
| `tests/` | pytest for all of the above |

Runtime side: `unreal/Verse/Source/VerseUI/{Public,Private}/Audio/`
(`UVerseAudioSubsystem`). Rules it keeps:

- A sound of anyone but the listener is attenuated to exactly the
  `DA_Audibility` range of its `Noise.*` tag, the range the bot hears it at
  (fairness F6). Sounds the bot cannot hear (crouch steps, lean, equip) play
  only for their own player. The listener's own bolt impacts are shooter
  feedback (cue `range_m`), as the bot gets its own hit confirms.
- At most 64 voices; a cue over its own limit replaces its oldest voice, over
  the global cap the lowest-priority voice is stolen.
- Occlusion is traced through destructible pieces with the destruction query,
  which honours holes and breaches, so opening a wall opens the sound; loops
  re-trace every 0.25 s.
- Hidden or dormant: muted at once; shown again: a 150 ms fade in.
- All Verse sounds feed one master submix with a look-ahead limiter.

```
python art/verse/audio/build_audio.py
python art/verse/audio/import_audio.py          # needs the editor build
python art/verse/audio/reference_mix.py --check
python art/verse/audio/audit_licences.py --require-assets
python -m pytest art/verse/audio/tests -q
```

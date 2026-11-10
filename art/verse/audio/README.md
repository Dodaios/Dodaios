# Verse audio (WP19)

Sound for the Unreal Verse, built as code. Nothing recorded is committed:
synthesised sounds are computed here, CC0 recordings are read from the files
the ledger (`art/verse/LICENSES.md`) cites, and only the imported `.uasset`
files under `unreal/Verse/Content/Verse/Audio/` enter git (Git LFS).

| File | Job |
|---|---|
| `dsp.py` | Seeded DSP primitives (noise, filters, modes, room responses) |
| `recipes.py` | One recipe per sound family: weapon layers (real-gun reports: supersonic crack, muzzle blast, action; no tonal parts), bullet flybys (crack and zip), spent casings, impacts on the 8 materials, footsteps per surface, foley, reloads, melee, finisher, destruction per piece class, debris, drones, gadgets, beds, UI |
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
  only for their own player. The listener's own bullet impacts are shooter
  feedback (cue `range_m`), as the bot gets its own hit confirms.
- Weapons fire bullets. Four sound profiles (`pistol`, `smg`, `rifle`,
  `marksman`); `cues.json` `weapon_ids` maps each weapon id to one. A bullet
  passing within `flyby.radius_m` plays `bullet_flyby` at its closest point,
  timed by the firing weapon's `ProjectileSpeed` (`flyby.bullet_speed_mps`
  when the weapon has no definition). Every shot drops a `casing_<profile>`
  at the shooter's feet (`casing.drop_m` below the muzzle) after
  `casing.delay_s`; it is queued only when the listener is within the cue's
  `range_m` (8 m).
- At most 64 voices; a cue over its own limit replaces its oldest voice, over
  the global cap the lowest-priority voice is stolen.
- The table is `DA_Audibility` (Core): the cue set's own pointer, else the
  project's one `UVerseAudibilityTable` asset (`/Game/Verse/Core/DA_Audibility`
  first, else the asset registry), and only without any asset the contract
  rows. `reference_mix.py` keeps a copy of those rows; a test holds it equal to
  Core's `MakeContractRows`.
- Someone else's reload plays at that player's pawn with the `Noise.Reload`
  range; without a known pawn it does not play. A new reload or a cancel stops
  the player's previous reload voice.
- Occlusion is traced through destructible pieces with the destruction query,
  which honours holes and breaches, so opening a wall opens the sound; loops
  re-trace every 0.25 s. A voice's volume multiplier (cue volume, gain, bus
  and master gain) is set once at the start; occlusion moves only the voice's
  fader, so the heard level is always multiplier x occlusion gain.
- Hidden or dormant: muted at once; shown again: a 150 ms fade in.
- Every sound routes to the submix of its bus (weapons, impacts, foley,
  destruction, gadgets, ambience, UI); the bus submixes feed one master submix
  with a look-ahead limiter. Bus gains stay on the voice multiplier so the
  event log and the reference mix see them.
- Sources are sound waves; layering (mechanical, body, tail, distance layers)
  is done by the subsystem, which starts each layer as its own voice.

Mixer lane (A19.3 audio-thread cost): `Verse.UI.Audio.MixerLoad` runs
`destruction_storm` through the engine sink and the shipped cues and writes
`Saved/Harness/proof/WP19/19.6/mixer_load.json`. It needs a run with sound;
under `-nosound` (the `test.py` lane) it only notes the skip:

```
python scripts/unreal/with_lock.py --label wp19-mixer -- <UnrealEditor-Cmd.exe> unreal/Verse/Verse.uproject   "-ExecCmds=Automation RunTests Verse.UI.Audio.MixerLoad; Quit" "-TestExit=Automation Test Queue Empty"   -unattended -nullrhi -nosplash -NoP4 -stdout -ReportExportPath=<dir> -abslog=<dir>/run.log
```

```
python art/verse/audio/build_audio.py
python art/verse/audio/import_audio.py          # needs the editor build
python art/verse/audio/reference_mix.py --check
python art/verse/audio/audit_licences.py --require-assets
python -m pytest art/verse/audio/tests -q
```

# The Sovereign: the commander's default skin

The person plays the commander in every view (bird's-eye, third and first person, the duel). Their body is
`SK_Sovereign`, the first of what will become a set of skins. Original design: a hooded sovereign in black velvet
with gold piping, glowing amber eyes deep in the hood, a deep red cloak lining.

## The model

Built in Blender by `art/verse/characters/sovereign.py` (painter `looks_sovereign.py`) through the normal
character build:

```
python scripts/verse/blender.py run --no-lock art/verse/characters/build.py --only SK_Sovereign --no-clips
python scripts/verse/blender.py run art/verse/characters/sovereign_qa.py all   # look-dev renders
```

- Male skeleton, so every shared clip (`A_Human_M.glb`) drives it.
- Pieces: inner robe on the body (pale aged face, bare hands), floor-length robe skirt, bell sleeves with gold
  cuffs, a deep cowl (hood and shoulder drape in one shell), an open cloak to the floor, a gold clasp and chain,
  belt, boots, emissive eyes (`M_SovEye`).
- The robe skirt hangs from the hips and is swung by both thighs together, so a stride never splits it.
- Materials have their own names (`M_Sov*`), so the rank tiers never repaint them. `applyLook` still runs and
  simply finds nothing to tint.
- About 39k triangles, 2.1 MB.

## The cloak bones

The Sovereign carries its own copy of the skeleton with six extra bones, `Cloak_{R,C,L}{1,2}` (children of
`Chest`), listed in the manifest as `extraBones`. The clips never animate them. `actors/cloak.ts` (`CloakRig`)
poses them every frame as damped springs: the hem lifts behind a walking body, swings against a strafe or a turn,
and whips a little after a stop. Deck bodies and the duel figure both run it.

## Arc Storm (F)

Hold F on a deck (not in a duel): both arms rise toward the aim (the view at eye level, the body's facing on the
plate) and violet-white lightning crackles from the hands (`abilities/arcStorm.ts`, sound in `arcSound.ts`).
In first person the bolts leave from the bottom corners of the view, where the person's own hands are. It is a
show of power only: it does nothing to the crew or the duel yet.

## Where the commander's body is chosen

`COMMANDER_SKIN` in `actors/characters.ts`. A manifest without it falls back to an officer body, everywhere
(deck cast, duel figure, first-person arms).

# Verse on Unreal: style sheet (Military-Industrial Noir)

Owner: WP14. Source of truth for the look of the Unreal Verse: the master
materials and their parameters, the post-process look profile, the weapon
design sheet and the weapon VFX. Palette and colour bans are the contract's
(`docs/verse/unreal/contracts/art-pipeline.md` 8); this sheet never widens them.

## 1. Look in one paragraph

Black steel, concrete, oil and wear under hard work lights that fall off
into darkness, dust and neutral haze. Accents are rare and small: amber for
our own bolts, lamps and screens; signal red for the opponent and alarms;
brand gold only on rank marks. Never cyan, violet or coloured fog. Every
surface has roughness variation and a wear or grime mask; edges are 45 degree
chamfers that catch the light.

## 2. How the text becomes assets

| Step | Command | Writes |
|---|---|---|
| Weapon, gadget and VFX meshes | `python scripts/verse/export_unreal.py weapons` | FBX in `art/verse/.cache/unreal/weapons/`, records in `unreal/Verse/Art/Import/Weapons/**`, `Art/Import/VFX/Weapons/` |
| Grade LUT and AgX chart reference | `python scripts/verse/export_unreal.py textures` | `art/verse/.cache/unreal/look/`, record `Art/Import/PostProcess/T_Verse_Grade_LUT_M.import.json` |
| Everything in Unreal, one lock hold | `python scripts/unreal/import_art.py wp14` | LUT texture, masters, MIs, meshes with sockets and slots, validation, lookdev frames |
| Single steps | `import_art.py masters`, `materials`, `assets`, `validate`, `lookdev` | as named |
| Evidence numbers | `python art/verse/weapons/look/evaluate.py` | `unreal/Verse/Saved/Harness/proof/WP14/metrics.json` |

Masters are built from `unreal/Verse/Content/Python/verse_pipeline/masters.py`;
MIs from `unreal/Verse/Art/Materials/**/MI_*.mi.json`. Edit the text, never the
`.uasset`.

## 3. Look profile (WP14.2)

| Item | Value | Why |
|---|---|---|
| Tone map | `M_Verse_PostTonemap` (post-process material, blendable location "replacing the tonemapper") samples `T_Verse_Grade_LUT_M` | The LUT holds Blender's own AgX output, so Unreal frames grade like today's Blender renders |
| LUT layout | 32 x 32 x 32 lattice as a 1024 x 32 strip of 32 slices (slice = blue), stored linear (HDR compression, no mips, clamped) | One sample pair per pixel, no tonemapper curve to invert |
| LUT input | per channel `u = (log2(c / 0.18) + 12.47393) / 18.47393`, clamped | AgX's own lower bound, headroom to +6 EV above middle grey |
| Order in the shader | `(scene + bloom * BloomScale) * exposure`, then the LUT | Bloom input 2 and the eye-adaptation exposure replace the tonemapper's own |
| Exposure | Manual, physical camera off; `AutoExposureBias` per deck. Bias 0 means exposure scale 1 (chart test) | Fixed exposure per deck (art-pipeline 7) |
| Reference scenes | bias -4, bloom 0.35 | Values of `verse_pipeline.lookdev.PROFILE` |
| Work light, hard | Spot, 5600 K, 2600 cd, 26 degree cone, source radius 1.5 cm, shadows on | Hard light, deep falloff, key-to-shadow at least 8 : 1 |
| Fill | Spot, 4300 K, 90 cd, wide, no shadows | Keeps blacks readable without lifting them |
| Rim | Spot, 6500 K, 900 cd, 18 degree cone | Separates black weapons from black walls |
| Practical lamps | Amber `#F2A33A` and red `#E3242B` emissive at 20-25 nits plus a small point light (6-8 cd) | Lamps light only their surroundings |
| Haze | Exponential height fog density 0.035, inscattering luminance 0.004 grey, volumetric fog on, albedo 0.9 grey | Neutral haze, never coloured (art-pipeline 8.3) |
| Viewmodel lighting | No emissive on weapons; the weapon MIs keep roughness low on oiled and worn areas so the rim and work lights draw the edges. WP02 attaches no extra light | Black stays black, edges read |

Accepted when the chart rendered in Unreal through this profile at bias 0
matches the Blender AgX render of the same scene-linear values with a mean
CIEDE2000 of at most 3 (A14.4); the offline error of the LUT alone is in the
metrics too.

## 4. Weapon design sheet (WP14.3)

All weapons are original. Names are fictional. Every part is fully black:
base colour at most `#1A1A1B`, worn edges at most `#3B3F47`, no gold, no
coloured trim; the only light on a weapon is a sight reticle or a gadget
status lamp in amber. The silhouettes are built from 45 degree chamfered
slabs and faceted prisms (brutalist grid), never from the outline of any
existing firearm.

| Weapon | Role | Asset | Skeleton | Bones | Sockets |
|---|---|---|---|---|---|
| Graveline | assault rifle | `SK_Weapon_Graveline` | `SKEL_Weapon_Graveline` | `Root`, `Magazine`, `Bolt`, `Trigger` | `SOCKET_Muzzle`, `SOCKET_Sight`, `SOCKET_Support`, `SOCKET_Eject` |
| Tallow | pistol | `SK_Weapon_Tallow` | `SKEL_Weapon_Tallow` | `Root`, `Magazine`, `Slide`, `Trigger` | `SOCKET_Muzzle`, `SOCKET_Sight`, `SOCKET_Support`, `SOCKET_Eject` |
| Hookbill | knife | `SK_Weapon_Hookbill` | `SKEL_Weapon_Hookbill` | `Root` | `SOCKET_Tip` |
| Bulwark | deployable energy barricade | `SM_Weapon_Bulwark` | - | static mesh | none |
| Bulwark | energy field of the Bulwark | `SM_Weapon_BulwarkField` | - | static mesh | none |
| BreachCharge | breach charge | `SM_Weapon_BreachCharge` | - | static mesh | none |
| Skitter | submachine gun | `SK_Weapon_Skitter` | `SKEL_Weapon_Skitter` | `Root`, `Magazine`, `Bolt`, `Trigger` | `SOCKET_Muzzle`, `SOCKET_Sight`, `SOCKET_Support`, `SOCKET_Eject` |
| Longsight | designated marksman rifle | `SK_Weapon_Longsight` | `SKEL_Weapon_Longsight` | `Root`, `Magazine`, `Bolt`, `Trigger` | `SOCKET_Muzzle`, `SOCKET_Sight`, `SOCKET_Support`, `SOCKET_Eject` |

Shape language per weapon:

- **Graveline** (assault rifle): Monolithic slab receiver with a 45 degree chamfered spine; no carry handle, no rail lugs; Hexagonal handguard prism with three stepped vent slots per side; Squat box sight with a recessed amber dot reticle; Skeleton stock of two angled struts closing on a rubber butt block; Magazine straight and tapered, with a ribbed base plate.
- **Tallow** (pistol): Wedge slide whose front third steps down by a 45 degree chamfer; Rear serration as three deep horizontal grooves, not vertical cuts; Grip with a hard brutalist backstrap step and a flat base plate; Square trigger guard with a chamfered front corner.
- **Hookbill** (knife): Straight single-edged blade whose spine bends down into a short hook at the tip; Faceted blade grind: two flat planes, no hollow grind; Square guard plate and a handle of stacked chamfered rubber blocks; Pommel as a flat hexagonal cap.
- **Bulwark** (deployable energy barricade): Low steel sled with two fold-out feet and an emitter rail along its top; Energy field panel as a separate mesh SM_Weapon_BulwarkField (thin, translucent); One amber status lamp at the rear.
- **BreachCharge** (breach charge): Flat rectangular slab in a chamfered frame with four corner pads; Detonator block in the middle with one amber arming lamp.
- **Skitter** (submachine gun): Short box receiver with a forward magazine that doubles as the support grip; Charging slot on the left side; Stubby collapsed stock of a single flat bar; Low open sight blades instead of an optic.
- **Longsight** (designated marksman rifle): Long faceted octagonal barrel shroud ending in a squared muzzle block; Tube sight on two flat stand-offs with deep sun hoods; Solid stock with a stepped cheek riser; Short box magazine.

### 4.1 No-copy checklist

Every weapon PR answers each line with yes before it lands; the verifier
checks the turnarounds against it.

| # | Check |
|---|---|
| 1 | The silhouette is drawn from chamfered slabs and prisms of this sheet, not traced from a photo, a drawing or a model of any real firearm |
| 2 | No part (receiver, slide, grip, stock, magazine, muzzle device, sight) reproduces the distinctive shape of a real product |
| 3 | No real make, model, calibre marking, proof mark, serial or logo appears in geometry, textures, names, comments or records |
| 4 | The name is one of the fictional names above; a new weapon gets a new fictional name in this sheet first |
| 5 | Every material slot uses an `MI_Weapon_*` of `M_Verse_Weapon`, `M_Verse_Glass` or `M_Verse_Emissive`; base colour luminance at most 0.06 linear (A14.2) |
| 6 | Bones at most 24, triangles at most 60 k first person, all sockets of art-pipeline 12.2 present (A14.1) |
| 7 | The forbidden-name scan (`scripts/unreal/check_forbidden_names.py`) reports 0 hits over the diff |

### 4.2 Weapon space

+X towards the muzzle, +Z up, +Y right in Unreal (+Y left in Blender); the
origin and bone `Root` sit at the grip point that attaches to `Weapon_R`.
Sockets are relative to `Root`; their positions are in
`art/verse/weapons/specs.py` and are added on import by
`verse_pipeline.weapons` (skeletal FBX files carry no socket objects).

## 5. Weapon VFX (WP14.9)

| Asset | Use | Material |
|---|---|---|
| `SM_Vfx_Bolt` | laser bolt core and glow sleeve, 60 cm long, +X along flight | `MI_Weapon_Vfx_BoltOwn` |
| `SM_Vfx_MuzzleFlash` | crossed flash cards on +X | `MI_Weapon_Vfx_MuzzleOwn` |
| `SM_Vfx_ImpactSparks` | spark streak burst along +X (surface normal) | `MI_Weapon_Vfx_Sparks` |

| Material instance | Master | Use |
|---|---|---|
| `MI_Weapon_Vfx_BoltOwn` | `M_Verse_Emissive` | own bolt, amber |
| `MI_Weapon_Vfx_BoltFoe` | `M_Verse_Emissive` | opponent bolt, red |
| `MI_Weapon_Vfx_MuzzleOwn` | `M_Verse_Emissive` | own muzzle flash, amber |
| `MI_Weapon_Vfx_MuzzleFoe` | `M_Verse_Emissive` | opponent muzzle flash, red |
| `MI_Weapon_Vfx_Sparks` | `M_Verse_Emissive` | impact sparks, amber-white |
| `MI_Weapon_Vfx_Scorch` | `M_Verse_Decal` | impact scorch decal, oil black |

Bolts are opaque unlit emissive rods (84 triangles, no translucency, no
overdraw): own `MI_Weapon_Vfx_BoltOwn` amber `#F2A33A`, opponent
`MI_Weapon_Vfx_BoltFoe` red `#E3242B` (README Projectiles; the
`BoltColorOwn`/`BoltColorFoe` tags of `UVerseWeaponDefinition` select one of
the two). The muzzle flash is translucent with a vertex-colour falloff from a
hot core; the scorch is a DBuffer decal with the procedural round mask of
`M_Verse_Decal`. `Fade` on every VFX instance is the runtime lifetime knob.

## 6. Master materials and their parameters (WP14.1)

Frozen names (art-pipeline 7). Parameter tables are generated from
`verse_pipeline/masters.py`; a test fails when a parameter is missing here.
Rules beyond the parameters:

- `M_Verse_Weapon` clamps `BaseTint` to `#1A1A1B` and `EdgeTint` to
  `#3B3F47` per channel in the shader; no instance can lighten a weapon.
- `UseHoleMask = true` in a recipe also sets the instance's blend mode
  override to Masked (`verse_pipeline.materials`); the hole mask is the
  per-piece 256 x 256 render target of destruction 5, sampled at UV0 through
  `HoleMaskUV` (xy scale, zw offset).
- Triplanar mode (`UseTriplanar`) maps in world space relative to the
  object origin with a per-object random offset; use it only for pieces
  without UVs. Normal maps apply in UV mode only.
- Vertex colour: R = edge wear (chamfer middles), G = grime (concave seams),
  B = third texture set share (surface master only).
- `validate_assets` fails on a palette ban (art-pipeline 8.3) in any MI vector
  and on A14.2 for any MI under `/Game/Verse/Materials/Instances/Weapons/`.

### `M_Verse_Surface`

Opaque hard surface: steel, concrete, paint, rubber.

| Parameter | Kind | Meaning |
|---|---|---|
| `BaseTint` | vector | Albedo tint (linear); multiplies the texture set |
| `RoughnessMin` | scalar | Roughness on worn, polished areas |
| `RoughnessMax` | scalar | Roughness on untouched areas |
| `Metallic` | scalar | 0 dielectric (paint, concrete, rubber), 1 bare steel |
| `EdgeWear` | scalar | Strength of vertex colour R (edge wear) and world noise wear |
| `EdgeTint` | vector | Colour of worn edges |
| `GrimeAmount` | scalar | Strength of vertex colour G (grime) and noise grime |
| `NoiseScale` | scalar | World noise frequency per metre |
| `UseTriplanar` | switch | Object-relative triplanar mapping for pieces without UVs |
| `TriplanarScale` | scalar | Texture repeats per metre in triplanar mode |
| `UseTextureSet` | switch | Sample Set1 (and Set2/Set3 by noise masks) instead of flat tint |
| `Set1_BC` | texture | Texture set 1 base colour (sRGB) |
| `Set1_ORM` | texture | Texture set 1 AO/roughness/metallic |
| `Set1_N` | texture | Texture set 1 normal (UV mode only) |
| `Set2_BC` | texture | Texture set 2 base colour (triplanar blend, noise mask) |
| `Set3_BC` | texture | Texture set 3 base colour (triplanar blend, vertex colour B) |
| `Set2Amount` | scalar | Share of set 2 |
| `Set3Amount` | scalar | Share of set 3 |
| `UseHoleMask` | switch | Per-piece hole mask (destruction 5); implies Masked blend |
| `HoleMask` | texture | Hole mask render target, R = 1 solid, 0 hole |
| `HoleMaskUV` | vector | UV0 to mask space: xy scale, zw offset |

### `M_Verse_Floor`

Floors and decks, world-space grid.

| Parameter | Kind | Meaning |
|---|---|---|
| `BaseTint` | vector | Deck plate colour |
| `SeamTint` | vector | Seam line colour |
| `GridCm` | scalar | Seam grid size in cm on the global grid |
| `SeamCm` | scalar | Seam width in cm |
| `RoughnessMin` | scalar | Roughness in the gloss lanes |
| `RoughnessMax` | scalar | Roughness elsewhere |
| `LaneCm` | scalar | Spacing of the worn gloss lanes (along X) |
| `LaneWidthCm` | scalar | Width of a worn lane |
| `WearAmount` | scalar | Strength of lane wear and noise |
| `NoiseScale` | scalar | World noise frequency per metre |
| `UseHoleMask` | switch | Never on the hall floor; for breakable deck panels |
| `HoleMask` | texture | Hole mask, R = 1 solid |
| `HoleMaskUV` | vector | UV0 to mask space |

### `M_Verse_Emissive`

Light panels, indicators, lamps, reticles and opaque weapon VFX (unlit, two-sided).

| Parameter | Kind | Meaning |
|---|---|---|
| `EmissiveColor` | vector | Linear colour, palette-checked (amber, red, work-light white) |
| `EmissiveNits` | scalar | Brightness multiplier |
| `Fade` | scalar | 0..1 runtime fade (VFX lifetime) |
| `UseVertexFalloff` | switch | Multiply by vertex colour R (hot core to cool tip) |

### `M_Verse_Glass`

Glazing, lenses, energy fields and soft VFX (translucent).

| Parameter | Kind | Meaning |
|---|---|---|
| `BaseTint` | vector | Glass tint |
| `Opacity` | scalar | Coverage |
| `Roughness` | scalar | Surface roughness |
| `EmissiveColor` | vector | Self-light of energy fields and flashes |
| `EmissiveNits` | scalar | Brightness multiplier |
| `Fade` | scalar | 0..1 runtime fade |
| `UseVertexFalloff` | switch | Opacity and emission times vertex colour R |

### `M_Verse_Screen`

Desk monitors (render target from VerseScreens).

| Parameter | Kind | Meaning |
|---|---|---|
| `ScreenTexture` | texture | Render target of the desk's terminal |
| `EmissiveNits` | scalar | Screen brightness |
| `ScreenTint` | vector | Tint |
| `Roughness` | scalar | Glass front roughness |

### `M_Verse_Character`

Skin, cloth, gear (subsurface profile); UV0 stable for wound masks.

| Parameter | Kind | Meaning |
|---|---|---|
| `BaseTint` | vector | Albedo tint |
| `BaseColorMap` | texture | Base colour (sRGB) |
| `ORMMap` | texture | AO, roughness, metallic |
| `NormalMap` | texture | Normal |
| `RoughnessScale` | scalar | Roughness multiplier |
| `Sheen` | scalar | Cloth sheen at grazing angles |
| `SubsurfaceAmount` | scalar | Skin subsurface opacity |

### `M_Verse_Weapon`

All weapons: black only, edge wear, oil, grime; no emissive.

| Parameter | Kind | Meaning |
|---|---|---|
| `BaseTint` | vector | Base colour; clamped in shader to #1A1A1B |
| `EdgeTint` | vector | Worn edge colour; clamped to #3B3F47 |
| `EdgeWear` | scalar | Strength of vertex colour R (chamfer middles) |
| `EdgeMetallic` | scalar | Metallic of worn edges (1 steel, 0 polymer) |
| `Metallic` | scalar | Metallic of the body |
| `RoughnessMin` | scalar | Roughness of polished, oiled areas |
| `RoughnessMax` | scalar | Roughness of the body |
| `OilAmount` | scalar | Oil film: darker and glossier patches |
| `GrimeAmount` | scalar | Strength of vertex colour G (seams) |
| `NoiseScale` | scalar | Noise frequency per UV metre |

### `M_Verse_Decal`

DBuffer decal: markings, stencils, grime, scorch.

| Parameter | Kind | Meaning |
|---|---|---|
| `BaseTint` | vector | Decal colour |
| `Opacity` | scalar | Coverage |
| `Roughness` | scalar | Roughness written to the DBuffer |
| `DecalMask` | texture | Shape mask, R |
| `UseRadialMask` | switch | Procedural round mask with ragged rim (scorch) |
| `NoiseScale` | scalar | Rim noise frequency |

### `M_Verse_PostTonemap`

Replaces the tonemapper: exposure, bloom, then the AgX grade LUT.

| Parameter | Kind | Meaning |
|---|---|---|
| `GradeLut` | texture | T_Verse_Grade_LUT_M (32^3 strip) |
| `BloomScale` | scalar | Bloom added before the grade |
| `LutSize` | scalar | Lattice size of the strip |

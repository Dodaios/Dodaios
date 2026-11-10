# Contract: coordinates and units

Owner: integration owner. Implemented in `VerseCore` (architecture section 2).
Every package that reads a three.js-era number (deck manifests, `ArenaDef`
data, art builders, bridge payloads, golden test data) converts it through this
contract and nowhere else.

## 1. The two frames

| | three.js Verse today (source frame, "T") | Unreal Verse (target frame, "U") |
|---|---|---|
| Length unit | metre | centimetre |
| Handedness | right-handed | left-handed |
| Up | +Y | +Z |
| Other axes | +X = screen right (plan east), +Z = toward the plate camera (plan south, screen bottom) | +X = forward (engine convention), +Y = right |
| Floor | deck floor at y = 0 | deck floor at Z = 0 (deck-local) |
| Plan origin | `x = 0` left hull wall, `z = 0` far (hero) hull wall (`art/verse/LEVELS.md`) | same point, deck-local origin |
| Yaw | radians about +Y, 0 faces +Z, 90° faces +X (`combat/math.ts:2-4`, `yawOf = atan2(dx, dz)`); manifests store `yaw_deg` with the same meaning (`content/loadDeck.ts:47`, `arena.ts` spoke `yawDeg`) | degrees about +Z, 0 faces +X, +90 faces +Y; range (-180, 180] (`FRotator::NormalizeAxis`) |
| Pitch | radians, positive looks up (`combat/math.ts:4`) | degrees, positive looks up |
| Mesh front | actor roots turn by `rotation.y = yaw` (`actors/actor.ts:688`), so models face local +Z | a pawn's gameplay forward is +X; an imported skeletal or static mesh's front is local +Y (section 3.3) |
| Blender (art builders) | Blender = (x, -z, y) of T (`art/verse/BRIEF.md` §4, `hangar_layout.py:B`) | reached through glTF, never directly |

Source of the mapping. Unreal's own glTF importer and exporter swap Y and Z and
scale metres by 100 (`Plugins/Interchange/Runtime/Source/Parsers/GLTFCore/Private/GLTF/ConversionUtilities.h:16-42`,
`Import/Private/Gltf/InterchangeGltfPrivate.h:24` `GltfUnitConversionMultiplier = 100`).
Our realtime exports are glTF with +Y up, which is frame T. Choosing the same
mapping means imported meshes, converted manifest sockets and converted sim
data land on the same spot with no per-asset fix-up. This is a decision.

## 2. Formulas

### 2.1 Positions, lengths, directions

Let `M` be the axis permutation T→U (Y and Z swapped, determinant -1, so the
handedness flips):

```
M = | 1 0 0 |        U = 100 · M · T  + O_deck      (positions)
    | 0 0 1 |        U =       M · T                (directions, normals: no scale, no offset)
    | 0 1 0 |        T = M · (U - O_deck) / 100     (M is its own inverse)
```

Per component:

| Quantity | T to U | U to T |
|---|---|---|
| Position | `X = 100·x + Ox`, `Y = 100·z + Oy`, `Z = 100·y + Oz` | `x = (X-Ox)/100`, `y = (Z-Oz)/100`, `z = (Y-Oy)/100` |
| Direction, normal, velocity direction | `(x, z, y)` | `(X, Z, Y)` |
| Length, radius, height, distance | `·100` | `/100` |
| Speed (m/s), acceleration (m/s²) | `·100` (cm/s, cm/s²) | `/100` |
| Area, volume | `·10⁴`, `·10⁶` | `/10⁴`, `/10⁶` |
| Time, mass, damage, health, angles in a cone (±44° sight) | unchanged | unchanged |
| Axis-aligned box `x0..x1, y0..y1, z0..z1` | `Min = 100·(x0, z0, y0) + O`, `Max = 100·(x1, z1, y1) + O` (no negation, so min stays min) | inverse |
| Vertical cylinder `(x, z, r, y0..y1)` | centre `100·(x, z)`, radius `100·r`, `Z` span `100·y0..100·y1` | inverse |
| Cross product | `M(a × b) = -(Ma × Mb)`: a three.js cross product changes sign after conversion. Convert the operands, then cross in U; never convert a T cross product | |

`O_deck` is the deck's world origin in centimetres, owned by `VerseDecks`. It
is a pure translation: no rotation, no scale, ever. Deck-local code passes
`FVerseDeckFrame::Local()` (zero offset).

### 2.2 Heading (gameplay yaw)

A heading is where an actor, controller, spawn, console or camera points.
three.js forward is `(sin ψ, 0, cos ψ)`; Unreal forward of yaw `φ` is
`(cos φ, sin φ, 0)`. Through `M`:

```
φ_deg = Normalize( 90 - ψ_deg )          ψ_deg = ψ_rad · 180/π
ψ_rad = WrapPi( (90 - φ_deg) · π/180 )   Normalize → (-180, 180], WrapPi → (-π, π]
```

- Sense flips: three.js yaw grows counter-clockwise on the LEVELS plan
  (x right, z down); Unreal yaw grows clockwise seen from above. Yaw *rates*
  therefore flip sign: `φ̇ = -ψ̇` (deg/s from rad/s: `-ψ̇·180/π`).
- three.js "right" (`rightX = -cos ψ`, `rightZ = sin ψ`, `combat/math.ts:47-48`)
  maps exactly to Unreal's right axis (`FRotationMatrix(R).GetUnitAxis(EAxis::Y)`).
  Lean sign is defined in U: lean > 0 moves toward the pawn's right axis.
- Pitch: `θ_U_deg = θ_T_rad · 180/π`, same sign. View rotation = `FRotator(θ, φ, 0)`.
  Then `FRotator(θ, φ, 0).Vector() == M · dirFromAngles(ψ, θ)` (`combat/math.ts:51-54`).

### 2.3 Object rotation (geometry placed as authored)

For a rotation operator (an Object3D quaternion, a glTF node rotation), the
conversion is the one Unreal's glTF importer uses:

```
q_U = ( -q_T.x, -q_T.z, -q_T.y, q_T.w )     q_T = ( -q_U.x, -q_U.z, -q_U.y, q_U.w )
```

so that `q_U.RotateVector(M·v) == M·(q_T · v)`. A pure three.js yaw `ψ` becomes
a Unreal yaw of `-ψ_deg`: this is the **mesh yaw**, and it always equals
`heading - 90°`. Consequences:

| Use | Function | Value for manifest `yaw_deg = a` |
|---|---|---|
| Actor, pawn, controller, spawn point, console facing, AI facing | `ToUnrealHeadingDeg` | `Normalize(90 - a)` |
| Static geometry imported from the realtime glTF and placed by its socket | `ToUnrealMeshYawDeg` | `Normalize(-a)` |
| Skeletal mesh on a pawn | mesh component relative yaw is the fixed `-90°` | (heading - 90 = mesh yaw) |

Never convert a three.js **camera** quaternion: a three.js camera looks down
local -Z, a Unreal camera down local +X. Convert the camera's (yaw, pitch)
with section 2.2 instead. Never convert a three.js Euler triple
(`actor.ts:684` uses order `YXZ`, and `Object3D.rotation.x > 0` tilts a +Z-facing
model *down*, the opposite of combat pitch); build the quaternion first.

### 2.4 Precision

- All conversion math is `double` (`FVector` is double under large world coordinates).
- Converting at most once: data stays in T until the decoding edge
  (`VerseDecks` manifest import, `VerseBridge` codec, harness golden loaders),
  then lives in U. Nothing converts back except the bridge encoder and tests.
- Quantisation for the network (Iris quantised vectors) happens after
  conversion, in U units. three.js snapshot quantisation (`math.ts:q`) does
  not carry over.

## 3. Worked examples

### 3.1 Hangar (deck 4) positions, deck-local (`O_deck = 0`)

Data from `art/verse/decks/hangar/hangar_layout.py` and
`public/verse/decks/hangar/manifest.json`.

| Point | T (x, y, z) m | U (X, Y, Z) cm |
|---|---|---|
| Floor corner, far-left (hero wall, west) | (0, 0, 0) | (0, 0, 0) |
| Floor corner, far-right (hero wall, east) | (100, 0, 0) | (10000, 0, 0) |
| Floor corner, near-left (near wall, west) | (0, 0, 62) | (0, 6200, 0) |
| Floor corner, near-right | (100, 0, 62) | (10000, 6200, 0) |
| Ceiling slab, near-right corner | (100, 21, 62) | (10000, 6200, 2100) |
| Hero wall top above the blast door centre (wall face z 1.5) | (50, 22, 1.5) | (5000, 150, 2200) |
| Launch well floor, first corner (26 m deep) | (8, -26, 8) | (800, 800, -2600) |
| Launch well floor, opposite corner | (38, -26, 20) | (3800, 2000, -2600) |
| Shuttle piece origin (pad centre) | (50, 0, 23.6) | (5000, 2360, 0) |
| Booth floor corner (raised 1.2 m) | (3, 1.2, 47.2) | (300, 4720, 120) |
| Lift door `lift_a` | (68, 0, 50.72) | (6800, 5072, 0) |
| Holo `Shuttle__tactical` | (50, 2.53, 24.6) | (5000, 2460, 253) |
| Eye height above the floor (`shoulderRig.ts`) | (·, 1.65, ·) | (·, ·, 165) |

### 3.2 Spawns

| Spawn | T position, yaw | U position | U heading | U mesh yaw |
|---|---|---|---|---|
| Hangar `commander` (`lift_lobby`) | (70, 0, 54.2), `yaw_deg` 0 (faces +z, toward the near wall) | (7000, 5420, 0) | 90 | 0 |
| Hangar `SOCKET_spawn_arrival` (ramp foot) | (50, 0, 38.1) | (5000, 3810, 0) | per socket | per socket |
| Reactor side 0 (`arenaReactor.ts:82`) | (38.8, 0, 22), yaw π/2 | (3880, 2200, 0) | 0 | -90 |
| Reactor side 1 (`arenaReactor.ts:83`) | (69.2, 0, 22), yaw -π/2 | (6920, 2200, 0) | 180 | 90 |

The feet-on-floor point converts as above; a `ACharacter` location is its
capsule centre, so `VerseMovement` adds the capsule half-height in Z. That
offset is Movement's, not part of this contract.

### 3.3 Yaw, pitch, directions, quaternions

| T input | T forward (x, y, z) | U heading / rotator | U forward (X, Y, Z) | U mesh yaw |
|---|---|---|---|---|
| ψ = 0 | (0, 0, 1) | 90 | (0, 1, 0) | 0 |
| ψ = 90° | (1, 0, 0) | 0 | (1, 0, 0) | -90 |
| ψ = -90° | (-1, 0, 0) | 180 (not -180) | (-1, 0, 0) | 90 |
| ψ = 180° | (0, 0, -1) | -90 | (0, -1, 0) | 180 |
| ψ = 135° (reactor `ring_1`) | (0.7071, 0, -0.7071) | -45 | (0.7071, -0.7071, 0) | -135 |
| ψ = -135° (reactor `ring_2`) | (-0.7071, 0, -0.7071) | -135 | (-0.7071, -0.7071, 0) | 135 |
| ψ = 90°, θ = 10° | (0.9848, 0.1736, 0) | `FRotator(10, 0, 0)` | (0.9848, 0, 0.1736) | |
| Plate view direction `D` (BRIEF §4) | (0, -0.8660, -0.5) | | (0, -0.5, -0.8660) | |
| Quaternion, yaw 90° about +Y: (0, 0.7071, 0, 0.7071) | | q_U = (0, 0, -0.7071, 0.7071) = yaw -90 | | -90 |
| Yaw rate +2 rad/s | | -114.59 deg/s | | |
| Run speed 4.8 m/s; rifle bullet 880 m/s | | 480 cm/s; 88000 cm/s | | |

## 4. C++ API (VerseCore)

File: `unreal/Verse/Source/VerseCore/Public/VerseCoords.h`. A plain C++
namespace for hot paths, a thin Blueprint library for data and tools.

```cpp
#pragma once
#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "VerseCoords.generated.h"

/** A point or vector in the three.js Verse frame: metres, +Y up, +Z toward the plate camera.
 *  A distinct type so a metre value can never be passed where an Unreal FVector is expected. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseThreeVector
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite) double X = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite) double Y = 0.0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite) double Z = 0.0;
};

/** A deck's world placement: translation only, in centimetres. Owned by VerseDecks. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseDeckFrame
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite) FVector OriginCm = FVector::ZeroVector;
	static FVerseDeckFrame Local() { return FVerseDeckFrame(); }
};

namespace Verse::Coords
{
	inline constexpr double CmPerMetre = 100.0;

	// Scalars
	VERSECORE_API double MetresToCm(double Metres);
	VERSECORE_API double CmToMetres(double Cm);

	// Points (scaled and offset) and directions (swapped only)
	VERSECORE_API FVector            ToUnrealPosition(const FVerseThreeVector& P, const FVerseDeckFrame& Deck = FVerseDeckFrame::Local());
	VERSECORE_API FVerseThreeVector  ToThreePosition(const FVector& PCm, const FVerseDeckFrame& Deck = FVerseDeckFrame::Local());
	VERSECORE_API FVector            ToUnrealDirection(const FVerseThreeVector& D);
	VERSECORE_API FVerseThreeVector  ToThreeDirection(const FVector& D);
	VERSECORE_API FBox               ToUnrealBox(double X0, double X1, double Y0, double Y1, double Z0, double Z1,
	                                             const FVerseDeckFrame& Deck = FVerseDeckFrame::Local());

	// Heading (gameplay forward, +X)
	VERSECORE_API double   ToUnrealHeadingDeg(double ThreeYawRad);        // Normalize(90 - deg(yaw))
	VERSECORE_API double   ToUnrealHeadingDegFromDeg(double ThreeYawDeg); // manifest yaw_deg
	VERSECORE_API double   ToThreeYawRad(double UnrealYawDeg);            // WrapPi(rad(90 - yaw))
	VERSECORE_API double   ToUnrealYawRateDeg(double ThreeYawRateRad);    // sign flips
	VERSECORE_API FRotator ToUnrealViewRotation(double ThreeYawRad, double ThreePitchRad);

	// Object rotation (geometry as authored; mesh front = local +Y)
	VERSECORE_API double   ToUnrealMeshYawDeg(double ThreeYawRad);        // Normalize(-deg(yaw)) == heading - 90
	VERSECORE_API FQuat    ToUnrealQuat(const FQuat& ThreeQuat);          // (-x, -z, -y, w)
	VERSECORE_API FQuat    ToThreeQuat(const FQuat& UnrealQuat);          // (-x, -z, -y, w)

	// Manifest sockets: position + yaw_deg in one step
	enum class ESocketUse : uint8 { Heading, Mesh };
	VERSECORE_API FTransform ToUnrealSocketTransform(const FVerseThreeVector& P, double ThreeYawDeg, ESocketUse Use,
	                                                 const FVerseDeckFrame& Deck = FVerseDeckFrame::Local());
}

/** Blueprint and editor-utility access; same functions, no extra logic. */
UCLASS()
class VERSECORE_API UVerseCoordsLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()
public:
	UFUNCTION(BlueprintPure, Category = "Verse|Coords") static FVector  ThreeToUnrealPosition(const FVerseThreeVector& P, const FVerseDeckFrame& Deck);
	UFUNCTION(BlueprintPure, Category = "Verse|Coords") static FVerseThreeVector UnrealToThreePosition(const FVector& PCm, const FVerseDeckFrame& Deck);
	UFUNCTION(BlueprintPure, Category = "Verse|Coords") static double   ThreeYawDegToUnrealHeading(double ThreeYawDeg);
	UFUNCTION(BlueprintPure, Category = "Verse|Coords") static double   ThreeYawDegToUnrealMeshYaw(double ThreeYawDeg);
};
```

Rules for callers:

- The literal `100` (or `0.01`) for metre/centimetre never appears outside
  `VerseCoords.cpp`; callers use `MetresToCm`. New tuning data is authored
  in U units directly (README: numbers do not carry over), so most gameplay
  code never calls this API at all.
- No module re-derives the mapping (no local `FVector(x, z, y)`).

## 5. Required tests

Low-level automation tests in `VerseCore/Private/Tests/VerseCoordsTest.cpp`
(`WITH_DEV_AUTOMATION_TESTS`, filter `Verse.Contract.Coords.*`, so they run with
every `Verse.Contract.*` filter of `orchestration.md` 3.3), run headless in
`unreal-build`. Tolerances: positions 1e-6 cm, directions and quaternion
components 1e-12, angles 1e-9 deg.

| # | Test | Asserts |
|---|---|---|
| 1 | `Basis` | T +X → U (100, 0, 0); T +Y → (0, 0, 100); T +Z → (0, 100, 0) |
| 2 | `Handedness` | `M(a × b) == -(Ma × Mb)` for 1,000 seeded pairs; det(M) = -1 |
| 3 | `RoundTripPosition` | 10,000 seeded points in ±10 km and random deck offsets: T→U→T and U→T→U within tolerance |
| 4 | `HangarGolden` | every row of table 3.1 and 3.2 exactly |
| 5 | `HeadingMatchesDirFromAngles` | for 10,000 seeded (ψ, θ): `ToUnrealViewRotation(ψ, θ).Vector() == ToUnrealDirection(dirFromAngles(ψ, θ))` |
| 6 | `RightAxisParity` | `ToUnrealDirection((-cos ψ, 0, sin ψ)) == FRotationMatrix(FRotator(0, φ, 0)).GetUnitAxis(EAxis::Y)` |
| 7 | `YawWrap` | outputs in (-180, 180]; ψ = -90° → 180; ψ = 180° → -90; `ToThreeYawRad` outputs in (-π, π]; round trip of every table 3.3 row |
| 8 | `QuatConjugation` | `ToUnrealQuat(q).RotateVector(Mv) == M(q·v)` for 10,000 seeded unit quaternions and vectors; `ToThreeQuat(ToUnrealQuat(q)) == q` |
| 9 | `MeshYawIsHeadingMinus90` | `Normalize(heading - 90) == ToUnrealMeshYawDeg` for all ψ; yaw-only quaternion route gives the same mesh yaw |
| 10 | `BoxOrder` | `ToUnrealBox` min ≤ max on every axis for every `ArenaBox` in the golden file |
| 11 | `DeckFrameTranslationOnly` | an offset frame changes positions by exactly `OriginCm` and leaves directions, headings and quaternions untouched |
| 12 | `YawRateSign` | `ToUnrealYawRateDeg(+1 rad/s) == -57.2957795…` |
| 13 | `CrossLanguageGolden` | reads `unreal/Verse/Tests/Data/coords_golden.json` (T inputs plus expected U outputs); a vitest in the frontend reads the same file and checks the T side with `combat/math.ts`, so both languages agree on one file |
| 14 | `NoStrayScale` (CI script, not C++) | grep fails the build on `* 100`/`/ 100`/`0.01` next to position or metre identifiers outside `VerseCoords.cpp`, and on `FVector(.*\.X, .*\.Z, .*\.Y)` patterns outside it |

## Frozen interface

Other packages may rely on all of the following, and nothing else:

- The mapping `U = 100 · (x, z, y) + O_deck` for points, `(x, z, y)` for
  directions, and its inverse; deck frames are translation-only.
- Heading `φ = Normalize(90 - ψ_deg)`, pitch unchanged in sign, yaw rates
  negated, ranges (-180, 180] and (-π, π].
- Mesh yaw `= -ψ_deg = heading - 90`; quaternions `(-x, -z, -y, w)` both ways;
  pawn skeletal mesh relative yaw `-90°`.
- Deck-local origin at the plan's (x = 0, z = 0) floor point, floor at Z = 0.
- The types `FVerseThreeVector`, `FVerseDeckFrame`, the functions in
  `Verse::Coords` and `UVerseCoordsLibrary` with the signatures in section 4,
  and the golden file `unreal/Verse/Tests/Data/coords_golden.json`.
- Manifests and bridge payloads stay in T units; conversion happens once at
  the `VerseDecks` and `VerseBridge` decoding edge.

## Change rule

Changes go through the integration owner only. A change is a pull request that
edits this file, `VerseCoords.h/.cpp`, the golden file and the tests together,
lists every consumer it affects (`VerseDecks`, `VerseBridge`, `VerseCrew`,
`VerseScreens`, `VerseBot`, `VerseHarness` at least), and lands before any
consumer relies on it. Adding a new function is allowed by the same rule;
changing the meaning of an existing one is not, it gets a new name instead.

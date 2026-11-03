#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"

#include "VersePenetrationPhysicalMaterial.generated.h"

/** Roles of non-destructible world geometry (destruction.md 2: "through its physical material"). */
UENUM(BlueprintType)
enum class EVerseWorldSurface : uint8
{
	/** The hangar hall floor (DR4: never changes state, never passes). */
	HallFloor,
	/** Structural walls, columns, slabs. */
	StructuralWall,
	/** Structural beams and frames. */
	StructuralBeam
};

// WP03.7: non-destructible world geometry gets its row of DA_PenetrationTable through its
// physical material. The physical material is named for its surface role
// (`PM_Verse_HallFloor`, `PM_Verse_StructuralWall`, `PM_Verse_StructuralBeam`, optionally with a
// suffix such as `_Painted`); the zone owners assign those to their architecture. Hall floor and
// structural walls are `concrete`, structural beams `armor_steel`. Destructible pieces never
// use this: their row comes from the piece itself. Matching by name keeps VerseDestruction
// inside its module edges (architecture.md 2), which do not include PhysicsCore.

namespace VersePenetration
{
	/** The frozen mapping of world surfaces to table rows (destruction.md 2). */
	VERSEDESTRUCTION_API EVersePenetrationMaterial WorldSurfaceMaterial(EVerseWorldSurface Surface);

	/** `PM_Verse_<Role>`: the physical material name of a surface role. */
	VERSEDESTRUCTION_API FString PhysicalMaterialName(EVerseWorldSurface Surface);

	/** The surface role a physical material name stands for; false when it names none. */
	VERSEDESTRUCTION_API bool SurfaceFromPhysicalMaterialName(const FString& Name, EVerseWorldSurface& OutSurface);

	/**
	 * Row for a hit on geometry that is not a registered piece: the row of its Verse physical
	 * material, else `concrete`. Unmapped blocking geometry therefore never lets a bolt through.
	 */
	VERSEDESTRUCTION_API EVersePenetrationMaterial ResolveWorldMaterial(const UObject* PhysicalMaterial);
}

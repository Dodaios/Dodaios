#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "PhysicalMaterials/PhysicalMaterial.h"

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

/**
 * Physical material of non-destructible world geometry (WP03.7). Its surface role maps to a
 * row of DA_PenetrationTable: hall floor and structural walls are `concrete`, structural beams
 * `armor_steel`. Destructible pieces never use it: their row comes from the piece itself.
 */
UCLASS(BlueprintType)
class VERSEDESTRUCTION_API UVersePenetrationPhysicalMaterial : public UPhysicalMaterial
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Verse")
	EVerseWorldSurface Surface = EVerseWorldSurface::StructuralWall;

	EVersePenetrationMaterial GetPenetrationMaterial() const;
};

namespace VersePenetration
{
	/** The frozen mapping of world surfaces to table rows (destruction.md 2). */
	VERSEDESTRUCTION_API EVersePenetrationMaterial WorldSurfaceMaterial(EVerseWorldSurface Surface);

	/**
	 * Row for a hit on geometry that is not a registered piece: the Verse physical material's
	 * row, else `concrete`. Unmapped blocking geometry therefore never lets a bolt through.
	 */
	VERSEDESTRUCTION_API EVersePenetrationMaterial ResolveWorldMaterial(const UPhysicalMaterial* PhysicalMaterial);
}

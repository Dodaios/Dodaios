#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTuning.h"
#include "Destruction/VerseDestructionTypes.h"

#include "VersePieceTypes.generated.h"

// Plain data of the destruction runtime (contracts/destruction.md 3, 6.1, 7). Everything here
// is engine-world free, so the server simulation (FVerseDestructionSim) runs and is tested
// without a UWorld.

/** One authored nav link of a piece, piece-local cm (destruction.md 6.1). */
USTRUCT(BlueprintType)
struct VERSEDESTRUCTION_API FVersePieceNavLink
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, Category = "Nav")
	FVector Start = FVector::ZeroVector;

	UPROPERTY(EditAnywhere, Category = "Nav")
	FVector End = FVector::ZeroVector;
};

/** Which links of a piece are live in a state (destruction.md 6.1). */
enum class EVersePieceNavLinkKind : uint8
{
	/** Low breach: a mantle link through the opening while Breached. */
	Mantle,
	/** Destroyed catwalk: drop-down links to the floor below. */
	Drop
};

/**
 * Static description of one piece, the same on server and clients. Built from an
 * AVerseDestructible when the manager registers it, or directly by tests.
 */
struct VERSEDESTRUCTION_API FVersePieceDef
{
	FGuid Guid;
	EVersePieceClass Class = EVersePieceClass::WallPanel;
	EVersePenetrationMaterial Material = EVersePenetrationMaterial::SheetMetal;

	/** Piece to world. */
	FTransform Transform = FTransform::Identity;

	/** Proxy bounds per state, piece-local; Damaged and Repairing reuse others (see GetLocalBounds). */
	FBox IntactBounds = FBox(ForceInit);
	TArray<FBox, TInlineAllocator<4>> HoledBounds;
	TArray<FBox, TInlineAllocator<4>> BreachedBounds;
	/** Optional authored Remains proxy; invalid = no gameplay collision when Destroyed. */
	FBox RemainsBounds = FBox(ForceInit);

	/** Intact proxy vertices, piece-local (the breach side-effect radius test of destruction.md 3.2). */
	TArray<FVector> ProxyVertices;

	/** Opening centroid per Holed / Breached variant, piece-local (destruction.md 3.1). */
	TArray<FVector, TInlineAllocator<4>> HoledCentroids;
	TArray<FVector, TInlineAllocator<4>> BreachedCentroids;

	TArray<FVersePieceNavLink> MantleLinks;
	TArray<FVersePieceNavLink> DropLinks;

	/** Proxy bounds for a state and variant, piece-local; invalid when the state has no proxy. */
	FBox GetLocalBounds(EVersePieceState State, uint8 Variant) const;

	/** The same in world space (axis-aligned box around the transformed local box). */
	FBox GetWorldBounds(EVersePieceState State, uint8 Variant) const;

	/** Nearest variant to a piece-local point; 0 when no centroids are authored. */
	static uint8 NearestVariant(TConstArrayView<FVector> Centroids, const FVector& LocalPoint);

	/** True if any Intact proxy vertex (or, without vertices, the Intact box) lies within Radius of the world point. */
	bool IsWithinRadius(const FVector& WorldPoint, float RadiusCm) const;
};

/** Repair priority of a class (destruction.md 7 "Order"): lower first. */
VERSEDESTRUCTION_API int32 VerseRepairClassPriority(EVersePieceClass Class);

/** The material a class must use (destruction.md 3.2). */
VERSEDESTRUCTION_API EVersePenetrationMaterial VerseMaterialOfClass(EVersePieceClass Class);

/** Materials that never change state (DR4). */
VERSEDESTRUCTION_API bool VerseMaterialNeverBreaks(EVersePenetrationMaterial Material);

/**
 * WP06 start values that are not part of DA_DestructionTuning (drone flight, impulses, debris
 * body counts). Mirrors unreal/Verse/Data/destruction/tuning.json; tuned through the harness.
 */
struct VERSEDESTRUCTION_API FVerseDestructionStartValues
{
	float DroneSpeedCmS = 600.f;
	uint32 DroneNoiseIntervalMs = 1000;
	float BoltImpulseNs = 20.f;
	float MeleeImpulseNs = 40.f;
	float BreachImpulseNs = 1500.f;
	uint8 BoltStrainRadiusCm = 20;
	uint8 MeleeStrainRadiusCm = 30;
	/** Hub events are coalesced per piece per tick always; multicasts beyond the rate cap are dropped (the fast array stays the truth). */
	bool bCoalescePerTick = true;
};

/** Everything the simulation needs from DA_DestructionTuning plus the start values. */
struct VERSEDESTRUCTION_API FVerseDestructionSimTuning
{
	TMap<EVersePieceClass, FVersePieceClassTuning> Classes;
	float BreachSideRadiusCm = 150.f;
	float RepairDelayS = 60.f;
	int32 MaxActiveDrones = 3;
	float DroneMaxHp = 30.f;
	float RepairEncroachMarginCm = 10.f;
	float RepairEncroachRecheckS = 0.5f;
	float NavDirtyMarginCm = 50.f;
	int32 NavMaxTilesInFlight = 4;
	int32 MaxFractureEventsPerSecond = 64;
	FVerseDestructionStartValues Start;

	/** Contract values (a default UVerseDestructionTuning). */
	static FVerseDestructionSimTuning Contract();
	static FVerseDestructionSimTuning FromAsset(const UVerseDestructionTuning& Asset);

	const FVersePieceClassTuning& ClassRow(EVersePieceClass Class) const;
};

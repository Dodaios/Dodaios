#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "Engine/DataAsset.h"

#include "VerseDestructionTuning.generated.h"

/** One row of the piece class table (destruction.md 3.2). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVersePieceClassTuning
{
	GENERATED_BODY()

	UPROPERTY(EditDefaultsOnly, Category = "Destruction")
	EVersePenetrationMaterial Material = EVersePenetrationMaterial::SheetMetal;

	/** 0 = the class has no HP (catwalk: breach charge only). */
	UPROPERTY(EditDefaultsOnly, Category = "Destruction")
	float MaxHp = 0.f;

	/** Bullets move Intact to Damaged on the first hit. */
	UPROPERTY(EditDefaultsOnly, Category = "Destruction")
	bool bDamagedOnFirstHit = true;

	/** Bullets move to Holed at or below this HP; negative = never Holed by bullets. */
	UPROPERTY(EditDefaultsOnly, Category = "Destruction")
	float HoledAtOrBelowHp = -1.f;

	/** A breach charge moves the target to Breached (walls). */
	UPROPERTY(EditDefaultsOnly, Category = "Destruction")
	bool bBreachedByCharge = false;

	/** HP 0 moves to Destroyed (glass, ceiling). */
	UPROPERTY(EditDefaultsOnly, Category = "Destruction")
	bool bDestroyedAtZeroHp = false;

	/** A breach charge moves the target to Destroyed (glass, catwalk, ceiling). */
	UPROPERTY(EditDefaultsOnly, Category = "Destruction")
	bool bDestroyedByCharge = false;

	/** Melee on a Damaged piece destroys it (glass only). */
	UPROPERTY(EditDefaultsOnly, Category = "Destruction")
	bool bDestroyedByMeleeWhenDamaged = false;

	UPROPERTY(EditDefaultsOnly, Category = "Destruction", meta = (Units = "s"))
	float RepairTimeS = 8.f;
};

/**
 * DA_DestructionTuning: the thresholds, HP, times and budgets of destruction.md 3, 5, 7 and 10.
 * Fields frozen; values retune only through the contract's change rule. A new asset starts
 * with the contract values.
 */
UCLASS(BlueprintType)
class VERSECORE_API UVerseDestructionTuning : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	UVerseDestructionTuning();

	UPROPERTY(EditDefaultsOnly, Category = "Classes")
	TMap<EVersePieceClass, FVersePieceClassTuning> Classes;

	/** Other breakable pieces within this distance of a detonation go Holed or Destroyed (3.2). */
	UPROPERTY(EditDefaultsOnly, Category = "Breach", meta = (Units = "cm"))
	float BreachSideRadiusCm = 150.f;

	UPROPERTY(EditDefaultsOnly, Category = "Holes")
	int32 HolesPerPiece = 24;

	UPROPERTY(EditDefaultsOnly, Category = "Holes")
	int32 HolesPerArena = 512;

	UPROPERTY(EditDefaultsOnly, Category = "Holes")
	int32 GlowingHolesMax = 128;

	/** Exponential cooling time constant of a hole rim. */
	UPROPERTY(EditDefaultsOnly, Category = "Holes", meta = (Units = "s"))
	float HoleGlowTauS = 1.2f;

	UPROPERTY(EditDefaultsOnly, Category = "Holes", meta = (Units = "s"))
	float HoleGlowEndS = 4.f;

	/** After the last state-changing or hole-making damage. */
	UPROPERTY(EditDefaultsOnly, Category = "Repair", meta = (Units = "s"))
	float RepairDelayS = 60.f;

	UPROPERTY(EditDefaultsOnly, Category = "Repair")
	int32 MaxActiveDrones = 3;

	UPROPERTY(EditDefaultsOnly, Category = "Repair")
	float DroneMaxHp = 30.f;

	/** Completion waits while a pawn overlaps the Intact proxy bounds plus this. */
	UPROPERTY(EditDefaultsOnly, Category = "Repair", meta = (Units = "cm"))
	float RepairEncroachMarginCm = 10.f;

	UPROPERTY(EditDefaultsOnly, Category = "Repair", meta = (Units = "s"))
	float RepairEncroachRecheckS = 0.5f;

	/** Old and new proxy bounds grow by this when marking nav tiles dirty (6.1). */
	UPROPERTY(EditDefaultsOnly, Category = "Nav", meta = (Units = "cm"))
	float NavDirtyMarginCm = 50.f;

	UPROPERTY(EditDefaultsOnly, Category = "Nav")
	int32 NavMaxTilesInFlight = 4;

	UPROPERTY(EditDefaultsOnly, Category = "Budget")
	int32 MaxDebrisBodiesHigh = 400;

	UPROPERTY(EditDefaultsOnly, Category = "Budget")
	int32 MaxDebrisBodiesLow = 150;

	UPROPERTY(EditDefaultsOnly, Category = "Budget")
	int32 MaxBodiesPerFracture = 40;

	/** Fragments smaller than this are Niagara particles, not rigid bodies. */
	UPROPERTY(EditDefaultsOnly, Category = "Budget", meta = (Units = "cm"))
	float MinRigidFragmentCm = 5.f;

	UPROPERTY(EditDefaultsOnly, Category = "Budget", meta = (Units = "s"))
	float DebrisSleepS = 3.f;

	UPROPERTY(EditDefaultsOnly, Category = "Budget", meta = (Units = "s"))
	float DebrisDespawnHighS = 10.f;

	UPROPERTY(EditDefaultsOnly, Category = "Budget", meta = (Units = "s"))
	float DebrisDespawnLowS = 6.f;

	UPROPERTY(EditDefaultsOnly, Category = "Budget", meta = (Units = "s"))
	float DebrisFadeS = 0.3f;

	UPROPERTY(EditDefaultsOnly, Category = "Budget")
	int32 MaxGeometryCollectionActors = 32;

	UPROPERTY(EditDefaultsOnly, Category = "Budget")
	int32 MaxFractureEventsPerSecond = 64;

	/** The class table of destruction.md 3.2. */
	static TMap<EVersePieceClass, FVersePieceClassTuning> MakeContractClasses();
};

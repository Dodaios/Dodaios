#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "Engine/DataAsset.h"
#include "GameplayTagContainer.h"

#include "VersePenetrationTable.generated.h"

/** One material row of DA_PenetrationTable (destruction.md 2). Columns frozen. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVersePenetrationRow
{
	GENERATED_BODY()

	/** Verse.Material.<id> */
	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	FGameplayTag MaterialTag;

	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	EVersePenetrationMaterial WireId = EVersePenetrationMaterial::SheetMetal;

	UPROPERTY(EditDefaultsOnly, Category = "Penetration", meta = (Units = "cm"))
	float RefThicknessCm = 1.f;

	/** Power units at the reference thickness (100 = assault rifle). */
	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	float PenetrationCost = 0.f;

	/** Damage multiplier after passing. */
	UPROPERTY(EditDefaultsOnly, Category = "Penetration", meta = (ClampMin = "0", ClampMax = "1"))
	float DamageMultiplier = 1.f;

	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	bool bBreakableByBullets = false;

	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	bool bBreakableByBreach = false;

	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	EVerseDebrisType DebrisType = EVerseDebrisType::SparksOnly;
};

/**
 * DA_PenetrationTable (destruction.md 2): one row per material, indexed by wire id. The cost
 * formula and the 3-piece limit are frozen; the numbers are retuned only through the contract's
 * change rule. A new asset starts with the contract table.
 */
UCLASS(BlueprintType)
class VERSECORE_API UVersePenetrationTable : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	UVersePenetrationTable();

	/** Index = wire id. */
	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	TArray<FVersePenetrationRow> Rows;

	/** The table of destruction.md 2, in wire order. */
	static TArray<FVersePenetrationRow> MakeContractRows();

	/** Row by wire id, nullptr when the id is unknown. */
	const FVersePenetrationRow* FindRow(uint8 WireId) const;

	/** cost x clamp(traced / ref, 0.5, 3.0) */
	static float PassCost(const FVersePenetrationRow& Row, float TracedThicknessCm);
};

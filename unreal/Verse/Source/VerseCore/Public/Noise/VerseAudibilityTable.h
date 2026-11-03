#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "GameplayTagContainer.h"

#include "VerseAudibilityTable.generated.h"

/** One noise row (bot.md 3.2): range and position error multiplier for one Noise.* tag. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseAudibilityRow
{
	GENERATED_BODY()

	/** The Noise.* tag; the row key. */
	UPROPERTY(EditDefaultsOnly, Category = "Audibility")
	FGameplayTag Noise;

	/** Audible range; ignored when bWholeArena. Multiplied by the event loudness when bRangeScalesWithLoudness. */
	UPROPERTY(EditDefaultsOnly, Category = "Audibility", meta = (Units = "m"))
	float RangeM = 0.f;

	/** Heard anywhere in the arena. */
	UPROPERTY(EditDefaultsOnly, Category = "Audibility")
	bool bWholeArena = false;

	/** Range = loudness x RangeM (Noise.Fracture, Noise.Drone: loudness x 40 m). */
	UPROPERTY(EditDefaultsOnly, Category = "Audibility")
	bool bRangeScalesWithLoudness = false;

	/** Multiplier on the tier's hearing error sd (0 = exact, Noise.Impact). */
	UPROPERTY(EditDefaultsOnly, Category = "Audibility")
	float ErrorMultiplier = 1.f;
};

/**
 * DA_Audibility (bot.md 3.2): one table drives the bot's hearing and the person's audio
 * attenuation, so both hear the same world (fairness F6). A new asset starts with the
 * contract table. Crouch walk, prone crawl and standing still raise no noise, so they have no row.
 */
UCLASS(BlueprintType)
class VERSECORE_API UVerseAudibilityTable : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	UVerseAudibilityTable();

	UPROPERTY(EditDefaultsOnly, Category = "Audibility")
	TArray<FVerseAudibilityRow> Rows;

	/** The table of bot.md 3.2, one row per Noise.* tag in table order. */
	static TArray<FVerseAudibilityRow> MakeContractRows();

	const FVerseAudibilityRow* FindRow(const FGameplayTag& Noise) const;

	/** Audible range in metres for an event; a very large value for whole-arena rows; 0 for an unknown tag. */
	float GetAudibleRangeM(const FGameplayTag& Noise, float Loudness) const;

	/** Range used for whole-arena rows (larger than any deck). */
	static constexpr float WholeArenaRangeM = 100000.f;
};

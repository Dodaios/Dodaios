#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"

#include "VerseMeleeDefinition.generated.h"

/** The knife strike and the finisher geometry (combat-state.md 7). Fields frozen; values are start values. */
UCLASS(BlueprintType)
class VERSECORE_API UVerseMeleeDefinition : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	/** Not a one-shot: two strikes kill. */
	UPROPERTY(EditDefaultsOnly, Category = "Strike")
	float StrikeDamage = 55.f;

	UPROPERTY(EditDefaultsOnly, Category = "Strike", meta = (Units = "s"))
	float StrikeHitDelay = 0.15f;

	UPROPERTY(EditDefaultsOnly, Category = "Strike", meta = (Units = "s"))
	float StrikeCooldown = 0.7f;

	UPROPERTY(EditDefaultsOnly, Category = "Strike", meta = (Units = "m"))
	float StrikeRange = 2.f;

	/** deg */
	UPROPERTY(EditDefaultsOnly, Category = "Strike")
	float StrikeConeHalfAngle = 30.f;

	UPROPERTY(EditDefaultsOnly, Category = "Finisher", meta = (Units = "m"))
	float FinisherRange = 1.5f;

	UPROPERTY(EditDefaultsOnly, Category = "Finisher", meta = (Units = "m"))
	float FinisherMaxHeightDelta = 0.6f;

	/** theta at or below this is Front (deg); Back starts at 180 minus this. */
	UPROPERTY(EditDefaultsOnly, Category = "Finisher")
	float FrontHalfAngle = 60.f;

	/** phi limit (deg): the attacker must look at the victim. */
	UPROPERTY(EditDefaultsOnly, Category = "Finisher")
	float AttackerFacingMax = 45.f;

	UPROPERTY(EditDefaultsOnly, Category = "Finisher", meta = (Units = "s"))
	float FinisherDuration = 2.5f;

	UPROPERTY(EditDefaultsOnly, Category = "Finisher", meta = (Units = "s"))
	float FinisherKillTime = 2.1f;
};

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"

#include "VerseBotAdaptiveConfig.generated.h"

class UVerseBotTier;

/**
 * The adaptive mode (bot.md 9.2): unreal/Verse/Data/bot/adaptive.json, asset
 * /Game/Verse/Bot/Tiers/DA_BotAdaptive. A continuous skill s in [0, 1]: 0 = normal, 0.5 = hard,
 * 1 = elite. Fields and the interpolation rule are frozen; the values are start values.
 */
UCLASS(BlueprintType)
class VERSECORE_API UVerseBotAdaptiveConfig : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	/** Hard at match start. */
	UPROPERTY(EditDefaultsOnly, Category = "Adaptive", meta = (ClampMin = "0", ClampMax = "1"))
	float StartSkill = 0.5f;

	/** Rolling window of the last kills (either side). */
	UPROPERTY(EditDefaultsOnly, Category = "Adaptive")
	int32 WindowKills = 10;

	/** Person's share of kills in the window the controller aims for. */
	UPROPERTY(EditDefaultsOnly, Category = "Adaptive")
	float TargetPersonShare = 0.5f;

	/** No change while the share is within target +- deadband. */
	UPROPERTY(EditDefaultsOnly, Category = "Adaptive")
	float Deadband = 0.08f;

	/** ds = Gain x (share - target). */
	UPROPERTY(EditDefaultsOnly, Category = "Adaptive")
	float Gain = 0.25f;

	/** Bound on abs(ds). */
	UPROPERTY(EditDefaultsOnly, Category = "Adaptive")
	float MaxStepPerKill = 0.05f;

	/** No adjustment before this many kills. */
	UPROPERTY(EditDefaultsOnly, Category = "Adaptive")
	int32 WarmupKills = 4;

	/** When a new s is applied: the bot's respawn, never during an engagement. */
	UPROPERTY(EditDefaultsOnly, Category = "Adaptive")
	FName ApplyAt = TEXT("bot_respawn");

	/**
	 * The skill after one kill: unchanged during warm-up or inside the deadband, otherwise
	 * s + clamp(Gain x (share - target), -MaxStepPerKill, MaxStepPerKill), clamped to [0, 1].
	 */
	float NextSkill(float CurrentSkill, float PersonShare, int32 KillsSoFar) const;

	/**
	 * The interpolation rule of 9.2: every numeric field (float, int, float pair) piecewise linear,
	 * normal to hard on [0, 0.5] and hard to elite on [0.5, 1]; int fields round. S is clamped to
	 * [0, 1], so the result is never below normal or above elite. Writes every field of Out except
	 * TierId, which becomes "adaptive".
	 */
	static void InterpolateTier(const UVerseBotTier& Normal, const UVerseBotTier& Hard, const UVerseBotTier& Elite,
		float S, UVerseBotTier& Out);
};

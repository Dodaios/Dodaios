#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"

#include "VerseBotTier.generated.h"

/**
 * One bot tier (bot.md 9.1): /Game/Verse/Bot/Tiers/DA_BotTier_Normal, _Hard, _Elite. The source of
 * truth is unreal/Verse/Data/bot/tiers.json; the commandlet VerseImportBotTiers writes the assets.
 * Field names, types and groups are frozen, and so are the contract floors and caps below. The
 * defaults are the normal tier's start values. Units: ms, s, m, deg as the names say.
 */
UCLASS(BlueprintType)
class VERSECORE_API UVerseBotTier : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	/** Contract floor of WallbangMinBelief (bot.md 4.5). */
	static constexpr float WallbangMinBeliefFloor = 0.25f;
	/** Contract cap of WallbangMaxSourceAgeS (bot.md 4.5). */
	static constexpr float WallbangMaxSourceAgeCapS = 4.f;
	/** Contract cap of LearnWeightMax (bot.md 7.3). */
	static constexpr float LearnWeightMaxCap = 0.35f;
	/** Hysteresis on the current state's utility, fixed for all tiers (bot.md 5). */
	static constexpr float UtilityHysteresis = 0.18f;

	/** normal, hard, elite (AVersePlayerState::BotTier). */
	UPROPERTY(EditDefaultsOnly, Category = "Identity")
	FName TierId = TEXT("normal");

	/** Stimulus to first action, ms: mean, sd */
	UPROPERTY(EditDefaultsOnly, Category = "Perception")
	FVector2f ReactionMs = FVector2f(320.0f, 60.0f);

	UPROPERTY(EditDefaultsOnly, Category = "Perception")
	float PeripheralReactionMul = 1.6f;

	UPROPERTY(EditDefaultsOnly, Category = "Perception")
	float PartialExposureAcquireMul = 1.5f;

	UPROPERTY(EditDefaultsOnly, Category = "Perception")
	float TrackLatencyMs = 150.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Perception")
	float HearingErrorBaseM = 3.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Perception")
	float HearingErrorPerM = 0.1f;

	/** OU wander sd */
	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float AimNoiseDeg = 1.4f;

	/** OU rate k, 1/s */
	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float AimNoiseRate = 1.6f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float AcquireErrorDeg = 6.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float AcquireMs = 650.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float TurnRateDegS = 450.0f;

	/** 1/s */
	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float AimStiffness = 8.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float LeadSkill = 0.6f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float LeadNoise = 0.35f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float MotionWindowMs = 0.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float RecoilPatternComp = 0.35f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float RecoilResidualGain = 0.3f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float FireTolerance = 2.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float HeadAimChance = 0.05f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float AdsRangeM = 12.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float BurstRangeM = 30.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	int32 MaxBurstShots = 8;

	UPROPERTY(EditDefaultsOnly, Category = "Decision")
	float DecisionMs = 320.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Decision")
	float UtilityNoise = 0.08f;

	UPROPERTY(EditDefaultsOnly, Category = "Decision")
	float Aggression = 0.5f;

	UPROPERTY(EditDefaultsOnly, Category = "Decision")
	float CoverUse = 0.4f;

	UPROPERTY(EditDefaultsOnly, Category = "Decision")
	float FlankUse = 0.2f;

	UPROPERTY(EditDefaultsOnly, Category = "Decision")
	float PreferredRangeM = 14.0f;

	/** min, max */
	UPROPERTY(EditDefaultsOnly, Category = "Decision")
	FVector2f StrafeMs = FVector2f(700.0f, 1500.0f);

	UPROPERTY(EditDefaultsOnly, Category = "Movement")
	float LeanUse = 0.2f;

	UPROPERTY(EditDefaultsOnly, Category = "Movement")
	float CrouchPeekUse = 0.2f;

	UPROPERTY(EditDefaultsOnly, Category = "Movement")
	float ProneUse = 0.05f;

	UPROPERTY(EditDefaultsOnly, Category = "Movement")
	float SlideUse = 0.1f;

	UPROPERTY(EditDefaultsOnly, Category = "Movement")
	float NavLinkCostMul = 2.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Movement")
	float SoundDiscipline = 0.1f;

	UPROPERTY(EditDefaultsOnly, Category = "Movement")
	float PeekRepeatPenalty = 0.1f;

	UPROPERTY(EditDefaultsOnly, Category = "Gadgets and walls")
	float BulwarkUse = 0.2f;

	UPROPERTY(EditDefaultsOnly, Category = "Gadgets and walls")
	float BreachUse = 0.1f;

	UPROPERTY(EditDefaultsOnly, Category = "Gadgets and walls")
	float WallbangUse = 0.15f;

	/** Contract floor 0.25 */
	UPROPERTY(EditDefaultsOnly, Category = "Gadgets and walls")
	float WallbangMinBelief = 0.55f;

	/** Contract cap 4 s */
	UPROPERTY(EditDefaultsOnly, Category = "Gadgets and walls")
	float WallbangMaxSourceAgeS = 1.5f;

	UPROPERTY(EditDefaultsOnly, Category = "Gadgets and walls")
	float WallbangMinDamageFrac = 0.3f;

	UPROPERTY(EditDefaultsOnly, Category = "Gadgets and walls")
	float PrefireChance = 0.1f;

	UPROPERTY(EditDefaultsOnly, Category = "Melee and reload")
	float StalkUse = 0.1f;

	UPROPERTY(EditDefaultsOnly, Category = "Melee and reload")
	float MaxStalkS = 4.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Melee and reload")
	float FinisherCommitConfidence = 0.8f;

	UPROPERTY(EditDefaultsOnly, Category = "Melee and reload")
	float KnifeChoice = 0.2f;

	UPROPERTY(EditDefaultsOnly, Category = "Melee and reload")
	float TacticalReloadAtFrac = 0.25f;

	UPROPERTY(EditDefaultsOnly, Category = "Melee and reload")
	float ReloadOnlyWhenSafe = 0.3f;

	UPROPERTY(EditDefaultsOnly, Category = "Melee and reload")
	float PistolSwitchChance = 0.2f;

	/** Contract cap 0.35 */
	UPROPERTY(EditDefaultsOnly, Category = "Learning")
	float LearnWeightMax = 0.1f;

	UPROPERTY(EditDefaultsOnly, Category = "Learning")
	float LearnSamplesHalf = 12.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Learning")
	float HabitHalfLifeS = 180.0f;

	UPROPERTY(EditDefaultsOnly, Category = "Learning")
	float ExplorationRate = 0.25f;

	/** Writes the start values of bot.md 9.1 for normal, hard or elite; false for another id. */
	static bool ApplyStartValues(FName InTierId, UVerseBotTier& Out);

	/** True when every contract floor and cap holds. */
	bool SatisfiesContractBounds() const;

	/** Clamps the fields that have a contract floor or cap. */
	void ClampToContract();
};

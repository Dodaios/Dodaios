#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

#include "VerseGoreTypes.generated.h"

// Client-cosmetic gore (contracts/combat-state.md 8). Everything here is local to one viewer:
// nothing replicates, nothing collides, nothing feeds back into gameplay (rule D6).

/** Material parameter names a character material reads to draw wound masks (WP05.4). */
namespace VerseGoreParams
{
	/** Scalar: number of live wounds (0..16). */
	inline const FName WoundCount(TEXT("Verse_WoundCount"));
	/** Vector per wound, `Verse_Wound_00` .. `Verse_Wound_15`: xyz = reference-pose component-space
	 *  position in cm (compare against the material's pre-skinned position), w = radius in cm. */
	VERSEGORE_API FName WoundSlot(int32 Index);
	/** Scalar 0..1 a body material may use to wet the whole mask (pool-time darkening). */
	inline const FName WoundWetness(TEXT("Verse_WoundWetness"));
}

/** Frozen caps of acceptance row A5.4 and the start values of the effects (tuning, not frozen). */
struct VERSEGORE_API FVerseGoreTuning
{
	/** A5.4 caps. */
	int32 MaxSpatterDecals = 256;
	int32 MaxPools = 16;
	int32 MaxWoundsPerCharacter = 16;
	/** Droplets alive at once across all bursts (oldest first recycled). */
	int32 MaxDroplets = 1536;
	int32 MaxFlashes = 32;

	/** Spatter: how far blood flies past the body along the bolt, cm. */
	float SpatterRangeCm = 380.f;
	/** Spatter cone half-angle around the bolt direction, degrees. */
	float SpatterConeDeg = 14.f;
	/** Floor drip trace length below the impact, cm. */
	float DripTraceCm = 260.f;
	/** Spatter decal size at contact and at full range, cm (half extents of the projected square). */
	float SpatterSizeNearCm = 34.f;
	float SpatterSizeFarCm = 14.f;
	float DripSizeCm = 16.f;
	/** Decal projection depth, cm. */
	float DecalDepthCm = 12.f;

	/** Pools: radius at full growth, cm, and growth time, s (WP05.5). */
	float PoolRadiusCm = 85.f;
	float PoolStartFraction = 0.08f;
	float PoolGrowSeconds = 4.f;
	float PoolTraceCm = 320.f;

	/** Wounds: radius range, cm, mapped from damage 10..60. */
	float WoundRadiusMinCm = 2.5f;
	float WoundRadiusMaxCm = 6.f;

	/** Bursts: droplet life and speeds, cm/s. */
	float DropletLifeSeconds = 0.7f;
	float DropletSpeedCm = 520.f;
	float DropletBackSprayFraction = 0.3f;
	float DropletSizeCm = 1.6f;
	float GravityCm = 980.f;

	/** Reduced: neutral impact flash life, s, and size, cm. */
	float FlashLifeSeconds = 0.08f;
	float FlashSizeCm = 14.f;

	/** Finisher cut to black is ended by Recover or Aborted; this is the safety end, s. */
	float CutToBlackTimeoutSeconds = 4.f;

	/** Droplets per burst by zone at 30 damage; scaled by damage / 30 within [0.5, 2]. */
	static int32 BaseDroplets(EVerseHitZone Zone);
	/** Spatter traces per hit by zone (killing blows add one). */
	static int32 SpatterTraces(EVerseHitZone Zone);
};

/** Budget counters reported to the harness (WP05.8, A5.4). */
USTRUCT(BlueprintType)
struct VERSEGORE_API FVerseGoreBudget
{
	GENERATED_BODY()

	/** Live now. */
	UPROPERTY(BlueprintReadOnly) int32 SpatterDecals = 0;
	UPROPERTY(BlueprintReadOnly) int32 Pools = 0;
	UPROPERTY(BlueprintReadOnly) int32 Droplets = 0;
	UPROPERTY(BlueprintReadOnly) int32 Flashes = 0;
	UPROPERTY(BlueprintReadOnly) int32 WoundedCharacters = 0;
	UPROPERTY(BlueprintReadOnly) int32 MaxWoundsOnOneCharacter = 0;

	/** Peaks since the last reset. */
	UPROPERTY(BlueprintReadOnly) int32 PeakSpatterDecals = 0;
	UPROPERTY(BlueprintReadOnly) int32 PeakPools = 0;
	UPROPERTY(BlueprintReadOnly) int32 PeakDroplets = 0;
	UPROPERTY(BlueprintReadOnly) int32 PeakWoundsOnOneCharacter = 0;

	/** Totals since the last reset. */
	UPROPERTY(BlueprintReadOnly) int32 HitsHandled = 0;
	UPROPERTY(BlueprintReadOnly) int32 DeathsHandled = 0;
	UPROPERTY(BlueprintReadOnly) int32 FinisherPhasesHandled = 0;
	UPROPERTY(BlueprintReadOnly) int32 DecalsSpawned = 0;
	UPROPERTY(BlueprintReadOnly) int32 DecalsRecycled = 0;
	UPROPERTY(BlueprintReadOnly) int32 PoolsRecycled = 0;
	UPROPERTY(BlueprintReadOnly) int32 WoundsRecycled = 0;
	UPROPERTY(BlueprintReadOnly) int32 DropletsSpawned = 0;
	UPROPERTY(BlueprintReadOnly) int32 FlashesSpawned = 0;
	UPROPERTY(BlueprintReadOnly) int32 Purges = 0;

	/** Game-thread cost of handling one hit, ms (mean and worst). */
	UPROPERTY(BlueprintReadOnly) double HitMeanMs = 0.0;
	UPROPERTY(BlueprintReadOnly) double HitMaxMs = 0.0;
	/** Game-thread cost of one gore tick, ms (mean and worst). */
	UPROPERTY(BlueprintReadOnly) double TickMeanMs = 0.0;
	UPROPERTY(BlueprintReadOnly) double TickMaxMs = 0.0;

	/** Accumulators behind the means. */
	double HitTotalMs = 0.0;
	double TickTotalMs = 0.0;
	int64 Ticks = 0;
};

/** One finisher cut to black as the Reduced level plays it (A5.5). */
struct FVerseGoreCutToBlack
{
	bool bActive = false;
	int32 AttackerId = 0;
	int32 VictimId = 0;
	uint64 StartFrame = 0;
	uint64 EndFrame = 0;
	double StartTime = 0.0;
	int32 Count = 0;
};

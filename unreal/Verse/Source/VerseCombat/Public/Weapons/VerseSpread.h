#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

class UVerseWeaponDefinition;

/** Everything the spread formula of combat-state.md 4.4 reads at the moment of a shot. */
struct FVerseSpreadInput
{
	EVerseStance Stance = EVerseStance::Stand;
	float AdsBlend = 0.f;
	/** Horizontal speed, m/s. */
	float HorizontalSpeedMps = 0.f;
	bool bAirborne = false;
};

/**
 * Spread, bloom, first-shot accuracy, the per-shot seed and the server's fire validation
 * (combat-state.md 4.4). Pure functions plus a small bloom state; the server and the owning client
 * evaluate the same inputs and draw the same direction.
 */
struct VERSECOMBAT_API FVerseSpread
{
	/** Server-side tolerance on the shot direction beyond sigma, degrees. */
	static constexpr float DirectionToleranceDeg = 1.5f;
	/** Largest accepted distance of the fire origin from the rewound eye point, cm. */
	static constexpr float OriginToleranceCm = 30.f;

	/** Bloom, degrees; grows per shot, decays at BloomRecoveryRate after BloomRecoveryDelay. */
	float Bloom = 0.f;
	float LastShotTime = -1000.f;

	/** True when the next shot at `Now` is a first shot (rested at least FirstShotRestTime). */
	bool IsFirstShot(const UVerseWeaponDefinition& W, float Now) const;

	/** sigma of 4.4 for a shot at `Now` (before this shot's bloom is added). */
	float SigmaFor(const UVerseWeaponDefinition& W, const FVerseSpreadInput& In, float Now) const;

	/** sigma without the first-shot rule and without bloom decay (the server's validation bound uses this with Bloom = BloomMax). */
	static float RestingSigma(const UVerseWeaponDefinition& W, const FVerseSpreadInput& In, float BloomDeg);

	/** Decay bloom up to `Now`; call each tick or before a shot. */
	void DecayTo(const UVerseWeaponDefinition& W, float Now, float Dt);

	/** Registers a shot at `Now`: first shot resets bloom to 0, then bloom += BloomPerShot (capped). */
	void OnShot(const UVerseWeaponDefinition& W, float Now);

	/** seed = Hash(shooter net id, shot counter, match seed). */
	static uint32 ShotSeed(uint32 ShooterNetId, uint16 ShotCounter, uint32 MatchSeed);

	/** dir = uniform in the cone of half-angle sigma around Forward, from VerseRng(seed, n, Spread). */
	static FVector ShotDirection(const FVector& Forward, float SigmaDeg, uint32 Seed, int32 ShotIndex);

	/** Server check of a fire request (4.4). False means the shot is answered with Rejected. */
	static bool ValidateFire(const FVector& Origin, const FVector& Dir, const FVector& RewoundEye,
		const FVector& ServerForward, float SigmaDeg);
};

/**
 * Cyclic fire cadence with sub-tick timing. Shots are scheduled exactly FireInterval apart; a tick
 * fires every shot whose scheduled time has passed, so the measured rate equals RPM at any tick
 * rate and each shot carries its exact time (the projectile manager advances it by the remainder).
 */
struct VERSECOMBAT_API FVerseFireCadence
{
	/** Earliest time the next shot may go. */
	float NextShotTime = -1000.f;
	/** Rounds left in the current burst (Burst mode). */
	int32 BurstLeft = 0;
	/** Trigger was held on the previous tick (Semi needs a fresh press). */
	bool bTriggerWasDown = false;

	/**
	 * Scheduled times of the shots to fire during the tick ending at `Now`, given the trigger and the
	 * rounds available. `TickStart` is the start of the tick.
	 */
	void Collect(const UVerseWeaponDefinition& W, bool bTriggerDown, float TickStart, float Now, int32 RoundsAvailable,
		TArray<float>& OutShotTimes);

	/** Server check: a shot at `Time` is not earlier than the cadence allows (1 ms grace). */
	bool AllowsShotAt(const UVerseWeaponDefinition& W, float Time) const;
};

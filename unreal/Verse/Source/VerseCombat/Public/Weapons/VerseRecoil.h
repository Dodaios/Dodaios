#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

class UVerseWeaponDefinition;

/**
 * Recoil state of one weapon (combat-state.md 4.1, 4.2, 11.2). Not replicated: the server and the
 * owning client simulate it identically from the same seed, stance, ADS blend and look input (R5).
 * Angles are degrees, X = pitch (positive = up), Y = yaw (positive = right).
 */
struct VERSECOMBAT_API FVerseRecoilState
{
	/** Shot index n within the current spray. */
	int32 ShotIndex = 0;

	/** Time of the last shot, seconds (server time on the server, predicted server time on the owner). */
	float LastShotTime = -1000.f;

	/** A: recoil applied and not yet recovered or compensated. */
	FVector2f Accumulated = FVector2f::ZeroVector;

	/** Spread bloom, degrees (4.4). */
	float Bloom = 0.f;

	/** Kick still being applied over RecoilKickTime (ease-out). */
	FVector2f KickTotal = FVector2f::ZeroVector;
	FVector2f KickApplied = FVector2f::ZeroVector;
	float KickStartTime = -1000.f;

	/** m = RecoilStanceMultiplier[stance] * lerp(1, RecoilAdsMultiplier, ads). */
	static float Multiplier(const UVerseWeaponDefinition& W, EVerseStance Stance, float AdsBlend);

	/** The smallest stance x ADS multiplier of the weapon (m_min of R1). */
	static float MinMultiplier(const UVerseWeaponDefinition& W);

	/** Index n the next shot at `Now` uses: 0 after PatternResetTime without a shot. */
	int32 ShotIndexAt(const UVerseWeaponDefinition& W, float Now) const;

	/** Resets the shot index when the pattern reset time has passed. Call before KickFor. */
	void BeginShot(const UVerseWeaponDefinition& W, float Now);

	/** k_n = m * (P(n) + f * |P(n)| * u_n), u_n from VerseRng(seed, n, Recoil). */
	FVector2f KickFor(const UVerseWeaponDefinition& W, float Multiplier, uint32 Seed) const;

	/** The pure kick formula for an explicit shot index. */
	static FVector2f KickAt(const UVerseWeaponDefinition& W, int32 N, float Multiplier, uint32 Seed);

	/** A += k_n, n += 1; starts the eased kick on the control rotation. */
	void OnShot(const FVector2f& Kick, float Now);

	/** Pulling against the recoil compensates it (4.2); the input itself is passed through unchanged. */
	void OnLookInput(FVector2f& InOutDelta);

	/** Part of the kick to add to the control rotation since the last call (ease-out over t_k). */
	FVector2f TickKick(const UVerseWeaponDefinition& W, float Now);

	/** Recovery of 4.2: returns the rotation to remove from the control rotation this tick. */
	FVector2f TickRecovery(const UVerseWeaponDefinition& W, float Now, float Dt);
};

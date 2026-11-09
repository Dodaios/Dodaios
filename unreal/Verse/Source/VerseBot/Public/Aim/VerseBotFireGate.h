#pragma once

#include "CoreMinimal.h"

class UVerseBotTier;

/** The fire discipline fields of a tier (bot.md 8.2, 9.1). */
struct VERSEBOT_API FVerseBotFireParams
{
	double FireTolerance = 2.0;
	double AdsRangeM = 12.0;
	double BurstRangeM = 30.0;
	int32 MaxBurstShots = 8;
	/** Single taps beyond TapRangeM (bot.md 8.2 "elite taps beyond 30 m"). */
	bool bTapsAtLongRange = false;

	/**
	 * From a tier. Taps belong to the elite tier; in adaptive mode they start once the effective
	 * skill is past the middle between hard and elite (s >= 0.75), where the interpolated tier is
	 * closer to elite than to hard. EffectiveSkill < 0 means a fixed tier.
	 */
	static FVerseBotFireParams FromTier(const UVerseBotTier& Tier, float EffectiveSkill = -1.f);
};

/** Why the gate holds fire this tick (presentation and tests). */
enum class EVerseBotFireBlock : uint8
{
	None,
	NoTarget,
	CannotFire,
	SpawnProtectedTarget,
	OffTarget,
	BurstRecovery,
	TapRest,
	FireInterval,
};

/** One tick of the fire gate's inputs. */
struct VERSEBOT_API FVerseBotFireGateInput
{
	double NowS = 0.0;
	/** A target the bot may shoot at (visible, or authorised by FVerseBotNoSightFire). */
	bool bHasTarget = false;
	/** Angle between the current view and the aim point, degrees. */
	double AimErrorDeg = 0.0;
	/** Angular half-width of the aimed part (FVerseBotAimPoint::HalfWidthDeg); a no-sight target uses the authorised disc. */
	double TargetHalfWidthDeg = 0.5;
	double RangeM = 0.0;
	/** The spawn protection effect is visible on the target (bot.md 5.2, 8.2): never fire. */
	bool bTargetSpawnProtected = false;
	bool bSprinting = false;
	bool bSliding = false;
	/** Round chambered or in the magazine, not reloading, not switching. */
	bool bCanFire = true;
	/** Full auto (hold the trigger) or semi (one press per shot). */
	bool bAutomatic = true;
	/** Weapon timing, seconds (UVerseWeaponDefinition). */
	double FireIntervalS = 0.1;
	double FirstShotRestS = 0.3;
	double PatternResetS = 0.35;
	/** The recoil controller says the spray ended (FVerseBotRecoilControl::IsSpraying false). */
	bool bRecoilSettled = true;
};

/** What the gate wants on the input frame this tick. */
struct VERSEBOT_API FVerseBotFireGateOutput
{
	/** Hold the Fire button this tick. */
	bool bHoldFire = false;
	/** The Fire bit goes down this tick (semi-auto shots and the first shot of a burst). */
	bool bPressFire = false;
	bool bAds = false;
	EVerseBotFireBlock Block = EVerseBotFireBlock::None;
};

/**
 * Fire discipline (bot.md 8.1 Fire tolerance, 8.2): fires only while the aim error is within
 * FireTolerance x the target's angular half-width; beyond BurstRangeM in bursts of at most
 * MaxBurstShots, then waits for the recoil to settle and the aim to come back; elite single taps
 * beyond 30 m with the weapon's first-shot rest between them; ADS beyond AdsRangeM unless
 * sprinting or sliding; never at a visibly spawn-protected target.
 *
 * The caller reports every shot that actually left the barrel with NotifyShot (own magazine count
 * on the HUD), so bursts count real shots.
 */
class VERSEBOT_API FVerseBotFireGate
{
public:
	/** bot.md 8.2: elite taps beyond this range, m. */
	static constexpr double TapRangeM = 30.0;

	void Reset(const FVerseBotFireParams& InParams);
	void SetParams(const FVerseBotFireParams& InParams) { Params = InParams; }
	const FVerseBotFireParams& GetParams() const { return Params; }

	FVerseBotFireGateOutput Evaluate(const FVerseBotFireGateInput& In);

	/** A shot left the barrel at TimeS. */
	void NotifyShot(double TimeS);

	int32 GetBurstShots() const { return BurstShots; }

	/** The fire tolerance test alone (bot.md 8.1, brain.ts:878-882). */
	static bool WithinTolerance(double AimErrorDeg, double HalfWidthDeg, double FireTolerance)
	{
		return AimErrorDeg <= FireTolerance * HalfWidthDeg;
	}

private:
	FVerseBotFireParams Params;
	int32 BurstShots = 0;
	double LastShotS = -1.0e9;
	bool bTriggerHeld = false;
	bool bWaitingForRecovery = false;
};

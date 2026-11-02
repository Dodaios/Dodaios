#pragma once

#include "CoreMinimal.h"

class UVerseBotTier;
class UVerseWeaponDefinition;
enum class EVerseStance : uint8;

/** The recoil fields of a tier (bot.md 9.1). */
struct VERSEBOT_API FVerseBotRecoilParams
{
	double PatternComp = 0.35;
	double ResidualGain = 0.3;
	double TrackLatencyMs = 150.0;

	static FVerseBotRecoilParams FromTier(const UVerseBotTier& Tier);
};

/**
 * Recoil control (bot.md 8.1 Recoil, against combat-state.md 4.1).
 *
 * The pattern part of every kick is public and identical every spray, so the bot knows it as a
 * practised person does and pulls against RecoilPatternComp of it the moment it fires
 * (predictive). The random part (f x |P(n)| x u_n) it cannot know: it sees it only as view motion
 * it did not cause, TrackLatencyMs later, and then corrects RecoilResidualGain of it.
 *
 * The result is a hand offset (pitch, yaw, degrees) the aim system adds to the aim target, so both
 * corrections go through the normal aim controller (turn cap, stiffness):
 *
 *   offset = -PatternComp x sum(m P(n))  -  ResidualGain x sum(observed_n - m P(n)) for shots older than the latency
 *
 * Over a spray the view therefore keeps (1 - PatternComp) of the pattern climb (A9.4). When no
 * shot was fired for the weapon's PatternResetTime the spray ends, the offset returns to zero and
 * the aim system re-syncs its hand to the perceived view, so leftover climb is corrected as a
 * person re-centres.
 */
class VERSEBOT_API FVerseBotRecoilControl
{
public:
	void Reset(const FVerseBotRecoilParams& InParams);
	void SetParams(const FVerseBotRecoilParams& InParams) { Params = InParams; }
	const FVerseBotRecoilParams& GetParams() const { return Params; }

	/**
	 * Own shot fired at TimeS. PatternKickDeg is m x P(n) (pitch, yaw), the known part of the kick;
	 * KickWindowS is how long the weapon takes to apply it (RecoilKickTime plus a tick);
	 * PatternResetS the weapon's PatternResetTime.
	 */
	void OnShot(double TimeS, const FVector2D& PatternKickDeg, double KickWindowS, double PatternResetS);

	/** View motion of this tick the bot did not cause: view now - view before - own look delta. */
	void ObserveUnexplainedMotion(double TimeS, const FVector2D& DeltaDeg);

	/** Matures residuals older than the track latency; ends the spray after PatternResetS. */
	void Tick(double NowS);

	/** True from the first shot until PatternResetS after the last one. */
	bool IsSpraying() const { return bSpraying; }

	/** Shots of the current spray. */
	int32 GetShotIndex() const { return Shots.Num(); }

	/** The offset to add to the aim target, degrees (pitch, yaw). */
	FVector2D GetHandOffsetDeg() const { return -Params.PatternComp * PatternSum - Params.ResidualGain * ResidualSeen; }

	FVector2D GetPatternSum() const { return PatternSum; }
	FVector2D GetResidualSeen() const { return ResidualSeen; }

	/** m x P(n) for a weapon, stance and ADS blend (combat-state.md 4.1). */
	static FVector2D PatternKick(const UVerseWeaponDefinition& Weapon, int32 ShotIndex, EVerseStance Stance, double AdsBlend);

private:
	struct FShot
	{
		double TimeS = 0.0;
		FVector2D Expected = FVector2D::ZeroVector;
		FVector2D Observed = FVector2D::ZeroVector;
		double KickWindowS = 0.0;
		bool bMature = false;
	};

	FVerseBotRecoilParams Params;
	TArray<FShot> Shots;
	FVector2D PatternSum = FVector2D::ZeroVector;
	FVector2D ResidualSeen = FVector2D::ZeroVector;
	double LastShotS = -1.0e9;
	double ResetAfterS = 0.35;
	bool bSpraying = false;
};

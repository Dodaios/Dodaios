#pragma once

#include "Bot/VersePerceptTypes.h"
#include "CoreMinimal.h"
#include "VerseRng.h"

class UVerseBotTier;

/** The tracking fields of a tier (bot.md 9.1). */
struct VERSEBOT_API FVerseBotTrackParams
{
	double TrackLatencyMs = 150.0;
	double MotionWindowMs = 0.0;
	double LeadSkill = 0.6;
	double LeadNoise = 0.35;
	double HeadAimChance = 0.05;

	static FVerseBotTrackParams FromTier(const UVerseBotTier& Tier);
};

/** What the bot believes about a sighted target at the current tick. */
struct VERSEBOT_API FVerseBotTrackedTarget
{
	/** Pelvis, extrapolated over the track latency with the bot's motion read, world cm. */
	FVector PelvisLocation = FVector::ZeroVector;
	/** The motion read, cm/s. */
	FVector Velocity = FVector::ZeroVector;
	EVerseStance Stance = EVerseStance::Stand;
	float FacingYawDeg = 0.f;
	uint8 VisibleMask = 0;
	bool bSpawnProtected = false;
	bool bReloading = false;
	/** Server time of the sighting this was built from, seconds. */
	double SightingTimeS = 0.0;
};

/** The point the bot aims at and how wide that body part looks. */
struct VERSEBOT_API FVerseBotAimPoint
{
	FVector Location = FVector::ZeroVector;
	EVerseSightSample Sample = EVerseSightSample::UpperTorso;
	/** Angular half-width of the aimed body part from the eye, degrees (fire tolerance basis). */
	double HalfWidthDeg = 0.5;
	double RangeM = 0.0;
};

/**
 * Track latency, motion read and lead (bot.md 8.1): the aim follows the sighting TrackLatencyMs old,
 * extrapolated over that latency with LeadSkill (brain.ts:206-238). A target that keeps reversing
 * (A-D strafing) is read over MotionWindowMs, so the aim goes to the middle of its wobble instead
 * of chasing it. Lead = bolt flight time x LeadSkill x (1 + N(0, LeadNoise)), drawn per engagement,
 * as is the head-or-torso choice (HeadAimChance).
 *
 * Fed only with FVerseSightPercept (B2). Deterministic (B5).
 */
class VERSEBOT_API FVerseBotTargetTracker
{
public:
	/** Sighting history kept, seconds (covers the largest latency plus motion window). */
	static constexpr double HistoryS = 1.5;
	/** A sighting older than latency + this is no longer tracked, seconds. */
	static constexpr double StaleAfterLatencyS = 8.0 / 60.0;
	/** Reversal sampling step and look-back of the strafing read (brain.ts reversals). */
	static constexpr double ReversalStepS = 0.1;
	static constexpr double ReversalLookbackS = 0.7;
	/** Bolt speed (README Projectiles), m/s; the weapon asset's value wins when given. */
	static constexpr double DefaultBoltSpeedMps = 880.0;

	void Reset(const FVerseBotTrackParams& InParams, uint64 Seed);
	void SetParams(const FVerseBotTrackParams& InParams) { Params = InParams; }
	const FVerseBotTrackParams& GetParams() const { return Params; }

	/** A new engagement: draws the aim part (head with HeadAimChance) and the lead error. */
	void BeginEngagement();

	/** Adds the sighting of this tick. */
	void Push(double TimeS, const FVerseSightPercept& Sighting);

	/** Forgets the target (sight lost long enough, death, respawn). */
	void Clear();

	bool HasHistory() const { return History.Num() > 0; }
	double GetNewestSightingTimeS() const { return History.Num() > 0 ? History.Last().TimeS : -1.0e9; }
	const FVerseSightPercept* GetNewestSighting() const { return History.Num() > 0 ? &History.Last().Sighting : nullptr; }

	/** The target as the bot perceives it now; false when nothing is old enough or it went stale. */
	bool Perceived(double NowS, FVerseBotTrackedTarget& Out) const;

	/** The aim point with lead, from the eye (world cm). */
	FVerseBotAimPoint AimPoint(const FVerseBotTrackedTarget& Target, const FVector& Eye, double BoltSpeedMps) const;

	bool AimsAtHead() const { return bAimHead; }
	double GetLeadError() const { return LeadError; }

	/** Offset of a hit-zone sample point from the pelvis for a stance and facing, cm. */
	static FVector SampleOffset(EVerseSightSample Sample, EVerseStance Stance, float FacingYawDeg);

	/** Radius of the body part around a sample point, cm (angular half-width basis). */
	static double SampleRadiusCm(EVerseSightSample Sample);

	/** How often the horizontal motion reversed in the look-back before TimeS. */
	int32 CountReversals(double TimeS) const;

private:
	struct FEntry
	{
		double TimeS = 0.0;
		FVerseSightPercept Sighting;
	};

	FVerseBotTrackParams Params;
	FVerseRng Rng;
	TArray<FEntry> History;
	bool bAimHead = false;
	double LeadError = 0.0;

	const FEntry* EntryAtOrBefore(double TimeS) const;
};

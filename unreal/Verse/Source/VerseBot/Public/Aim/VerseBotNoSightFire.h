#pragma once

#include "CoreMinimal.h"
#include "VerseRng.h"

class UVerseBotTier;

/**
 * The authority a bot shot has (bot.md 8.4, F4). Every shot is exactly one of these; WP08's
 * FVerseBotFireAudit records it. None means the shot is not allowed.
 */
enum class EVerseBotFireAuthority : uint8
{
	None,
	/** A target in sight (after reaction). */
	Visible,
	/** Within 0.35 s after losing sight, aim within 2 m of the last seen position. */
	Suppression,
	/** A fresh heard percept near a peek edge with enough belief, PrefireChance per approach. */
	Prefire,
	/** Wall-shot authority of bot.md 4.5 (decided by the brain's belief, WP08). */
	WallShot,
};

/** The no-sight fire fields of a tier. */
struct VERSEBOT_API FVerseBotNoSightParams
{
	double PrefireChance = 0.1;
	/** Belief floor for a prefire: the tier's WallbangMinBelief, never below the contract floor 0.25. */
	double PrefireMinBelief = 0.55;

	static FVerseBotNoSightParams FromTier(const UVerseBotTier& Tier);
};

/** One tick of no-sight fire inputs (everything from percepts and belief, never truth). */
struct VERSEBOT_API FVerseBotNoSightInput
{
	double NowS = 0.0;
	/** Where the bot would put the bolt, world cm. */
	FVector AimPoint = FVector::ZeroVector;

	/** Last sighting of the opponent; LastSeenS < 0 when never seen this life. */
	double LastSeenS = -1.0;
	FVector LastSeenLocation = FVector::ZeroVector;

	/** Newest heard percept of the opponent; HeardS < 0 when none. */
	double HeardS = -1.0;
	FVector HeardLocation = FVector::ZeroVector;

	/** The peek edge the bot pre-aims (EQS / match memory), and the belief mass at it (WP07). */
	bool bHasPeekEdge = false;
	FVector PeekEdgeLocation = FVector::ZeroVector;
	double BeliefMassAtEdge = 0.0;
	/** Changes with every new approach to an edge; the prefire roll is drawn once per approach. */
	uint32 ApproachId = 0;

	/** bot.md 4.5 holds for AimPoint (the brain's check; learned terms never set it). */
	bool bWallShotAuthorised = false;
};

/**
 * The three no-sight fire modes (bot.md 8.4). Classify answers which authority a shot at the
 * input's aim point would have; any shot with None is a contract violation (F4).
 */
class VERSEBOT_API FVerseBotNoSightFire
{
public:
	static constexpr double SuppressionS = 0.35;
	static constexpr double SuppressionRadiusCm = 200.0;
	static constexpr double PrefireHeardMaxAgeS = 2.0;
	static constexpr double PrefireEdgeRadiusCm = 600.0;
	/** Contract floor of the belief behind a no-sight shot (bot.md 4.5). */
	static constexpr double BeliefFloor = 0.25;

	void Reset(const FVerseBotNoSightParams& InParams, uint64 Seed);
	void SetParams(const FVerseBotNoSightParams& InParams) { Params = InParams; }

	EVerseBotFireAuthority Classify(const FVerseBotNoSightInput& In);

	bool SuppressionAllowed(const FVerseBotNoSightInput& In) const;
	/** The prefire conditions without the per-approach roll. */
	bool PrefireConditions(const FVerseBotNoSightInput& In) const;

private:
	FVerseBotNoSightParams Params;
	FVerseRng Rng;
	uint32 RolledApproach = 0;
	bool bHaveRoll = false;
	bool bRollPassed = false;
};

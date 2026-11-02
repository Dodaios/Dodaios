#pragma once

#include "Balance/VersePersonModels.h"
#include "Bot/VersePerceptTypes.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "VerseRng.h"

/** Per-controller memory of the trick overrides (one per life is fine; reset per match). */
struct VERSEHARNESS_API FVerseTrickState
{
	double NextLeanFlipS = 0.0;
	bool bLeanRight = false;
	double LastSlideS = -1.0e9;
	uint32 PrevButtons = 0;
};

/**
 * Trick overrides as a pure function of the percept frame and the brain's input frame
 * (bot.md 11.2). Reads only FVersePerceptFrame (fairness F6): never a true location.
 */
struct VERSEHARNESS_API FVerseTrickOverrides
{
	static FVerseInputFrame Apply(const FVerseTrickConfig& Config, const FVersePerceptFrame& Percepts,
		const FVerseInputFrame& Brain, FVerseTrickState& State, FVerseRng& Rng, double NowS);

	static bool AnySighting(const FVersePerceptFrame& Percepts);

	/** Distance in metres from the own eye to the nearest sighting's pelvis; huge when none. */
	static float NearestSightingM(const FVersePerceptFrame& Percepts);
};

#pragma once

#include "CoreMinimal.h"

class UVerseBotTier;
struct FVerseRng;

/** What kind of stimulus a reaction answers (bot.md 8.1 Reaction). Flags combine. */
enum class EVerseBotStimulus : uint8
{
	Sight = 0,
	/** A heard noise: x 0.9. */
	Sound = 1 << 0,
	/** Seen in the 55-80 deg band: x PeripheralReactionMul. */
	Peripheral = 1 << 1,
	/** Only 1-2 sample points visible: x PartialExposureAcquireMul. */
	PartialExposure = 1 << 2,
};
ENUM_CLASS_FLAGS(EVerseBotStimulus);

/** The reaction fields of a tier (bot.md 9.1 Perception group). */
struct VERSEBOT_API FVerseBotReactionParams
{
	double MeanMs = 320.0;
	double SdMs = 60.0;
	double PeripheralMul = 1.6;
	double PartialExposureMul = 1.5;

	static FVerseBotReactionParams FromTier(const UVerseBotTier& Tier);
};

/**
 * Stimulus to first action (bot.md 8.1, B4): max(0.6 x mean, N(mean, sd)), then the stimulus
 * multipliers, then 1 / VisibilityFactor for a dark zone (bot.md 3.1 Range).
 */
struct VERSEBOT_API FVerseBotReaction
{
	/** The floor as a share of the mean (brain.ts:144-147). */
	static constexpr double FloorOfMean = 0.6;
	static constexpr double SoundMul = 0.9;

	static double SampleMs(FVerseRng& Rng, const FVerseBotReactionParams& Params,
		EVerseBotStimulus Stimulus = EVerseBotStimulus::Sight, double VisibilityFactor = 1.0);
};

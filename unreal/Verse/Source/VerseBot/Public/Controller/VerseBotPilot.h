#pragma once

#include "Bot/VersePerceptTypes.h"
#include "CoreMinimal.h"
#include "UObject/WeakObjectPtr.h"

class AController;
class FVerseBotBrainCore;
class FVerseBotEngineQueries;
class FVerseBotMatchMemory;
class UVerseBotTier;

/**
 * The bot brain for a controller that is not an AVerseBotController: the harness person models
 * (bot.md 11.1 "the same brain with person parameters"). Owns a brain, the engine world queries
 * of its controller and a match memory, and attaches the arena's belief grid once the runtime nav
 * mesh is built, exactly as the bot does. Reads only the percept frames it is given (B2).
 */
class VERSEBOT_API FVerseBotPilot
{
public:
	explicit FVerseBotPilot(AController& InOwner);
	~FVerseBotPilot();

	/** A new match: the tier (must outlive the pilot) and seed; memory and belief start empty. */
	void Reset(const UVerseBotTier& Tier, uint64 Seed, bool bLearning);

	/** One brain step on one frame; the input a person would produce. */
	FVerseInputFrame Think(const FVersePerceptFrame& Frame);

	bool IsReady() const { return Brain.IsValid(); }
	bool HasArena() const { return bArena; }

private:
	TWeakObjectPtr<AController> Owner;
	TUniquePtr<FVerseBotBrainCore> Brain;
	TUniquePtr<FVerseBotEngineQueries> Queries;
	TUniquePtr<FVerseBotMatchMemory> Memory;
	bool bArena = false;
	uint32 LastThinkMs = 0;
};

#pragma once

#include "Belief/VerseBeliefGrid.h"
#include "Brain/VerseBotWorldQueries.h"
#include "CoreMinimal.h"

class UWorld;
class FVerseBotBrainCore;
class FVerseBotEngineQueries;
class FVerseBotGridBelief;
class IVerseBotWorldQueries;

/**
 * Static arena knowledge of the bots of one world, built once from the runtime nav mesh and the
 * static geometry on the VerseSight channel (bot.md 3.3: public map knowledge; pawns ignore the
 * channel, so nothing here reads an opponent):
 * - the belief grid source (bot.md 4.1): 1 m cells on three levels, sampled from Recast, same-level
 *   neighbours joined where a move along the nav surface arrives, and ramp cells joined across
 *   levels, so belief mass flows up and down the stairs;
 * - cover points (bot.md 5.1 Search, 6.2 cover): nav points on a 2 m lattice next to a wall, with
 *   the cover they give (low or high) and the direction it protects against; points at the end of
 *   a cover run carry an edge id (peek edges).
 *
 * The nav mesh of the hangar arena generates at runtime, so Get returns null until it is built.
 */
struct VERSEBOT_API FVerseBotArenaData
{
	FBox ArenaBox = FBox(ForceInit);
	FVerseBeliefGridSource GridSource;
	/** Cover points: lattice points with a wall within reach at crouched eye height (bHigh: also standing). */
	TArray<FVerseBotCoverPoint> Points;

	/** Points within RadiusCm of Center (3D distance, levels apart by height). */
	void PointsWithin(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out) const;

	/**
	 * The world's data, built on the first call after the nav mesh is ready; null before that.
	 * Retries are rate limited (one attempt per second of world time).
	 */
	static TSharedPtr<const FVerseBotArenaData> Get(UWorld& World);

	/**
	 * Give a brain the arena once it is ready: the grid belief (clearing through Active, the queries
	 * the brain thinks with) and the cover points on Engine. Returns the grid belief the brain now
	 * owns, or null while the nav mesh is not built yet (call again later).
	 */
	static const FVerseBotGridBelief* AttachTo(UWorld& World, FVerseBotBrainCore& Brain, FVerseBotEngineQueries& Engine,
		IVerseBotWorldQueries& Active, int32 SelfPlayerId);

	/** Belief clear: cell sight tests per 10 Hz step (~2,000 cheap static traces a second). */
	static constexpr int32 ClearTestsPerStep = 200;

	/** Drop the cached data of a world (level change, arena rebuilt). */
	static void Forget(const UWorld& World);

	/** The arena box from spawn points: their bounds grown by a margin (public arena data). */
	static FBox ArenaBoxFromSpawns(TConstArrayView<FVector> Spawns);

	/** Cell size of the sampled grid, cm, and lattice step of arena points, cm. */
	static constexpr float GridCellCm = 100.f;
	static constexpr float PointStepCm = 200.f;
};

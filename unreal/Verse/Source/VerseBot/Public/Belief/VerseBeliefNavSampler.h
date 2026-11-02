#pragma once

#include "Belief/VerseBeliefGrid.h"
#include "CoreMinimal.h"
#include "Templates/Function.h"

class INavigationDataInterface;
class UWorld;

/** How to sample the arena's navmesh into belief cells (contracts/bot.md 4.1). */
struct VERSEBOT_API FVerseBeliefNavSettings
{
	/** The arena zone, world cm (about 50 x 40 m, three levels). */
	FBox ArenaBox = FBox(ForceInit);
	float CellSizeCm = 100.f;
	/** Floor height probed for each level, world cm (Floor, Mid, Upper). */
	float LevelProbeZCm[3] = {0.f, 400.f, 800.f};
	/** Projection extent: horizontal half-size and vertical reach, cm. */
	float ProjectHalfXYCm = 35.f;
	float ProjectHalfZCm = 150.f;
	/** Two cells of one column closer than this in height are the same floor. */
	float SameFloorCm = 80.f;
	/** Authored links in cell coordinates (column + level); resolved to cells after sampling. */
	struct FLink
	{
		FIntPoint FromColumn = FIntPoint::ZeroValue;
		EVerseArenaLevel FromLevel = EVerseArenaLevel::Floor;
		FIntPoint ToColumn = FIntPoint::ZeroValue;
		EVerseArenaLevel ToLevel = EVerseArenaLevel::Floor;
		float TraversalS = 1.f;
		bool bBidirectional = true;
		EVerseBeliefLinkKind Kind = EVerseBeliefLinkKind::Stair;
		EVerseBeliefGate Gate = EVerseBeliefGate::Always;
		int32 GatePiece = INDEX_NONE;
	};
	TArray<FLink> Links;
	/** Optional per-cell arena data: VisibilityFactor and zone id at a world point. */
	TFunction<float(const FVector&)> VisibilityAt;
	TFunction<uint8(const FVector&)> ZoneAt;
};

/**
 * Builds a belief grid source from Recast nav (WP07.5): every 1 x 1 m column of the arena box is
 * projected onto the navmesh at each level's probe height; a hit within reach is a cell. Two
 * same-level neighbours are connected when a move along the nav surface from one reaches the other.
 * Uses only the engine's navigation interface (no NavigationSystem module dependency).
 */
class VERSEBOT_API FVerseBeliefNavSampler
{
public:
	/** Sample the world's main nav data. Returns false (empty source) when the world has no nav. */
	static bool Build(const UWorld& World, const FVerseBeliefNavSettings& Settings, FVerseBeliefGridSource& OutSource);

	/** Sample a given nav data interface (tests, harness). */
	static bool Build(const INavigationDataInterface& Nav, const FVerseBeliefNavSettings& Settings, FVerseBeliefGridSource& OutSource);
};

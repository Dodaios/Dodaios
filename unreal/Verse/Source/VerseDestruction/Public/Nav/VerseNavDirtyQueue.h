#pragma once

#include "CoreMinimal.h"

/**
 * Navmesh dirty-tile queue of destruction.md 6.1: every state change marks the piece's old and
 * new proxy bounds (+50 cm) dirty; the tiles they cover are released at most N at a time, so
 * at most 4 tiles rebuild at once. Tiles are 32 x 32 cells of 10 cm (320 cm). Pure logic; the
 * manager hands released tiles to the navigation system.
 */
class VERSEDESTRUCTION_API FVerseNavDirtyQueue
{
public:
	static constexpr float TileSizeCm = 320.f;

	struct FTile
	{
		FIntPoint Key = FIntPoint::ZeroValue;
		/** Z range covered by the dirty boxes that touched this tile. */
		float MinZ = 0.f;
		float MaxZ = 0.f;
		/** The piece whose change first dirtied the tile (INDEX_NONE if unknown). */
		int32 PieceIndex = INDEX_NONE;
		/** World box of the tile footprint over the Z range. */
		FBox GetBox() const;
	};

	explicit FVerseNavDirtyQueue(int32 InMaxInFlight = 4, float InMarginCm = 50.f);

	/** Marks the tiles under Box (grown by the margin) dirty. Tiles already queued merge. */
	void MarkDirty(const FBox& Box, int32 PieceIndex = INDEX_NONE);

	/**
	 * Called when the navigation system reports rebuilt tiles (or once per nav tick when it
	 * cannot report): frees the in-flight slots and releases up to MaxInFlight queued tiles.
	 */
	TArray<FTile> Release(int32 CompletedSinceLastRelease);

	/** Releases everything (full reset rebuilds all dirty tiles). */
	TArray<FTile> ReleaseAll();

	int32 NumQueued() const { return Queue.Num(); }
	int32 NumInFlight() const { return InFlight; }
	int32 GetMaxInFlight() const { return MaxInFlight; }
	int32 GetPeakInFlight() const { return PeakInFlight; }

	static FIntPoint TileOf(const FVector& Point);

private:
	TArray<FTile> Queue;
	int32 MaxInFlight = 4;
	float MarginCm = 50.f;
	int32 InFlight = 0;
	int32 PeakInFlight = 0;
};

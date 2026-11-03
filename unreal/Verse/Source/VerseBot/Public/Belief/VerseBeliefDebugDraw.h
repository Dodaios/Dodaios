#pragma once

#include "Belief/VerseBeliefGrid.h"
#include "CoreMinimal.h"

class UWorld;

/**
 * Dev-only belief heatmap (WP07.10): in-world debug boxes coloured by mass, and a top-down image
 * of one level for screenshots and test evidence. Presentation only; never read by the brain.
 * Colours follow the Verse palette: low mass dark steel, high mass amber to red (never cyan or violet).
 */
class VERSEBOT_API FVerseBeliefDebugDraw
{
public:
	/** Heat colour for a mass relative to the grid's maximum (0-1). */
	static FColor HeatColor(float Relative);

	/** Draw the grid into the world (no-op in Shipping or without debug drawing). */
	static void DrawWorld(const UWorld* World, const FVerseBeliefGrid& Grid, const FVerseBeliefDerived& Derived,
		float LifetimeS = 0.f, float MinRelative = 0.02f);

	/**
	 * Render one level top-down, PixelsPerCell per cell, row 0 at the highest Y. Cells that do not
	 * exist are black; the TopCluster disc is outlined in gold; Marks are drawn as white crosses.
	 */
	static void RenderTopDown(const FVerseBeliefGrid& Grid, const FVerseBeliefDerived& Derived, EVerseArenaLevel Level,
		int32 PixelsPerCell, TArray<FColor>& OutPixels, int32& OutWidth, int32& OutHeight,
		TConstArrayView<FVector> Marks = {});

	/** RenderTopDown and save as PNG. Returns false when the file could not be written. */
	static bool SavePng(const FString& Path, const FVerseBeliefGrid& Grid, const FVerseBeliefDerived& Derived,
		EVerseArenaLevel Level, int32 PixelsPerCell, TConstArrayView<FVector> Marks = {});
};

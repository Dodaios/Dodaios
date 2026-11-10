#pragma once

#include "CoreMinimal.h"

/**
 * Flat item silhouettes for the HUD loadout block. Each icon is a few convex polygons on a
 * small grid (muzzle to the right); the painter turns them into triangles, so they stay sharp
 * at every resolution and need no texture.
 */
namespace VerseHudIcons
{
	/** Convex polygons of an item's icon, in grid units; empty for an unknown item. */
	const TArray<TArray<FVector2D>>& Shape(FName ItemId);

	/** Bounds of a shape (min, max). */
	FBox2D Bounds(const TArray<TArray<FVector2D>>& Shape);

	/**
	 * Fits the icon into Box (keeps the aspect, centred vertically; Align -1 left, 0 centre,
	 * 1 right) and calls Emit for every triangle. Returns false for an unknown item.
	 */
	bool Triangulate(FName ItemId, const FBox2D& Box, int32 Align, TFunctionRef<void(const FVector2D&, const FVector2D&, const FVector2D&)> Emit);
}

#pragma once

#include "Core/VerseUiPorts.h"
#include "CoreMinimal.h"

/**
 * Crosshair placement (WP18.2, A18.1). The crosshair is drawn where the predicted bolt
 * direction meets the screen, through the same projection the engine renders with
 * (ULocalPlayer, aspect ratio keeps the horizontal FOV), so recoil, sway and lean move it
 * exactly with the bolt. The spread circle radius is the spread half-angle on that projection.
 */
struct VERSEUI_API FVerseCrosshair
{
	/** The renderer's view-projection for View on a Viewport of that size (no translation). */
	static FMatrix ViewProjection(const FVerseHudView& View, const FVector2D& Viewport);

	/** Screen pixel of a world direction from the eye. False when it points behind the camera. */
	static bool ProjectDirection(const FVerseHudView& View, const FVector2D& Viewport, const FVector& Direction, FVector2D& OutPixel);

	/** Radius in pixels of a cone of HalfAngleDeg around the view axis. */
	static float SpreadRadiusPx(const FVerseHudView& View, const FVector2D& Viewport, float HalfAngleDeg);

	/** The pixel (integer cell) a sub-pixel position falls in. */
	static FIntPoint PixelCell(const FVector2D& Position) { return FIntPoint(FMath::FloorToInt(Position.X), FMath::FloorToInt(Position.Y)); }
};

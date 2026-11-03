#pragma once

#include "CoreMinimal.h"
#include "Layout/Margin.h"

/** Screen anchors for HUD blocks; offsets are in 1080p reference pixels. */
enum class EVerseUiAnchor : uint8
{
	TopLeft,
	Top,
	TopRight,
	Left,
	Centre,
	Right,
	BottomLeft,
	Bottom,
	BottomRight,
};

/**
 * Safe area and scale of one viewport (WP18.1). The HUD is authored at 1920 x 1080 and scales
 * uniformly by the smaller axis ratio, so 1440p is x1.333 and 4K is x2. Blocks anchor to the
 * safe rectangle (title-safe fraction or the platform padding, whichever is larger); the
 * crosshair alone uses the whole viewport, because it sits on the projected bolt direction.
 */
struct VERSEUI_API FVerseUiLayout
{
	static constexpr float ReferenceWidth = 1920.f;
	static constexpr float ReferenceHeight = 1080.f;

	FVector2D Viewport = FVector2D(ReferenceWidth, ReferenceHeight);
	/** Safe rectangle in viewport pixels. */
	FVector2D SafeMin = FVector2D::ZeroVector;
	FVector2D SafeMax = FVector2D(ReferenceWidth, ReferenceHeight);
	/** Geometry scale relative to 1080p. */
	float Scale = 1.f;
	/** Geometry scale times the person's text size choice. */
	float TextScale = 1.f;

	/**
	 * @param SafeFraction  Fraction of each axis kept free on every side (0.025 = action safe).
	 * @param PlatformPadding  Pixels the platform reports as unsafe (FDisplayMetrics); larger wins.
	 * @param UserTextScale  Accessibility text size, clamped to [0.8, 1.6].
	 */
	static FVerseUiLayout Compute(const FVector2D& Viewport, float SafeFraction, const FMargin& PlatformPadding, float UserTextScale);

	FVector2D SafeSize() const { return SafeMax - SafeMin; }

	/** Reference pixels to viewport pixels. */
	float Px(float ReferencePx) const { return ReferencePx * Scale; }

	/** Font size in points for a 1080p reference size, after scale and text size. */
	int32 FontSize(float ReferencePt) const;

	/**
	 * Top-left corner of a block of Size (viewport px) at Anchor, moved inward by Offset
	 * (reference px). The block always ends up fully inside the safe rectangle.
	 */
	FVector2D Place(EVerseUiAnchor Anchor, const FVector2D& Size, const FVector2D& Offset) const;
};

#pragma once

#include "CoreMinimal.h"

class UTexture2D;

/**
 * HUD item icons: white silhouettes with soft panel shading, rendered from the weapon meshes
 * by scripts/verse/hud_icons.py into Data/ui/icons/<item>_<height>.png. The HUD tints them.
 */
namespace VerseHudIcons
{
	/** True when the item has an icon. */
	bool Has(FName ItemId);

	/** Width over height of the item's icon; 0 when it has none. */
	float Aspect(FName ItemId);

	/**
	 * The icon texture for a draw this many pixels tall: the smallest stored height at least as
	 * tall, else the largest. Loaded once and kept; nullptr when the file is missing.
	 */
	UTexture2D* Texture(FName ItemId, float DrawHeightPx);

	/** Icon folder (Data/ui/icons of the project). */
	FString Directory();
}

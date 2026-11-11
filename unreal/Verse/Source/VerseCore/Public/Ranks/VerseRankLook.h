#pragma once

#include "CoreMinimal.h"

class UMeshComponent;

/**
 * The rank ladder and how a uniformed body wears it, as the three.js Verse does: the ladder of
 * `progression/ranks.ts` (level -> rank, tier, plate) and `actors/look.ts` `applyLook` (the tier's
 * uniform colours by material slot name, the agent's accent, the lit tiles of the chest rank
 * plate). The tier colours are `art/verse/characters/build.py` `TIERS`; `tests/verse` keeps both
 * tables in step with their sources.
 */
namespace VerseRanks
{
	struct FRank
	{
		const TCHAR* Id;
		int32 Level;
		const TCHAR* Tier;
		/** Lit plate slots, `top|bottom`, three digits each. */
		const TCHAR* Plate;
	};

	/** A tier's colours (sRGB hex as in build.py, so the table reads like its source). */
	struct FTier
	{
		const TCHAR* Id;
		const TCHAR* Uniform;
		const TCHAR* Trousers;
		const TCHAR* Trim;
		const TCHAR* Cap;
		/** Tile colour on the rank plate (`TIER_STYLE.tile`). */
		const TCHAR* Tile;
	};

	VERSECORE_API TConstArrayView<FRank> Ladder();
	VERSECORE_API TConstArrayView<FTier> Tiers();
	/** `rankForLevel`: the highest rank at or below `Level` (the first rank below level 1). */
	VERSECORE_API const FRank& ForLevel(int32 Level);
	VERSECORE_API const FTier* FindTier(FName Tier);
	/** Plate slots 0-5 (top row left to right, then the bottom row) that are lit (`litSlots`). */
	VERSECORE_API TArray<int32> LitSlots(const FString& Plate);
	/** Colour of an empty plate socket (`tileUnlit`). */
	VERSECORE_API FLinearColor TileUnlit();
	VERSECORE_API FLinearColor Linear(const TCHAR* Hex);

	/** Emission of a lit tile: `emissiveIntensity` 0.35 of the tile colour, in the characters'
	 *  three.js-to-nits scale (`fps/records.py` `EMIT_TO_NITS`). */
	inline constexpr float LitTileEmission = 0.35f;
	inline constexpr float EmitToNits = 12.f;

	/**
	 * `applyLook` on a body: `M_Uniform`, `M_Trousers`, `M_Trim`, `M_Cap` take the tier's colours,
	 * `M_Accent` the accent (when given), `M_RankTile_1..6` the tier's tile colour and a glow where
	 * the plate is lit, the empty socket colour elsewhere. Works on dynamic instances of the
	 * body's own materials (`BaseTint`, `EmissiveColor` of M_Verse_Character). Returns how many
	 * slots it set; 0 for a body without those slots or an unknown tier.
	 */
	VERSECORE_API int32 ApplyLook(UMeshComponent* Body, FName Tier, const FString& Plate, const FLinearColor* Accent = nullptr);
	/** `lookForLevel` + `applyLook`. */
	VERSECORE_API int32 ApplyLevel(UMeshComponent* Body, int32 Level, const FLinearColor* Accent = nullptr);
}

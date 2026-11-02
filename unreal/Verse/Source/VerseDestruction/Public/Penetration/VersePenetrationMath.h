#pragma once

#include "CoreMinimal.h"
#include "Destruction/VersePenetrationTable.h"

// The pure arithmetic of destruction.md 2 and combat-state.md 6: one piece, one bolt.
// TraceBolt, the golden table test and the bot's wall-shot check all use these functions,
// so the formula exists exactly once.

/** What one piece does to a bolt that entered it. */
struct FVersePenetrationStep
{
	/** row.cost x clamp(traced / ref, 0.5, 3.0) */
	float Cost = 0.f;
	bool bPassed = false;
	/** Power after the piece; 0 when the piece stopped the bolt. */
	float PowerLeft = 0.f;
	/** Damage after the piece; 0 when the piece stopped the bolt. */
	float DamageLeft = 0.f;
};

namespace VersePenetration
{
	/** PieceIndex of a FVersePenetrationHit on non-destructible world geometry (no piece, no damage call). */
	inline constexpr uint16 NoPiece = 0xFFFF;

	/** The weapon's MaxPenetrations clamped to the contract limit of 3 (never raised). */
	VERSEDESTRUCTION_API int32 EffectiveMaxPieces(int32 WeaponMaxPieces);

	/**
	 * One piece. bLimitReached: the bolt already passed its MaxPieces, so this piece stops it
	 * whatever the power (destruction.md 2: the 4th piece stops it).
	 */
	VERSEDESTRUCTION_API FVersePenetrationStep EvaluatePiece(const FVersePenetrationRow& Row, float TracedThicknessCm,
		float Power, float Damage, bool bLimitReached);

	/** True for the materials whose pieces keep bolt holes (destruction.md 5). */
	VERSEDESTRUCTION_API bool KeepsBoltHoles(EVersePenetrationMaterial Material);

	/** True for wall materials: hole 25 turns the piece Holed (destruction.md 5). */
	VERSEDESTRUCTION_API bool IsWallMaterial(EVersePenetrationMaterial Material);

	/** The frozen material ids of destruction.md 2 in wire order (`sheet_metal`, ...). */
	VERSEDESTRUCTION_API TConstArrayView<const TCHAR*> FrozenMaterialIds();
}

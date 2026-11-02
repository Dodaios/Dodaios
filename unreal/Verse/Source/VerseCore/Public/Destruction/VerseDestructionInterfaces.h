#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "UObject/Interface.h"

#include "VerseDestructionInterfaces.generated.h"

// The destruction query and damage interfaces (destruction.md frozen interface). Declared in
// Core so Combat, Bot and the harness code against them before VerseDestruction lands; the
// null stubs are in Stubs/VerseNullStubs.h. VerseDestruction implements them for real.
// Native only: Blueprints never implement them.

UINTERFACE(MinimalAPI, meta = (CannotImplementInterfaceInBlueprint))
class UVersePenetrationQuery : public UInterface
{
	GENERATED_BODY()
};

class VERSECORE_API IVersePenetrationQuery
{
	GENERATED_BODY()

public:
	/**
	 * Every piece the bolt segment enters, in order, against the current-state proxies.
	 * Origin and Dir in world cm; MaxDist in cm; Power and Damage at the segment start;
	 * MaxPieces <= 3. Holes are honoured (destruction.md 5).
	 */
	virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist,
		float Power, float Damage, uint8 RadiusMm, int32 MaxPieces) const = 0;

	/** Sight from Eye to Target on VerseSight: holes honoured, intact glass and grating see-through. */
	virtual bool TestSight(const FVector& Eye, const FVector& Target) const = 0;
};

/**
 * A plain native interface, not a UINTERFACE: its reflected twin UVersePieceDamage would share
 * the engine name of the frozen struct FVersePieceDamage. Implementers hand it out directly.
 */
class VERSECORE_API IVersePieceDamage
{
public:
	virtual ~IVersePieceDamage() = default;

	/** Server only (DR1). */
	virtual void ApplyPieceDamage(const FVersePieceDamage& Damage) = 0;
};

UINTERFACE(MinimalAPI, meta = (CannotImplementInterfaceInBlueprint))
class UVersePieceQuery : public UInterface
{
	GENERATED_BODY()
};

/** Piece truth. The bot uses it only behind its perception gate (DR6, bot.md F1). */
class VERSECORE_API IVersePieceQuery
{
	GENERATED_BODY()

public:
	virtual EVersePieceState GetPieceState(uint16 PieceIndex) const = 0;
	virtual EVersePenetrationMaterial GetPieceMaterial(uint16 PieceIndex) const = 0;
	/** World bounds of the current proxy; an invalid box for an unknown piece. */
	virtual FBox GetPieceBounds(uint16 PieceIndex) const = 0;
	virtual TArray<uint16> GetPiecesInBox(const FBox& WorldBox) const = 0;
};

#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Movement/VerseMovementQuery.h"
#include "UObject/Object.h"

#include "VerseNullStubs.generated.h"

// Null implementations of every contract interface (orchestration.md 0.3, work-packages.md 0.3),
// so every package builds and tests from day one. They describe an empty world: no pieces,
// nothing blocks sight, a pawn that stands still. Stateless; GetDefault<UVerseNull...>() is a
// valid instance. A package that needs richer behaviour writes its own FFake<Interface> under
// Private/Tests/<Area>/Fakes/. Verse.Contract.Stubs.* pins these answers.

/** No pieces: TraceBolt enters nothing, TestSight is always clear. */
UCLASS()
class VERSECORE_API UVerseNullPenetrationQuery : public UObject, public IVersePenetrationQuery
{
	GENERATED_BODY()

public:
	virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist,
		float Power, float Damage, uint8 RadiusMm, int32 MaxPieces) const override;
	virtual bool TestSight(const FVector& Eye, const FVector& Target) const override;
};

/** Ignores every damage request. */
UCLASS()
class VERSECORE_API UVerseNullPieceDamage : public UObject, public IVersePieceDamage
{
	GENERATED_BODY()

public:
	virtual void ApplyPieceDamage(const FVersePieceDamage& Damage) override;
};

/** No pieces: every index answers Intact, concrete, an invalid box; no piece is in any box. */
UCLASS()
class VERSECORE_API UVerseNullPieceQuery : public UObject, public IVersePieceQuery
{
	GENERATED_BODY()

public:
	virtual EVersePieceState GetPieceState(uint16 PieceIndex) const override;
	virtual EVersePenetrationMaterial GetPieceMaterial(uint16 PieceIndex) const override;
	virtual FBox GetPieceBounds(uint16 PieceIndex) const override;
	virtual TArray<uint16> GetPiecesInBox(const FBox& WorldBox) const override;
};

/** Standing, grounded, not sprinting, not mantling, no lean. */
UCLASS()
class VERSECORE_API UVerseNullMovementQuery : public UObject, public IVerseMovementQuery
{
	GENERATED_BODY()

public:
	virtual EVerseStance GetStance() const override;
	virtual bool IsSprinting() const override;
	virtual bool IsAirborne() const override;
	virtual bool IsMantling() const override;
	virtual int8 GetLeanQuantized() const override;
};

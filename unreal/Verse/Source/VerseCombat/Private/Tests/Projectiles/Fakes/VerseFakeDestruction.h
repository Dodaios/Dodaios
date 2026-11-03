#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Destruction/VerseDestructionTypes.h"

#if WITH_DEV_AUTOMATION_TESTS

/** One fake piece: an axis-aligned slab of one penetration material. */
struct FFakeVersePiece
{
	uint16 PieceIndex = 0;
	EVersePenetrationMaterial Material = EVersePenetrationMaterial::ContainerWall;
	FBox Bounds = FBox(ForceInit);
};

/**
 * WP03 fake (work-packages.md 0.3): IVersePenetrationQuery over a list of slabs. TraceBolt returns
 * every slab the segment enters, in order, with entry, exit and traced thickness; it never decides
 * a pass itself (the combat loop does). TestSight is always clear. A plain C++ object, compiled
 * only with the automation tests.
 */
class FFakeVersePenetrationQuery : public IVersePenetrationQuery
{
public:
	TArray<FFakeVersePiece> Pieces;
	mutable int32 Calls = 0;

	virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float Power, float Damage,
		uint8 RadiusMm, int32 MaxPieces) const override
	{
		++Calls;
		TArray<TPair<double, FVersePenetrationHit>> Found;
		const FVector End = Origin + Dir * MaxDist;
		for (const FFakeVersePiece& P : Pieces)
		{
			FVector HitLoc, HitNormal;
			float HitTime = 0.f;
			if (!FMath::LineExtentBoxIntersection(P.Bounds, Origin, End, FVector::ZeroVector, HitLoc, HitNormal, HitTime))
			{
				continue;
			}
			// Exit: the same test from the far side.
			FVector ExitLoc, ExitNormal;
			float ExitTime = 0.f;
			const bool bExit = FMath::LineExtentBoxIntersection(P.Bounds, End, Origin, FVector::ZeroVector, ExitLoc, ExitNormal, ExitTime);
			FVersePenetrationHit H;
			H.PieceIndex = P.PieceIndex;
			H.MaterialWireId = uint8(P.Material);
			H.Entry = HitLoc;
			H.Exit = bExit ? ExitLoc : End;
			H.TracedThicknessCm = float(FVector::Dist(H.Entry, H.Exit));
			Found.Add({double(HitTime), H});
		}
		Found.Sort([](const TPair<double, FVersePenetrationHit>& A, const TPair<double, FVersePenetrationHit>& B) { return A.Key < B.Key; });
		TArray<FVersePenetrationHit> Out;
		for (const TPair<double, FVersePenetrationHit>& F : Found)
		{
			if (Out.Num() >= MaxPieces)
			{
				break;
			}
			Out.Add(F.Value);
		}
		return Out;
	}

	virtual bool TestSight(const FVector&, const FVector&) const override
	{
		return true;
	}
};

/** Records every piece damage request (WP06 fake). */
class FFakeVersePieceDamage : public IVersePieceDamage
{
public:
	TArray<FVersePieceDamage> Calls;

	virtual void ApplyPieceDamage(const FVersePieceDamage& Damage) override
	{
		Calls.Add(Damage);
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS

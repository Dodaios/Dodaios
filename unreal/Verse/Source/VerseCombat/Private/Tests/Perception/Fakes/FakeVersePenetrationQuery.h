#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"

namespace VerseCombatPerceptionTests
{
	/** An occluder: an opaque box, optionally with see-through holes (boxes through its thickness). */
	struct FFakeOccluder
	{
		FBox Box = FBox(ForceInit);
		TArray<FBox> Holes;
	};

	/**
	 * Fake of WP03's IVersePenetrationQuery (work-packages 0.3): sight is blocked by opaque boxes
	 * unless the segment enters the box through one of its holes. Implements the contract exactly.
	 */
	class FFakeVersePenetrationQuery : public IVersePenetrationQuery
	{
	public:
		TArray<FFakeOccluder> Occluders;
		mutable int32 SightCalls = 0;

		FFakeOccluder& AddWall(const FVector& Min, const FVector& Max)
		{
			FFakeOccluder& Occluder = Occluders.AddDefaulted_GetRef();
			Occluder.Box = FBox(Min, Max);
			return Occluder;
		}

		virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float Power,
			float Damage, uint8 RadiusMm, int32 MaxPieces) const override
		{
			return {};
		}

		virtual bool TestSight(const FVector& Eye, const FVector& Target) const override
		{
			++SightCalls;
			for (const FFakeOccluder& Occluder : Occluders)
			{
				FVector HitLocation;
				FVector HitNormal;
				float HitTime = 0.f;
				if (!FMath::LineExtentBoxIntersection(Occluder.Box, Eye, Target, FVector::ZeroVector, HitLocation, HitNormal, HitTime))
				{
					continue;
				}
				bool bThroughHole = false;
				for (const FBox& Hole : Occluder.Holes)
				{
					if (Hole.ExpandBy(0.1).IsInside(HitLocation))
					{
						bThroughHole = true;
						break;
					}
				}
				if (!bThroughHole)
				{
					return false;
				}
			}
			return true;
		}
	};
}

#endif // WITH_DEV_AUTOMATION_TESTS

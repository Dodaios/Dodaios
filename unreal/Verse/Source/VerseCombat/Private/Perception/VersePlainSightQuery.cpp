#include "Perception/VersePlainSightQuery.h"

#include "CollisionQueryParams.h"
#include "Engine/World.h"

TArray<FVersePenetrationHit> UVersePlainSightQuery::TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist,
	float Power, float Damage, uint8 RadiusMm, int32 MaxPieces) const
{
	return {};
}

bool UVersePlainSightQuery::TestSight(const FVector& Eye, const FVector& Target) const
{
	const UWorld* World = GetWorld();
	if (!World)
	{
		return true;
	}
	static const FName TraceTag(TEXT("VerseSight"));
	FCollisionQueryParams Params(TraceTag, false);
	return !World->LineTraceTestByChannel(Eye, Target, SightChannel, Params);
}

#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "UObject/Object.h"
#include "VerseCollision.h"

#include "VersePlainSightQuery.generated.h"

/**
 * Stand-in for WP03's penetration query until it lands (work-packages WP07 "Depends on"): sight
 * is a plain line trace on the VerseSight channel, where pawns, glass and grating do not block.
 * Holes in intact pieces are not honoured (the piece proxy blocks); TraceBolt enters nothing.
 */
UCLASS()
class UVersePlainSightQuery : public UObject, public IVersePenetrationQuery
{
	GENERATED_BODY()

public:
	static constexpr ECollisionChannel SightChannel = VerseCollision::Sight;

	virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float Power,
		float Damage, uint8 RadiusMm, int32 MaxPieces) const override;
	virtual bool TestSight(const FVector& Eye, const FVector& Target) const override;
};

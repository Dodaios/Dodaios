#include "Controller/VerseBotEngineQueries.h"

#include "CollisionQueryParams.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Controller.h"
#include "GameFramework/PlayerStart.h"

bool FVerseBotEngineQueries::TestSight(const FVector& Eye, const FVector& Target)
{
	const AController* C = Owner.Get();
	UWorld* World = C ? C->GetWorld() : nullptr;
	if (!World)
	{
		return true;
	}
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseBotSight), false);
	Params.AddIgnoredActor(C);
	if (const APawn* Own = C->GetPawn())
	{
		Params.AddIgnoredActor(Own);
	}
	FCollisionObjectQueryParams Objects;
	Objects.AddObjectTypesToQuery(ECC_WorldStatic);
	FHitResult Hit;
	return !World->LineTraceSingleByObjectType(Hit, Eye, Target, Objects, Params);
}

FVerseBotBoltTrace FVerseBotEngineQueries::TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& Weapon)
{
	// No piece data yet: static geometry stops a bolt.
	FVerseBotBoltTrace R;
	R.DamageFrac = TestSight(Origin, Target) ? 1.f : 0.f;
	R.Pieces = 0;
	return R;
}

FVerseBotPath FVerseBotEngineQueries::FindPath(const FVector& From, const FVector& To, bool bCrouch)
{
	FVerseBotPath P;
	P.bValid = true;
	P.LengthCm = float(FVector::Dist(From, To));
	P.Waypoints.Add(To);
	return P;
}

void FVerseBotEngineQueries::GetCoverPoints(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out)
{
	Out.Reset();
}

void FVerseBotEngineQueries::GetPieces(const FVector& Center, float RadiusCm, TArray<FVerseBotPieceInfo>& Out)
{
	Out.Reset();
}

void FVerseBotEngineQueries::GetSpawnPoints(TArray<FVector>& Out)
{
	Out.Reset();
	const AController* C = Owner.Get();
	UWorld* World = C ? C->GetWorld() : nullptr;
	if (!World)
	{
		return;
	}
	for (TActorIterator<APlayerStart> It(World); It; ++It)
	{
		Out.Add(It->GetActorLocation());
	}
	Out.Sort([](const FVector& A, const FVector& B) { return A.X != B.X ? A.X < B.X : A.Y < B.Y; });
}

int32 FVerseBotEngineQueries::GetZoneId(const FVector& Location)
{
	const int32 X = FMath::FloorToInt32(Location.X / 1000.f);
	const int32 Y = FMath::FloorToInt32(Location.Y / 1000.f);
	return (X & 0xff) | ((Y & 0xff) << 8);
}

FVerseBotWeaponInfo FVerseBotEngineQueries::GetOwnWeapon()
{
	return FVerseBotWeaponInfo();
}

bool FVerseBotEngineQueries::CanActivateFinisher()
{
	return false;
}

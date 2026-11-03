#include "Controller/VerseBotEngineQueries.h"

#include "CollisionQueryParams.h"
#include "Components/PrimitiveComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Controller.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerStart.h"
#include "VerseCollision.h"

bool FVerseBotEngineQueries::SegmentHitsBox(const FBox& Box, const FVector& From, const FVector& To)
{
	if (!Box.IsValid)
	{
		return false;
	}
	if (Box.IsInside(From) || Box.IsInside(To))
	{
		return true;
	}
	const FVector Delta = To - From;
	if (Delta.IsNearlyZero())
	{
		return false;
	}
	return FMath::LineBoxIntersection(Box, From, To, Delta);
}

void FVerseBotEngineQueries::CachePieceBounds(UWorld& World)
{
	if (CachedWorld.Get() == &World)
	{
		return;
	}
	CachedWorld = &World;
	PieceBounds.Reset();
	// Static arena geometry only: pawns are skipped outright (F1), pieces are found by profile.
	for (TActorIterator<AActor> It(&World); It; ++It)
	{
		if (It->IsA<APawn>())
		{
			continue;
		}
		TInlineComponentArray<UPrimitiveComponent*> Prims(*It);
		for (const UPrimitiveComponent* Prim : Prims)
		{
			const FName Profile = Prim ? Prim->GetCollisionProfileName() : NAME_None;
			if (Profile == VerseCollision::Profile::Destructible || Profile == VerseCollision::Profile::ProxyOnly)
			{
				PieceBounds.Add(Prim->Bounds.GetBox());
			}
		}
	}
}

int32 FVerseBotEngineQueries::PiecesCrossed(const FVector& From, const FVector& To)
{
	int32 N = 0;
	for (const FBox& Box : PieceBounds)
	{
		N += SegmentHitsBox(Box, From, To) ? 1 : 0;
	}
	return N;
}

bool FVerseBotEngineQueries::TraceChannel(UWorld& World, ECollisionChannel Channel, const FVector& From, const FVector& To) const
{
	const AController* C = Owner.Get();
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseBotTrace), false);
	if (C)
	{
		Params.AddIgnoredActor(C);
		if (const APawn* Own = C->GetPawn())
		{
			Params.AddIgnoredActor(Own);
		}
	}
	FHitResult Hit;
	return World.LineTraceSingleByChannel(Hit, From, To, Channel, Params);
}

bool FVerseBotEngineQueries::TestSight(const FVector& Eye, const FVector& Target)
{
	const AController* C = Owner.Get();
	UWorld* World = C ? C->GetWorld() : nullptr;
	if (!World)
	{
		return false;
	}
	CachePieceBounds(*World);
	// Believed-intact pieces are opaque (no piece belief yet): never the server's current proxy.
	if (PiecesCrossed(Eye, Target) > 0)
	{
		return false;
	}
	return !TraceChannel(*World, VerseCollision::Sight, Eye, Target);
}

FVerseBotBoltTrace FVerseBotEngineQueries::TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& Weapon)
{
	FVerseBotBoltTrace R;
	const AController* C = Owner.Get();
	UWorld* World = C ? C->GetWorld() : nullptr;
	if (!World)
	{
		return R;
	}
	CachePieceBounds(*World);
	// No penetration data until IVersePenetrationQuery is wired (WP05/WP06): a believed piece on the
	// line is counted and stops the bolt, so no wall shot is ever authorised by this stand-in.
	R.Pieces = PiecesCrossed(Origin, Target);
	if (R.Pieces > 0)
	{
		R.DamageFrac = 0.f;
		return R;
	}
	R.DamageFrac = TraceChannel(*World, VerseCollision::Bolt, Origin, Target) ? 0.f : 1.f;
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

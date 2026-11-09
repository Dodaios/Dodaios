#include "Controller/VerseBotEngineQueries.h"

#include "CollisionQueryParams.h"
#include "Components/PrimitiveComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Controller.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerStart.h"
#include "NavigationPath.h"
#include "Rules/VerseSpawnPoint.h"
#include "NavigationSystem.h"
#include "VerseCollision.h"

namespace
{
	constexpr ECollisionChannel VerseSightChannel = VerseCollision::Sight;
}

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
	GlassBounds.Reset();
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
			else if (Profile == VerseCollision::Profile::Glass)
			{
				GlassBounds.Add(Prim->Bounds.GetBox());
			}
		}
	}
}

bool FVerseBotEngineQueries::GlassCrossed(const FVector& From, const FVector& To) const
{
	for (const FBox& Box : GlassBounds)
	{
		if (SegmentHitsBox(Box, From, To))
		{
			return true;
		}
	}
	return false;
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

bool FVerseBotEngineQueries::TraceSight(UWorld& World, const FVector& From, const FVector& To) const
{
	// VerseSight only: pawns (own and opponent) ignore the channel, so no capsule is ever read.
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseBotSight), false);
	FHitResult Hit;
	return World.LineTraceSingleByChannel(Hit, From, To, VerseSightChannel, Params);
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
	return !TraceSight(*World, Eye, Target);
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
	if (R.Pieces > 0 || GlassCrossed(Origin, Target))
	{
		R.DamageFrac = 0.f;
		return R;
	}
	// Glass is handled above (it stops bolts, sight passes it); the rest blocks both alike.
	R.DamageFrac = TraceSight(*World, Origin, Target) ? 0.f : 1.f;
	return R;
}

FVerseBotPath FVerseBotEngineQueries::FindPath(const FVector& From, const FVector& To, bool bCrouch)
{
	FVerseBotPath P;
	// The nav mesh when the arena has one (integration: the runtime arena builds it), else a straight line.
	// The own controller is the path context: as a nav agent it answers with its pawn's agent
	// properties, so the query never reads a pawn handle (bot isolation, bot.md 10).
	AController* C = Owner.Get();
	UWorld* World = C ? C->GetWorld() : nullptr;
	if (UNavigationSystemV1* Nav = World ? FNavigationSystem::GetCurrent<UNavigationSystemV1>(World) : nullptr)
	{
		const UNavigationPath* Path = Nav->FindPathToLocationSynchronously(World, From, To, C);
		// A partial path still leads to the reachable point nearest the goal (never into a wall).
		if (Path && Path->IsValid() && Path->PathPoints.Num() > 1)
		{
			P.bValid = true;
			P.LengthCm = float(Path->GetPathLength());
			for (int32 I = 1; I < Path->PathPoints.Num(); ++I)
			{
				P.Waypoints.Add(Path->PathPoints[I]);
			}
			return P;
		}
	}
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
	// Arena spawn points when the world has them; day starts outside the arena are no spawn prior.
	for (TActorIterator<AVerseSpawnPoint> It(World); It; ++It)
	{
		Out.Add(It->GetActorLocation());
	}
	if (Out.Num() == 0)
	{
		for (TActorIterator<APlayerStart> It(World); It; ++It)
		{
			Out.Add(It->GetActorLocation());
		}
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

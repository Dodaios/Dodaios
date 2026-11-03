#include "Penetration/VersePenetrationSubsystem.h"

#include "Components/PrimitiveComponent.h"
#include "Destruction/VersePenetrationTable.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Holes/VerseBoltHoleComponent.h"
#include "Misc/Paths.h"
#include "Penetration/VersePenetrationMath.h"
#include "Penetration/VersePenetrationPhysicalMaterial.h"
#include "Penetration/VersePenetrationTableImport.h"
#include "PhysicalMaterials/PhysicalMaterial.h"
#include "VerseCollision.h"
#include "VerseLog.h"

namespace
{
	/** Probe offset in front of a later shape entry: off the surface, well below any modelled gap. */
	constexpr double ProbeBackoffCm = 0.05;
	/** Entries closer than this to a run's start belong to that run. */
	constexpr double SameEntryCm = 0.01;

	/** A reverse trace from Probe back to RunStart that meets a surface of Component: Probe was in air, OutExit is the run's exit. */
	bool ReverseExit(const UPrimitiveComponent& Component, const FVector& Probe, const FVector& RunStart, FVector& OutExit)
	{
		FHitResult Hit;
		FCollisionQueryParams Params(SCENE_QUERY_STAT(VersePenetrationExit), false);
		if (const_cast<UPrimitiveComponent&>(Component).LineTraceComponent(Hit, Probe, RunStart, Params) && !Hit.bStartPenetrating
			&& Hit.Distance > UE_KINDA_SMALL_NUMBER)
		{
			OutExit = Hit.ImpactPoint;
			return true;
		}
		return false;
	}
}

void UVersePenetrationSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Table = VersePenetrationImport::LoadRuntimeTable(this);
}

void UVersePenetrationSubsystem::Deinitialize()
{
	Proxies.Reset();
	PieceFrames.Reset();
	PieceQuery = nullptr;
	HoleSource.Reset();
	Super::Deinitialize();
}

void UVersePenetrationSubsystem::SetTable(UVersePenetrationTable* InTable)
{
	if (InTable)
	{
		Table = InTable;
	}
}

void UVersePenetrationSubsystem::SetPieceQuery(const IVersePieceQuery* InPieceQuery)
{
	PieceQuery = InPieceQuery;
}

void UVersePenetrationSubsystem::SetHoleSource(UVerseBoltHoleComponent* InHoles)
{
	HoleSource = InHoles;
}

void UVersePenetrationSubsystem::RegisterPieceProxy(UPrimitiveComponent* Proxy, uint16 PieceIndex, EVersePenetrationMaterial Material,
	USceneComponent* Frame)
{
	if (!Proxy)
	{
		return;
	}
	USceneComponent* PieceFrame = Frame;
	if (!PieceFrame)
	{
		const AActor* Owner = Proxy->GetOwner();
		PieceFrame = Owner && Owner->GetRootComponent() ? Owner->GetRootComponent() : Proxy;
	}
	FVersePieceProxyInfo Info;
	Info.PieceIndex = PieceIndex;
	Info.Material = Material;
	Info.Frame = PieceFrame;
	Proxies.Add(TObjectKey<UPrimitiveComponent>(Proxy), Info);
	PieceFrames.Add(PieceIndex, PieceFrame);
}

void UVersePenetrationSubsystem::UnregisterPieceProxy(UPrimitiveComponent* Proxy)
{
	Proxies.Remove(TObjectKey<UPrimitiveComponent>(Proxy));
}

const FVersePieceProxyInfo* UVersePenetrationSubsystem::FindPieceProxy(const UPrimitiveComponent* Proxy) const
{
	return Proxy ? Proxies.Find(TObjectKey<UPrimitiveComponent>(Proxy)) : nullptr;
}

bool UVersePenetrationSubsystem::GetPieceFrame(uint16 PieceIndex, FTransform& OutPieceToWorld) const
{
	const TWeakObjectPtr<USceneComponent>* Frame = PieceFrames.Find(PieceIndex);
	if (!Frame || !Frame->IsValid())
	{
		return false;
	}
	OutPieceToWorld = (*Frame)->GetComponentTransform();
	return true;
}

EVersePieceState UVersePenetrationSubsystem::PieceState(uint16 PieceIndex) const
{
	return PieceQuery ? PieceQuery->GetPieceState(PieceIndex) : EVersePieceState::Intact;
}

bool UVersePenetrationSubsystem::FindExit(const UPrimitiveComponent& Component, const FVector& Entry, const FVector& Dir, FVector& OutExit)
{
	FVersePenetrationRuns Runs;
	const bool bFound = FindSolidRuns(Component, Entry, Dir, {}, Runs);
	OutExit = Runs.Last().Exit;
	return bFound;
}

bool UVersePenetrationSubsystem::FindSolidRuns(const UPrimitiveComponent& Component, const FVector& Entry, const FVector& Dir,
	TConstArrayView<FVector> LaterEntries, FVersePenetrationRuns& OutRuns)
{
	OutRuns.Reset();
	FVector RunStart = Entry;
	for (const FVector& Next : LaterEntries)
	{
		// The entry of another shape of the same component: if the point just in front of it is
		// in air, the run that started at RunStart ended at the surface a reverse trace meets first.
		if (FVector::DotProduct(Next - RunStart, Dir) <= ProbeBackoffCm + SameEntryCm)
		{
			continue;
		}
		FVector Exit;
		if (ReverseExit(Component, Next - Dir * ProbeBackoffCm, RunStart, Exit))
		{
			OutRuns.Add({RunStart, Exit});
			RunStart = Next;
		}
	}
	const double Reach = 2.0 * Component.Bounds.SphereRadius + 1.0;
	FVector Exit;
	const bool bFound = ReverseExit(Component, RunStart + Dir * Reach, RunStart, Exit);
	OutRuns.Add({RunStart, bFound ? Exit : RunStart});
	return bFound;
}

void UVersePenetrationSubsystem::CollectCrossings(const FVector& Start, const FVector& End, ECollisionChannel Channel, const FName StatName,
	FVersePenetrationCrossings& OutCrossings) const
{
	OutCrossings.Reset();
	const UWorld* World = GetWorld();
	const FVector Direction = (End - Start).GetSafeNormal();
	if (!World || Direction.IsNearlyZero())
	{
		return;
	}
	// One query for the whole segment: every blocking response is read as an overlap, so the
	// multi trace lists each shape the channel would hit (Chaos reports one hit per shape).
	// Whatever ignores the channel (pawn capsules, debris) still ignores it.
	FCollisionQueryParams Params(StatName, false);
	Params.bReturnPhysicalMaterial = true;
	FCollisionResponseParams Responses;
	Responses.CollisionResponse.SetAllChannels(ECR_Overlap);
	TArray<FHitResult> Shapes;
	World->LineTraceMultiByChannel(Shapes, Start, End, Channel, Params, Responses);
	Shapes.StableSort([](const FHitResult& A, const FHitResult& B) { return A.Distance < B.Distance; });

	// One crossing per component, in the order of its first entry. The later shape entries of the
	// same component split it into solid runs.
	TArray<TArray<FVector, TInlineAllocator<4>>, TInlineAllocator<8>> LaterEntries;
	for (const FHitResult& Hit : Shapes)
	{
		const UPrimitiveComponent* Component = Hit.GetComponent();
		if (!Component)
		{
			continue;
		}
		const FVector Entry = Hit.bStartPenetrating ? Start : FVector(Hit.ImpactPoint);
		const int32 Existing =
			OutCrossings.IndexOfByPredicate([Component](const FVersePenetrationCrossing& Crossing) { return Crossing.Component == Component; });
		if (Existing != INDEX_NONE)
		{
			LaterEntries[Existing].Add(Entry);
			continue;
		}
		if (OutCrossings.Num() >= MaxSurfacesPerQuery)
		{
			OutCrossings.Last().bTruncated = true;
			break;
		}
		FVersePenetrationCrossing& Crossing = OutCrossings.AddDefaulted_GetRef();
		Crossing.Component = Component;
		Crossing.BoneName = Hit.BoneName;
		Crossing.PhysMaterial = Hit.PhysMaterial;
		Crossing.Entry = Entry;
		LaterEntries.AddDefaulted();
	}
	for (int32 Index = 0; Index < OutCrossings.Num(); ++Index)
	{
		FVersePenetrationCrossing& Crossing = OutCrossings[Index];
		FindSolidRuns(*Crossing.Component, Crossing.Entry, Direction, LaterEntries[Index], Crossing.Runs);
		Crossing.Exit = Crossing.Runs.Last().Exit;
		Crossing.SolidCm = 0.0;
		for (const FVersePenetrationRun& Run : Crossing.Runs)
		{
			Crossing.SolidCm += FVector::Dist(Run.Entry, Run.Exit);
		}
	}
}

bool UVersePenetrationSubsystem::PassesHoles(const FVersePieceProxyInfo& Info, const FVector& EntryWorld, const FVector& ExitWorld) const
{
	const UVerseBoltHoleComponent* Holes = HoleSource.Get();
	const USceneComponent* Frame = Info.Frame.Get();
	if (!Holes || !Frame)
	{
		return false;
	}
	if (Holes->NumOnPiece(Info.PieceIndex) == 0)
	{
		return false;
	}
	const FTransform& PieceToWorld = Frame->GetComponentTransform();
	return Holes->RayPassesPieceHoles(Info.PieceIndex, PieceToWorld.InverseTransformPosition(EntryWorld),
		PieceToWorld.InverseTransformPosition(ExitWorld));
}

bool UVersePenetrationSubsystem::PassesHoles(const FVersePieceProxyInfo& Info, const FVersePenetrationCrossing& Crossing) const
{
	// Every solid run of the proxy must lie inside a hole; one solid run without a hole blocks.
	for (const FVersePenetrationRun& Run : Crossing.Runs)
	{
		if (!PassesHoles(Info, Run.Entry, Run.Exit))
		{
			return false;
		}
	}
	return !Crossing.Runs.IsEmpty();
}

TArray<FVersePenetrationHit> UVersePenetrationSubsystem::TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float Power,
	float Damage, uint8 RadiusMm, int32 MaxPieces) const
{
	TArray<FVersePenetrationHit> Result;
	const FVector Direction = Dir.GetSafeNormal();
	if (!GetWorld() || !Table || Direction.IsNearlyZero() || MaxDist <= 0.f)
	{
		return Result;
	}
	const int32 Limit = VersePenetration::EffectiveMaxPieces(MaxPieces);
	FVersePenetrationCrossings Crossings;
	CollectCrossings(Origin, Origin + Direction * MaxDist, VerseCollision::Bolt, SCENE_QUERY_STAT_NAME_ONLY(VerseTraceBolt), Crossings);

	float PowerLeft = Power;
	float DamageLeft = Damage;
	int32 Passes = 0;
	for (const FVersePenetrationCrossing& Crossing : Crossings)
	{
		const UPrimitiveComponent* Component = Crossing.Component;
		const FVersePieceProxyInfo* Info = FindPieceProxy(Component);
		if (Info && PassesHoles(*Info, Crossing))
		{
			// Flown through an existing hole: no cost, no damage, not a piece of this bolt.
			continue;
		}
		// World geometry: gameplay collision is simple collision (art-pipeline.md 5), so the body's
		// simple physical material is the one that applies; the hit's own material is the fallback.
		const UPhysicalMaterial* PhysMat = nullptr;
		if (!Info)
		{
			const FBodyInstance* Body = Component->GetBodyInstance(Crossing.BoneName);
			PhysMat = Body ? Body->GetSimplePhysicalMaterial() : nullptr;
			if (!PhysMat || VersePenetration::ResolveWorldMaterial(PhysMat) == EVersePenetrationMaterial::Concrete)
			{
				PhysMat = Crossing.PhysMaterial.IsValid() ? Crossing.PhysMaterial.Get() : PhysMat;
			}
		}
		const EVersePenetrationMaterial Material = Info ? Info->Material : VersePenetration::ResolveWorldMaterial(PhysMat);
		const FVersePenetrationRow* Row = Table->FindRow(uint8(Material));
		if (!Row)
		{
			Row = Table->FindRow(uint8(EVersePenetrationMaterial::Concrete));
		}

		// One entry per piece: a proxy of several convex shapes, or a concave Holed proxy, is
		// charged once for the solid it holds along the ray; the air between its shapes is free.
		FVersePenetrationHit& Out = Result.AddDefaulted_GetRef();
		Out.PieceIndex = Info ? Info->PieceIndex : VersePenetration::NoPiece;
		Out.MaterialWireId = uint8(Material);
		Out.Entry = Crossing.Entry;
		Out.Exit = Crossing.Exit;
		Out.TracedThicknessCm = float(Crossing.SolidCm);
		if (!Row)
		{
			break;
		}
		const FVersePenetrationStep Step = VersePenetration::EvaluatePiece(*Row, Out.TracedThicknessCm, PowerLeft, DamageLeft, Passes >= Limit);
		Out.bPassed = Step.bPassed;
		Out.PowerLeft = Step.PowerLeft;
		Out.DamageLeft = Step.DamageLeft;
		if (!Step.bPassed || Crossing.bTruncated)
		{
			break;
		}
		PowerLeft = Step.PowerLeft;
		DamageLeft = Step.DamageLeft;
		++Passes;
	}
	return Result;
}

bool UVersePenetrationSubsystem::TestSight(const FVector& Eye, const FVector& Target) const
{
	if (!GetWorld() || (Target - Eye).IsNearlyZero())
	{
		return true;
	}
	FVersePenetrationCrossings Crossings;
	CollectCrossings(Eye, Target, VerseCollision::Sight, SCENE_QUERY_STAT_NAME_ONLY(VerseTestSight), Crossings);
	for (const FVersePenetrationCrossing& Crossing : Crossings)
	{
		const FVersePieceProxyInfo* Info = FindPieceProxy(Crossing.Component);
		bool bSeeThrough = false;
		if (!Info)
		{
			// World geometry blocks; an overlap on the sight channel (unregistered glazing) does not.
			bSeeThrough = Crossing.Component->GetCollisionResponseToChannel(VerseCollision::Sight) != ECR_Block;
		}
		else
		{
			const EVersePieceState State = PieceState(Info->PieceIndex);
			bSeeThrough = State == EVersePieceState::Destroyed || Info->Material == EVersePenetrationMaterial::CatwalkGrating
				|| (Info->Material == EVersePenetrationMaterial::Glass && State == EVersePieceState::Intact)
				|| PassesHoles(*Info, Crossing);
		}
		if (!bSeeThrough || Crossing.bTruncated)
		{
			return false;
		}
	}
	return true;
}

int32 UVersePenetrationSubsystem::RecordBoltHoles(TConstArrayView<FVersePenetrationHit> Hits, const FVector& Dir, uint8 RadiusMm,
	uint32 ServerTimeMs) const
{
	UVerseBoltHoleComponent* Holes = HoleSource.Get();
	if (!Holes)
	{
		return 0;
	}
	int32 Added = 0;
	for (const FVersePenetrationHit& Hit : Hits)
	{
		if (!Hit.bPassed)
		{
			// A bolt that stops in a piece leaves a dent decal, no hole (destruction.md 5).
			break;
		}
		FTransform PieceToWorld;
		if (Hit.PieceIndex == VersePenetration::NoPiece || !GetPieceFrame(Hit.PieceIndex, PieceToWorld))
		{
			continue;
		}
		const FVector Mid = PieceToWorld.InverseTransformPosition((Hit.Entry + Hit.Exit) * 0.5);
		const FVector Axis = PieceToWorld.InverseTransformVectorNoScale(Dir.GetSafeNormal());
		if (Holes->AddHole(Hit.PieceIndex, EVersePenetrationMaterial(Hit.MaterialWireId), Mid, Axis, RadiusMm, ServerTimeMs)
			== EVerseHoleAddResult::Added)
		{
			++Added;
		}
	}
	return Added;
}

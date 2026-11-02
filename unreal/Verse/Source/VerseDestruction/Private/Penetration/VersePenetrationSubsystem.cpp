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

void UVersePenetrationSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Table = NewObject<UVersePenetrationTable>(this, TEXT("DA_PenetrationTable_Runtime"), RF_Transient);
	const FString Path = VersePenetrationImport::DefaultTablePath();
	if (FPaths::FileExists(Path))
	{
		TArray<FString> Errors;
		if (!VersePenetrationImport::ImportIntoTable(*Table, Path, Errors))
		{
			UE_LOG(LogVerseDestruction, Error, TEXT("penetration table %s rejected, using the contract table: %s"), *Path,
				*FString::Join(Errors, TEXT("; ")));
		}
	}
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
	const double Reach = 2.0 * Component.Bounds.SphereRadius + 1.0;
	const FVector Far = Entry + Dir * Reach;
	FHitResult Hit;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VersePenetrationExit), false);
	if (const_cast<UPrimitiveComponent&>(Component).LineTraceComponent(Hit, Far, Entry, Params) && !Hit.bStartPenetrating)
	{
		OutExit = Hit.ImpactPoint;
		return true;
	}
	OutExit = Entry;
	return false;
}

bool UVersePenetrationSubsystem::PassesHoles(const FVersePieceProxyInfo& Info, const FVector& EntryWorld, const FVector& ExitWorld) const
{
	const UVerseBoltHoleComponent* Holes = HoleSource.Get();
	const USceneComponent* Frame = Info.Frame.Get();
	if (!Holes || !Frame)
	{
		return false;
	}
	const TConstArrayView<FVerseBoltHole> PieceHoles = Holes->GetPieceHoles(Info.PieceIndex);
	if (PieceHoles.IsEmpty())
	{
		return false;
	}
	const FTransform& PieceToWorld = Frame->GetComponentTransform();
	return FVerseBoltHole::RayPassesHoles(PieceHoles, PieceToWorld.InverseTransformPosition(EntryWorld),
		PieceToWorld.InverseTransformPosition(ExitWorld));
}

TArray<FVersePenetrationHit> UVersePenetrationSubsystem::TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float Power,
	float Damage, uint8 RadiusMm, int32 MaxPieces) const
{
	TArray<FVersePenetrationHit> Result;
	const UWorld* World = GetWorld();
	const FVector Direction = Dir.GetSafeNormal();
	if (!World || !Table || Direction.IsNearlyZero() || MaxDist <= 0.f)
	{
		return Result;
	}
	const FVector End = Origin + Direction * MaxDist;
	const int32 Limit = VersePenetration::EffectiveMaxPieces(MaxPieces);

	// One query for the whole segment: every blocking response is read as an overlap, so the
	// multi trace lists each surface the bolt channel would hit, in order. Whatever ignores
	// VerseBolt (pawn capsules, debris) still ignores it. Each surface then costs one narrow
	// component trace for its exit.
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseTraceBolt), false);
	Params.bReturnPhysicalMaterial = true;
	FCollisionResponseParams Responses;
	Responses.CollisionResponse.SetAllChannels(ECR_Overlap);
	TArray<FHitResult> Surfaces;
	World->LineTraceMultiByChannel(Surfaces, Origin, End, VerseCollision::Bolt, Params, Responses);

	float PowerLeft = Power;
	float DamageLeft = Damage;
	int32 Passes = 0;
	int32 Visited = 0;
	for (const FHitResult& Hit : Surfaces)
	{
		const UPrimitiveComponent* Component = Hit.GetComponent();
		if (!Component)
		{
			continue;
		}
		if (++Visited > MaxSurfacesPerQuery)
		{
			break;
		}
		const FVector Entry = Hit.bStartPenetrating ? Origin : FVector(Hit.ImpactPoint);
		FVector Exit;
		FindExit(*Component, Entry, Direction, Exit);

		const FVersePieceProxyInfo* Info = FindPieceProxy(Component);
		if (Info && PassesHoles(*Info, Entry, Exit))
		{
			// Flown through an existing hole: no cost, no damage, not a piece of this bolt.
			continue;
		}
		// World geometry: gameplay collision is simple collision (art-pipeline.md 5), so the body's
		// simple physical material is the one that applies; the hit's own material is the fallback.
		const UPhysicalMaterial* PhysMat = nullptr;
		if (!Info)
		{
			const FBodyInstance* Body = Component->GetBodyInstance(Hit.BoneName);
			PhysMat = Body ? Body->GetSimplePhysicalMaterial() : nullptr;
			if (!PhysMat || VersePenetration::ResolveWorldMaterial(PhysMat) == EVersePenetrationMaterial::Concrete)
			{
				PhysMat = Hit.PhysMaterial.IsValid() ? Hit.PhysMaterial.Get() : PhysMat;
			}
		}
		const EVersePenetrationMaterial Material = Info ? Info->Material : VersePenetration::ResolveWorldMaterial(PhysMat);
		const FVersePenetrationRow* Row = Table->FindRow(uint8(Material));
		if (!Row)
		{
			Row = Table->FindRow(uint8(EVersePenetrationMaterial::Concrete));
		}

		FVersePenetrationHit& Out = Result.AddDefaulted_GetRef();
		Out.PieceIndex = Info ? Info->PieceIndex : VersePenetration::NoPiece;
		Out.MaterialWireId = uint8(Material);
		Out.Entry = Entry;
		Out.Exit = Exit;
		Out.TracedThicknessCm = float(FVector::Dist(Entry, Exit));
		if (!Row)
		{
			break;
		}
		const FVersePenetrationStep Step = VersePenetration::EvaluatePiece(*Row, Out.TracedThicknessCm, PowerLeft, DamageLeft, Passes >= Limit);
		Out.bPassed = Step.bPassed;
		Out.PowerLeft = Step.PowerLeft;
		Out.DamageLeft = Step.DamageLeft;
		if (!Step.bPassed)
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
	const UWorld* World = GetWorld();
	if (!World)
	{
		return true;
	}
	const FVector Direction = (Target - Eye).GetSafeNormal();
	if (Direction.IsNearlyZero())
	{
		return true;
	}
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseTestSight), false);
	for (int32 Pass = 0; Pass < MaxSurfacesPerQuery; ++Pass)
	{
		TArray<FHitResult> Hits;
		World->LineTraceMultiByChannel(Hits, Eye, Target, VerseCollision::Sight, Params);
		if (Hits.IsEmpty())
		{
			return true;
		}
		bool bReachedBlock = false;
		for (const FHitResult& Hit : Hits)
		{
			const UPrimitiveComponent* Component = Hit.GetComponent();
			if (!Component)
			{
				continue;
			}
			const FVersePieceProxyInfo* Info = FindPieceProxy(Component);
			bool bSeeThrough = false;
			if (!Info)
			{
				// World geometry blocks; an overlap on the sight channel (unregistered glazing) does not.
				bSeeThrough = !Hit.bBlockingHit;
			}
			else
			{
				const EVersePieceState State = PieceState(Info->PieceIndex);
				if (State == EVersePieceState::Destroyed || Info->Material == EVersePenetrationMaterial::CatwalkGrating
					|| (Info->Material == EVersePenetrationMaterial::Glass && State == EVersePieceState::Intact))
				{
					bSeeThrough = true;
				}
				else
				{
					const FVector Entry = Hit.bStartPenetrating ? Eye : FVector(Hit.ImpactPoint);
					FVector Exit;
					FindExit(*Component, Entry, Direction, Exit);
					bSeeThrough = PassesHoles(*Info, Entry, Exit);
				}
			}
			if (!bSeeThrough)
			{
				return false;
			}
			Params.AddIgnoredComponent(Component);
			bReachedBlock |= Hit.bBlockingHit;
		}
		if (!bReachedBlock)
		{
			// Only see-through overlaps between eye and target.
			return true;
		}
		// A see-through blocking surface (grating, a hole) was ignored; trace on behind it.
	}
	return false;
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

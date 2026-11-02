#include "Tests/Penetration/Fakes/VerseWP03Fakes.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/BoxComponent.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Holes/VerseBoltHoleComponent.h"
#include "Misc/Paths.h"
#include "Penetration/VersePenetrationSubsystem.h"
#include "VerseCollision.h"

EVersePieceState FFakePieceQuery::GetPieceState(uint16 PieceIndex) const
{
	const EVersePieceState* Found = States.Find(PieceIndex);
	return Found ? *Found : EVersePieceState::Intact;
}

EVersePenetrationMaterial FFakePieceQuery::GetPieceMaterial(uint16 PieceIndex) const
{
	const EVersePenetrationMaterial* Found = Materials.Find(PieceIndex);
	return Found ? *Found : EVersePenetrationMaterial::Concrete;
}

FBox FFakePieceQuery::GetPieceBounds(uint16 PieceIndex) const
{
	const FBox* Found = Bounds.Find(PieceIndex);
	return Found ? *Found : FBox(ForceInit);
}

TArray<uint16> FFakePieceQuery::GetPiecesInBox(const FBox& WorldBox) const
{
	TArray<uint16> Out;
	for (const TPair<uint16, FBox>& Pair : Bounds)
	{
		if (Pair.Value.Intersect(WorldBox))
		{
			Out.Add(Pair.Key);
		}
	}
	return Out;
}

FVerseWP03World::~FVerseWP03World()
{
	if (Penetration)
	{
		Penetration->SetPieceQuery(nullptr);
	}
}

bool FVerseWP03World::Create()
{
	if (!CreateTestWorld(EWorldType::Game))
	{
		return false;
	}
	Penetration = TestWorld->GetSubsystem<UVersePenetrationSubsystem>();
	if (!Penetration)
	{
		return false;
	}
	FActorSpawnParameters Params;
	Params.ObjectFlags = RF_Transient;
	Manager = TestWorld->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
	Holes = NewObject<UVerseBoltHoleComponent>(Manager, TEXT("BoltHoles"));
	Holes->RegisterComponent();
	Penetration->SetHoleSource(Holes);
	Penetration->SetPieceQuery(&Query);
	return true;
}

void FVerseWP03World::Settle()
{
	for (int32 Frame = 0; Frame < 3; ++Frame)
	{
		TickTestWorld(1.f / 60.f);
	}
}

AActor* FVerseWP03World::SpawnBox(const FVector& Center, const FRotator& Rotation, const FVector& HalfExtent, FName Profile, UPhysicalMaterial* PhysMat)
{
	FActorSpawnParameters Params;
	Params.ObjectFlags = RF_Transient;
	AActor* Actor = TestWorld->SpawnActor<AActor>(AActor::StaticClass(), FTransform(Rotation, Center), Params);
	UBoxComponent* Box = NewObject<UBoxComponent>(Actor, TEXT("Proxy"));
	Box->SetBoxExtent(HalfExtent, false);
	Box->SetCollisionProfileName(Profile);
	if (PhysMat)
	{
		Box->BodyInstance.SetPhysMaterialOverride(PhysMat);
	}
	Actor->SetRootComponent(Box);
	Box->RegisterComponent();
	Actor->SetActorLocationAndRotation(Center, Rotation);
	return Actor;
}

AActor* FVerseWP03World::SpawnPiece(uint16 PieceIndex, EVersePenetrationMaterial Material, const FVector& Center, float ThicknessCm,
	float WidthCm, float HeightCm, const FRotator& Rotation)
{
	const FName Profile = Material == EVersePenetrationMaterial::Glass ? VerseCollision::Profile::Glass : VerseCollision::Profile::Destructible;
	AActor* Actor = SpawnBox(Center, Rotation, FVector(ThicknessCm, WidthCm, HeightCm) * 0.5, Profile, nullptr);
	UBoxComponent* Box = BoxOf(Actor);
	Penetration->RegisterPieceProxy(Box, PieceIndex, Material);
	Query.Materials.Add(PieceIndex, Material);
	Query.Bounds.Add(PieceIndex, Box->Bounds.GetBox());
	return Actor;
}

AActor* FVerseWP03World::SpawnWorldBox(const EVerseWorldSurface* Surface, const FVector& Center, float ThicknessCm, float WidthCm, float HeightCm)
{
	UPhysicalMaterial* PhysMat = nullptr;
	if (Surface)
	{
		UVersePenetrationPhysicalMaterial* Verse = NewObject<UVersePenetrationPhysicalMaterial>(GetTransientPackage());
		Verse->Surface = *Surface;
		PhysMats.Emplace(Verse);
		PhysMat = Verse;
	}
	return SpawnBox(Center, FRotator::ZeroRotator, FVector(ThicknessCm, WidthCm, HeightCm) * 0.5, VerseCollision::Profile::Architecture, PhysMat);
}

UBoxComponent* FVerseWP03World::BoxOf(AActor* Actor) const
{
	return Actor ? Cast<UBoxComponent>(Actor->GetRootComponent()) : nullptr;
}

void FVerseWP03World::DestroyActor(AActor* Actor)
{
	if (Actor)
	{
		if (UBoxComponent* Box = BoxOf(Actor))
		{
			Penetration->UnregisterPieceProxy(Box);
		}
		Actor->Destroy();
	}
}

namespace VerseWP03Test
{
	FString GoldenFixturePath()
	{
		return FPaths::Combine(FPaths::ProjectContentDir(), TEXT("Verse"), TEXT("Test"), TEXT("WP03"), TEXT("penetration_golden.json"));
	}
}

#endif // WITH_DEV_AUTOMATION_TESTS

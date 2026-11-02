#include "Projectiles/VerseBoltPresentation.h"

#include "Combat/VerseWeaponDefinition.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Damage/VerseDamageService.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/PlayerController.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/App.h"
#include "Subsystems/SubsystemCollection.h"
#include "Weapons/VerseCombatTags.h"
#include "Weapons/VerseWeaponComponent.h"
#include "Weapons/VerseWeaponRegistry.h"

UVerseBoltPresentation* UVerseBoltPresentation::Get(const UObject* WorldContextObject)
{
	const UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UVerseBoltPresentation>() : nullptr;
}

bool UVerseBoltPresentation::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return Super::ShouldCreateSubsystem(Outer) && (!World || World->GetNetMode() != NM_DedicatedServer);
}

void UVerseBoltPresentation::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Collection.InitializeDependency<UVerseEventHub>();
	Subscribe();
}

void UVerseBoltPresentation::Subscribe()
{
	if (bSubscribed)
	{
		return;
	}
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		FireHandle = Hub->OnFire.AddUObject(this, &UVerseBoltPresentation::HandleFire);
		HitHandle = Hub->OnHit.AddUObject(this, &UVerseBoltPresentation::HandleHit);
		RejectHandle = UVerseWeaponComponent::OnAnyShotRejected.AddUObject(this, &UVerseBoltPresentation::HandleRejected);
		bSubscribed = true;
	}
}

void UVerseBoltPresentation::Deinitialize()
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnFire.Remove(FireHandle);
		Hub->OnHit.Remove(HitHandle);
	}
	UVerseWeaponComponent::OnAnyShotRejected.Remove(RejectHandle);
	bSubscribed = false;
	Bolts.Reset();
	Impacts.Reset();
	Super::Deinitialize();
}

TStatId UVerseBoltPresentation::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseBoltPresentation, STATGROUP_Tickables);
}

double UVerseBoltPresentation::WorldNow() const
{
	if (ClockOverride)
	{
		return ClockOverride();
	}
	const UWorld* World = GetWorld();
	return World ? World->GetTimeSeconds() : 0.0;
}

int32 UVerseBoltPresentation::GetLocalPlayerId() const
{
	if (LocalPlayerIdOverride.IsSet())
	{
		return LocalPlayerIdOverride.GetValue();
	}
	if (const UWorld* World = GetWorld())
	{
		if (const APlayerController* Pc = World->GetFirstPlayerController())
		{
			if (Pc->IsLocalController() && Pc->GetPawn())
			{
				return VerseCombatIds::IdOf(Pc->GetPawn());
			}
		}
	}
	return MIN_int32;
}

void UVerseBoltPresentation::HandleFire(const FVerseFireEvent& E)
{
	FVerseVisualBolt B;
	B.ShooterId = E.ShooterId;
	B.ShotCounter = E.ShotCounter;
	B.WeaponId = E.WeaponId;
	B.Origin = E.Origin;
	B.Dir = FVector(E.Direction).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
	B.SpawnTime = WorldNow();
	B.bOwn = E.ShooterId == GetLocalPlayerId();
	FGameplayTag Tag;
	if (const UVerseWeaponDefinition* W = FVerseWeaponRegistry::FindWeapon(E.WeaponId))
	{
		B.SpeedCmS = W->ProjectileSpeed * 100.0;
		B.MaxRangeCm = W->MaxRange * 100.0;
		Tag = B.bOwn ? W->BoltColorOwn : W->BoltColorFoe;
	}
	B.Color = VerseCombatTags::BoltColor(Tag, B.bOwn);
	// A bolt is drawn once: shooter and counter identify it.
	Bolts.RemoveAll([&B](const FVerseVisualBolt& X) { return X.ShooterId == B.ShooterId && X.ShotCounter == B.ShotCounter; });
	Bolts.Add(B);
}

void UVerseBoltPresentation::HandleHit(const FVerseHitEvent& E)
{
	if (E.Source != EVerseDamageSource::Bolt)
	{
		return;
	}
	const int32 Before = Bolts.Num();
	Bolts.RemoveAll([&E](const FVerseVisualBolt& X) { return X.ShooterId == E.InstigatorId && X.ShotCounter == E.ShotCounter; });
	if (Bolts.Num() != Before || E.VictimId == -1)
	{
		FVerseVisualImpact& I = Impacts.AddDefaulted_GetRef();
		I.Location = E.ImpactWorld;
		I.SpawnTime = WorldNow();
	}
}

void UVerseBoltPresentation::HandleRejected(int32 ShooterId, uint16 ShotCounter)
{
	Bolts.RemoveAll([ShooterId, ShotCounter](const FVerseVisualBolt& X) { return X.ShooterId == ShooterId && X.ShotCounter == ShotCounter; });
}

FVector UVerseBoltPresentation::HeadAt(const FVerseVisualBolt& B, double Now)
{
	const double D = FMath::Clamp((Now - B.SpawnTime) * B.SpeedCmS, 0.0, B.MaxRangeCm);
	return B.Origin + B.Dir * D;
}

int32 UVerseBoltPresentation::NumOwn() const
{
	int32 N = 0;
	for (const FVerseVisualBolt& B : Bolts)
	{
		N += B.bOwn ? 1 : 0;
	}
	return N;
}

int32 UVerseBoltPresentation::NumFoe() const
{
	return Bolts.Num() - NumOwn();
}

void UVerseBoltPresentation::Advance(double Now)
{
	Bolts.RemoveAll([Now](const FVerseVisualBolt& B) { return (Now - B.SpawnTime) * B.SpeedCmS >= B.MaxRangeCm; });
	Impacts.RemoveAll([Now](const FVerseVisualImpact& I) { return Now - I.SpawnTime > ImpactLifeS; });
	UpdateRender(Now);
}

void UVerseBoltPresentation::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	Advance(WorldNow());
}

void UVerseBoltPresentation::EnsureRender()
{
	UWorld* World = GetWorld();
	if (RenderActor || !World || !FApp::CanEverRender() || !World->IsGameWorld())
	{
		return;
	}
	UStaticMesh* Cylinder = LoadObject<UStaticMesh>(nullptr, TEXT("/Game/Verse/Test/WP02/SM_WP02_Cylinder.SM_WP02_Cylinder"));
	UStaticMesh* Sphere = LoadObject<UStaticMesh>(nullptr, TEXT("/Game/Verse/Test/WP02/SM_WP02_Sphere.SM_WP02_Sphere"));
	// Placeholder look (own WP02 test material, colour parameter); the glowing bolt material is WP14.9.
	UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Verse/Test/WP02/M_WP02_Placeholder.M_WP02_Placeholder"));
	if (!Cylinder || !Sphere || !Base)
	{
		return;
	}
	FActorSpawnParameters Params;
	Params.ObjectFlags |= RF_Transient;
	RenderActor = World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
	if (!RenderActor)
	{
		return;
	}
	auto Make = [this, Base](UStaticMesh* Mesh, const FLinearColor& Color, const TCHAR* Name)
	{
		UInstancedStaticMeshComponent* C = NewObject<UInstancedStaticMeshComponent>(RenderActor, Name);
		C->SetStaticMesh(Mesh);
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		C->SetCastShadow(false);
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, C);
		Mid->SetVectorParameterValue(TEXT("Color"), Color);
		C->SetMaterial(0, Mid);
		RenderActor->SetRootComponent(RenderActor->GetRootComponent() ? RenderActor->GetRootComponent() : C);
		C->RegisterComponent();
		RenderActor->AddInstanceComponent(C);
		return C;
	};
	OwnMeshes = Make(Cylinder, VerseCombatTags::BoltColor(VerseCombatTags::Presentation_Bolt_Amber, true), TEXT("OwnBolts"));
	FoeMeshes = Make(Cylinder, VerseCombatTags::BoltColor(VerseCombatTags::Presentation_Bolt_Red, false), TEXT("FoeBolts"));
	ImpactMeshes = Make(Sphere, FLinearColor(1.f, 0.8f, 0.5f), TEXT("Impacts"));
}

void UVerseBoltPresentation::UpdateRender(double Now)
{
	if (Bolts.Num() == 0 && Impacts.Num() == 0 && !RenderActor)
	{
		return;
	}
	EnsureRender();
	if (!OwnMeshes || !FoeMeshes || !ImpactMeshes)
	{
		return;
	}
	OwnMeshes->ClearInstances();
	FoeMeshes->ClearInstances();
	ImpactMeshes->ClearInstances();
	for (const FVerseVisualBolt& B : Bolts)
	{
		const FVector Head = HeadAt(B, Now);
		const double Length = FMath::Min(StreakLengthCm, FVector::Dist(Head, B.Origin));
		if (Length <= 1.0)
		{
			continue;
		}
		const FVector Mid = Head - B.Dir * (0.5 * Length);
		const FRotator Rot = FRotationMatrix::MakeFromZ(B.Dir).Rotator();
		const FVector Scale(StreakRadiusCm * 2.0 / 100.0, StreakRadiusCm * 2.0 / 100.0, Length / 100.0);
		(B.bOwn ? OwnMeshes : FoeMeshes)->AddInstance(FTransform(Rot, Mid, Scale), true);
	}
	for (const FVerseVisualImpact& I : Impacts)
	{
		ImpactMeshes->AddInstance(FTransform(FRotator::ZeroRotator, I.Location, FVector(0.12)), true);
	}
}

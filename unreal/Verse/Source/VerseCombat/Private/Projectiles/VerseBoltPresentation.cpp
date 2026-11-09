#include "Projectiles/VerseBoltPresentation.h"

#include "Combat/VerseWeaponDefinition.h"
#include "Components/DecalComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Damage/VerseDamageService.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/PlayerController.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/App.h"
#include "Projectiles/VersePlaceholderArt.h"
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
	Sparks.Reset();
	FoeFlashes.Reset();
	Trails.Reset();
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
	const FVerseVisualBolt* Seen = Bolts.FindByPredicate([&B](const FVerseVisualBolt& X) { return X.ShooterId == B.ShooterId && X.ShotCounter == B.ShotCounter; });
	if (Seen)
	{
		// The server's echo of an own predicted shot: the streak keeps where it was seen to leave.
		B.VisualOffset = Seen->VisualOffset;
	}
	else
	{
		FVector Muzzle;
		if (B.bOwn && VisualMuzzle && VisualMuzzle(B.ShooterId, Muzzle))
		{
			B.VisualOffset = Muzzle - B.Origin;
		}
		if (!B.bOwn)
		{
			// Another shooter's muzzle: a flash card a little ahead of the eye along the shot.
			FVerseVisualBurst& F = FoeFlashes.AddDefaulted_GetRef();
			F.Location = B.Origin + B.Dir * 45.0;
			F.Axis = B.Dir;
			F.SpawnTime = B.SpawnTime;
			F.Life = FoeFlashLifeS;
			F.Roll = float(uint32(B.ShotCounter) * 47u % 360u);
		}
	}
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
	bool bOwnBolt = false;
	for (const FVerseVisualBolt& X : Bolts)
	{
		if (X.ShooterId == E.InstigatorId && X.ShotCounter == E.ShotCounter)
		{
			bOwnBolt = X.bOwn;
			FVerseVisualTrail& Trail = Trails.AddDefaulted_GetRef();
			Trail.Start = X.Origin + X.VisualOffset;
			Trail.End = E.ImpactWorld;
			Trail.SpawnTime = WorldNow();
			Trail.bOwn = X.bOwn;
		}
	}
	Bolts.RemoveAll([&E](const FVerseVisualBolt& X) { return X.ShooterId == E.InstigatorId && X.ShotCounter == E.ShotCounter; });
	if (Bolts.Num() != Before || E.VictimId == -1)
	{
		FVerseVisualImpact& I = Impacts.AddDefaulted_GetRef();
		I.Location = E.ImpactWorld;
		I.SpawnTime = WorldNow();

		// Sparks off the surface; a world hit also leaves a scorch mark.
		const FVector Dir = FVector(E.Direction).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
		FVector Normal = -Dir;
		const UWorld* World = GetWorld();
		if (World && FApp::CanEverRender() && E.VictimId < 0)
		{
			FHitResult Surface;
			FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseBoltImpactNormal), false);
			if (World->LineTraceSingleByChannel(Surface, E.ImpactWorld - Dir * 12.0, E.ImpactWorld + Dir * 12.0, ECC_Visibility, Params))
			{
				Normal = Surface.ImpactNormal;
				PlaceScorch(Surface.ImpactPoint, Normal);
			}
		}
		FVerseVisualBurst& S = Sparks.AddDefaulted_GetRef();
		S.Location = E.ImpactWorld;
		// Sparks glance off: mostly back out along the normal, a little along the shot.
		S.Axis = (Normal + Dir * 0.35).GetSafeNormal(UE_SMALL_NUMBER, Normal);
		S.SpawnTime = I.SpawnTime;
		S.Life = SparkLifeS;
		S.Roll = float(uint32(E.ShotCounter) * 71u % 360u);
		S.bOwn = bOwnBolt;
	}
}

void UVerseBoltPresentation::PlaceScorch(const FVector& Location, const FVector& Normal)
{
	EnsureRender();
	if (!ScorchMaterial || !RenderActor)
	{
		return;
	}
	UDecalComponent* Decal = nullptr;
	if (Scorches.Num() < MaxScorchDecals)
	{
		Decal = NewObject<UDecalComponent>(RenderActor);
		Decal->SetDecalMaterial(ScorchMaterial);
		Decal->SetFadeScreenSize(0.0015f);
		Decal->RegisterComponent();
		Scorches.Add(Decal);
	}
	else
	{
		Decal = Scorches[NextScorch].Get();
		NextScorch = (NextScorch + 1) % MaxScorchDecals;
	}
	if (!Decal)
	{
		return;
	}
	FRotator Rotation = (-Normal).Rotation();
	Rotation.Roll = FMath::FRandRange(0.f, 360.f);
	// Decal box: 4 cm deep, about 7 cm across.
	Decal->DecalSize = FVector(4.0, 3.5, 3.5);
	Decal->SetWorldLocationAndRotation(Location, Rotation);
	Decal->MarkRenderStateDirty();
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

FVector UVerseBoltPresentation::VisualHeadAt(const FVerseVisualBolt& B, double Now)
{
	const FVector Head = HeadAt(B, Now);
	const double Travelled = FVector::Dist(Head, B.Origin);
	return Head + B.VisualOffset * (1.0 - FMath::Clamp(Travelled / ConvergeCm, 0.0, 1.0));
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
	Sparks.RemoveAll([Now](const FVerseVisualBurst& S) { return Now - S.SpawnTime > S.Life; });
	FoeFlashes.RemoveAll([Now](const FVerseVisualBurst& F) { return Now - F.SpawnTime > F.Life; });
	Trails.RemoveAll([Now](const FVerseVisualTrail& T) { return Now - T.SpawnTime > TrailLifeS; });
	UpdateRender(Now);
}

void UVerseBoltPresentation::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	Advance(WorldNow());
}

namespace VerseBoltArt
{
	// art/verse/weapons/specs.py VFX: the rod is 60 cm long with its tip at the origin, flying along +X;
	// the flash cards and the spark burst point along +X too.
	const TCHAR* RodMesh = TEXT("/Game/Verse/VFX/Weapons/SM_Vfx_Bolt.SM_Vfx_Bolt");
	const TCHAR* FlashMesh = TEXT("/Game/Verse/VFX/Weapons/SM_Vfx_MuzzleFlash.SM_Vfx_MuzzleFlash");
	const TCHAR* SparkMesh = TEXT("/Game/Verse/VFX/Weapons/SM_Vfx_ImpactSparks.SM_Vfx_ImpactSparks");
	const TCHAR* RodOwn = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_BoltOwn.MI_Weapon_Vfx_BoltOwn");
	const TCHAR* RodFoe = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_BoltFoe.MI_Weapon_Vfx_BoltFoe");
	const TCHAR* FlashFoe = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_MuzzleFoe.MI_Weapon_Vfx_MuzzleFoe");
	const TCHAR* Sparks = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_Sparks.MI_Weapon_Vfx_Sparks");
	const TCHAR* Scorch = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_Scorch.MI_Weapon_Vfx_Scorch");
	constexpr double RodLengthCm = 60.0;

	template <typename T>
	T* Load(const TCHAR* Path)
	{
		return LoadObject<T>(nullptr, Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	}

	/** A shot crosses the hangar in a tenth of a second: brighter than the lookdev so it reads in motion. */
	UMaterialInterface* Bright(UMaterialInterface* Base, UObject* Outer, float Nits)
	{
		if (!Base)
		{
			return nullptr;
		}
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, Outer);
		Mid->SetScalarParameterValue(TEXT("EmissiveNits"), Nits);
		return Mid;
	}
}

void UVerseBoltPresentation::EnsureRender()
{
	UWorld* World = GetWorld();
	if (RenderActor || !World || !FApp::CanEverRender() || !World->IsGameWorld())
	{
		return;
	}
	UStaticMesh* Cylinder = VersePlaceholderArt::Mesh(VersePlaceholderArt::EShape::Cylinder);
	UStaticMesh* Sphere = VersePlaceholderArt::Mesh(VersePlaceholderArt::EShape::Sphere);
	// Placeholder look (own WP02 test material, colour parameter) wherever the WP14.9 art is missing.
	UMaterialInterface* Base = VersePlaceholderArt::Material();
	if (!Cylinder || !Sphere || !Base)
	{
		return;
	}
	using namespace VerseBoltArt;
	UStaticMesh* Rod = Load<UStaticMesh>(RodMesh);
	UStaticMesh* Flash = Load<UStaticMesh>(FlashMesh);
	UStaticMesh* Spark = Load<UStaticMesh>(SparkMesh);
	UMaterialInterface* RodOwnMi = Load<UMaterialInterface>(RodOwn);
	UMaterialInterface* RodFoeMi = Load<UMaterialInterface>(RodFoe);
	UMaterialInterface* FlashFoeMi = Load<UMaterialInterface>(FlashFoe);
	UMaterialInterface* SparksMi = Load<UMaterialInterface>(VerseBoltArt::Sparks);
	ScorchMaterial = Load<UMaterialInterface>(Scorch);
	bArtBolts = Rod && Flash && Spark && RodOwnMi && RodFoeMi && FlashFoeMi && SparksMi;

	FActorSpawnParameters Params;
	Params.ObjectFlags |= RF_Transient;
	RenderActor = World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
	if (!RenderActor)
	{
		return;
	}
	auto Make = [this, Base](UStaticMesh* Mesh, const FLinearColor& Color, const TCHAR* Name, UMaterialInterface* Art)
	{
		UInstancedStaticMeshComponent* C = NewObject<UInstancedStaticMeshComponent>(RenderActor, Name);
		C->SetStaticMesh(Mesh);
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		C->SetCastShadow(false);
		if (Art)
		{
			for (int32 Slot = 0; Slot < FMath::Max(1, Mesh->GetStaticMaterials().Num()); ++Slot)
			{
				C->SetMaterial(Slot, Art);
			}
		}
		else
		{
			UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, C);
			Mid->SetVectorParameterValue(TEXT("Color"), Color);
			C->SetMaterial(0, Mid);
		}
		RenderActor->SetRootComponent(RenderActor->GetRootComponent() ? RenderActor->GetRootComponent() : C);
		C->RegisterComponent();
		RenderActor->AddInstanceComponent(C);
		return C;
	};
	const FLinearColor Amber = VerseCombatTags::BoltColor(VerseCombatTags::Presentation_Bolt_Amber, true);
	const FLinearColor Red = VerseCombatTags::BoltColor(VerseCombatTags::Presentation_Bolt_Red, false);
	if (bArtBolts)
	{
		RodArt = Rod;
		FlashArt = Flash;
		SparkArt = Spark;
		RodOwnLook = Bright(RodOwnMi, RenderActor, 60.f);
		RodFoeLook = Bright(RodFoeMi, RenderActor, 90.f);
		SparkLook = Bright(SparksMi, RenderActor, 80.f);
		FlashFoeLook = Bright(FlashFoeMi, RenderActor, 90.f);
	}
	OwnMeshes = Make(Cylinder, Amber, TEXT("OwnBolts"), nullptr);
	FoeMeshes = Make(Cylinder, Red, TEXT("FoeBolts"), nullptr);
	ImpactMeshes = Make(Sphere, FLinearColor(1.f, 0.8f, 0.5f), TEXT("Impacts"), nullptr);

	// A handful of short lights: the shot lights the walls it passes and the spot it hits.
	for (int32 I = 0; I < MaxLights; ++I)
	{
		UPointLightComponent* Light = NewObject<UPointLightComponent>(RenderActor);
		Light->SetIntensityUnits(ELightUnits::Lumens);
		Light->SetCastShadows(false);
		Light->SetAttenuationRadius(520.f);
		Light->SetSourceRadius(4.f);
		Light->SetVisibility(false);
		Light->RegisterComponent();
		Lights.Add(Light);
	}
}

void UVerseBoltPresentation::UpdateRender(double Now)
{
	if (Bolts.Num() == 0 && Impacts.Num() == 0 && Sparks.Num() == 0 && FoeFlashes.Num() == 0 && Trails.Num() == 0 && !RenderActor)
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
	ArtUsed = 0;
	for (const FVerseVisualBolt& B : Bolts)
	{
		if (bArtBolts)
		{
			// The rod's tip at the seen head, stretched back towards where the shot was seen to leave.
			const FVector Head = VisualHeadAt(B, Now);
			const double Length = FMath::Min(ArtStreakLengthCm, FVector::Dist(Head, B.Origin + B.VisualOffset));
			if (Length <= 1.0)
			{
				continue;
			}
			const FRotator Rot = FRotationMatrix::MakeFromX(B.Dir).Rotator();
			const FVector Scale(Length / VerseBoltArt::RodLengthCm, ArtWidthScale, ArtWidthScale);
			DrawArt(RodArt, B.bOwn ? RodOwnLook : RodFoeLook, FTransform(Rot, Head, Scale));
			continue;
		}
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
	if (bArtBolts)
	{
		for (const FVerseVisualBurst& S : Sparks)
		{
			const float Age = float((Now - S.SpawnTime) / FMath::Max(S.Life, 0.01));
			FRotator Rot = FRotationMatrix::MakeFromX(S.Axis).Rotator();
			Rot.Roll = S.Roll;
			// The burst flies out and thins: grows along its axis, shrinks across it.
			const FVector Scale(0.7f + 1.1f * Age, 0.9f * (1.f - 0.6f * Age), 0.9f * (1.f - 0.6f * Age));
			DrawArt(SparkArt, SparkLook, FTransform(Rot, S.Location, Scale));
		}
		for (const FVerseVisualTrail& Trail : Trails)
		{
			const FVector Along = Trail.End - Trail.Start;
			const double Length = Along.Size();
			if (Length < 10.0)
			{
				continue;
			}
			// Thins out as it fades; the rod's tip sits on the impact.
			const double Fade = 1.0 - FMath::Clamp((Now - Trail.SpawnTime) / TrailLifeS, 0.0, 1.0);
			const double Width = ArtWidthScale * (0.35 + 0.45 * Fade);
			const FRotator Rot = FRotationMatrix::MakeFromX(Along / Length).Rotator();
			DrawArt(RodArt, Trail.bOwn ? RodOwnLook : RodFoeLook, FTransform(Rot, Trail.End, FVector(Length / VerseBoltArt::RodLengthCm, Width, Width)));
		}
		for (const FVerseVisualBurst& F : FoeFlashes)
		{
			FRotator Rot = FRotationMatrix::MakeFromX(F.Axis).Rotator();
			Rot.Roll = F.Roll;
			DrawArt(FlashArt, FlashFoeLook, FTransform(Rot, F.Location, FVector(2.6)));
		}
	}
	else
	{
		for (const FVerseVisualImpact& I : Impacts)
		{
			ImpactMeshes->AddInstance(FTransform(FRotator::ZeroRotator, I.Location, FVector(0.12)), true);
		}
	}
	for (int32 I = ArtUsed; I < ArtPool.Num(); ++I)
	{
		if (ArtPool[I] && ArtPool[I]->IsVisible())
		{
			ArtPool[I]->SetVisibility(false);
		}
	}
	UpdateLights(Now);
}

void UVerseBoltPresentation::DrawArt(UStaticMesh* Mesh, UMaterialInterface* Look, const FTransform& Transform)
{
	if (!Mesh || !RenderActor)
	{
		return;
	}
	if (ArtUsed >= ArtPool.Num())
	{
		UStaticMeshComponent* New = NewObject<UStaticMeshComponent>(RenderActor);
		New->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		New->SetCastShadow(false);
		New->SetMobility(EComponentMobility::Movable);
		New->SetCanEverAffectNavigation(false);
		New->RegisterComponent();
		ArtPool.Add(New);
	}
	UStaticMeshComponent* Draw = ArtPool[ArtUsed++];
	if (Draw->GetStaticMesh() != Mesh)
	{
		Draw->SetStaticMesh(Mesh);
	}
	for (int32 Slot = 0; Slot < Draw->GetNumMaterials(); ++Slot)
	{
		if (Draw->GetMaterial(Slot) != Look)
		{
			Draw->SetMaterial(Slot, Look);
		}
	}
	Draw->SetWorldTransform(Transform);
	if (!Draw->IsVisible())
	{
		Draw->SetVisibility(true);
	}
}

void UVerseBoltPresentation::UpdateLights(double Now)
{
	if (Lights.Num() == 0)
	{
		return;
	}
	struct FCandidate
	{
		FVector Location;
		FLinearColor Color;
		float Lumens;
		double Priority;
	};
	TArray<FCandidate, TInlineAllocator<32>> Candidates;
	static const FLinearColor Amber(1.f, 0.55f, 0.15f);
	static const FLinearColor Red(1.f, 0.12f, 0.06f);
	for (const FVerseVisualBurst& F : FoeFlashes)
	{
		const float Fade = 1.f - float((Now - F.SpawnTime) / F.Life);
		Candidates.Add({F.Location, Red, 5000.f * Fade, 3.0});
	}
	for (const FVerseVisualBurst& S : Sparks)
	{
		const float Fade = 1.f - float((Now - S.SpawnTime) / S.Life);
		Candidates.Add({S.Location + S.Axis * 8.0, S.bOwn ? Amber : FLinearColor(1.f, 0.7f, 0.4f), 2600.f * Fade * Fade, 2.0});
	}
	for (const FVerseVisualBolt& B : Bolts)
	{
		Candidates.Add({VisualHeadAt(B, Now) - B.Dir * 40.0, B.bOwn ? Amber : Red, B.bOwn ? 900.f : 1600.f, B.bOwn ? 0.5 : 1.0});
	}
	Candidates.Sort([](const FCandidate& A, const FCandidate& B) { return A.Priority > B.Priority; });
	for (int32 I = 0; I < Lights.Num(); ++I)
	{
		UPointLightComponent* Light = Lights[I];
		if (!Light)
		{
			continue;
		}
		if (I < Candidates.Num() && Candidates[I].Lumens > 1.f)
		{
			Light->SetWorldLocation(Candidates[I].Location);
			Light->SetLightColor(Candidates[I].Color);
			Light->SetIntensity(Candidates[I].Lumens);
			Light->SetVisibility(true);
		}
		else if (Light->IsVisible())
		{
			Light->SetVisibility(false);
		}
	}
}

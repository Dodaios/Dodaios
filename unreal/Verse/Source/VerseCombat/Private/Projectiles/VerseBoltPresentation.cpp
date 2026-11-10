#include "Projectiles/VerseBoltPresentation.h"

#include "Combat/VerseWeaponDefinition.h"
#include "Components/DecalComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Damage/VerseDamageService.h"
#include "Destruction/VerseDestructionTypes.h"
#include "Engine/HitResult.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/App.h"
#include "Projectiles/VersePlaceholderArt.h"
#include "Projectiles/VerseProjectileManager.h"
#include "Subsystems/SubsystemCollection.h"
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
		PenetrationHandle = Hub->OnPenetration.AddUObject(this, &UVerseBoltPresentation::HandlePenetration);
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
		Hub->OnPenetration.Remove(PenetrationHandle);
	}
	UVerseWeaponComponent::OnAnyShotRejected.Remove(RejectHandle);
	bSubscribed = false;
	Bolts.Reset();
	Impacts.Reset();
	Sparks.Reset();
	MuzzleFlashes.Reset();
	Trails.Reset();
	Puffs.Reset();
	Casings.Reset();
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

int32 UVerseBoltPresentation::RoundsLeft(int32 ShooterId, FName WeaponId) const
{
	if (RoundsLeftOverride)
	{
		return RoundsLeftOverride(ShooterId, WeaponId);
	}
	UWorld* World = GetWorld();
	if (!World)
	{
		return -1;
	}
	for (TActorIterator<APawn> It(World); It; ++It)
	{
		if (VerseCombatIds::IdOf(*It) != ShooterId)
		{
			continue;
		}
		const UVerseInventoryComponent* Inventory = It->FindComponentByClass<UVerseInventoryComponent>();
		const FVerseWeaponSlotState* Slot = Inventory ? Inventory->GetActiveState() : nullptr;
		if (Slot && Slot->Definition && Slot->Definition->WeaponId == WeaponId)
		{
			return FVerseMagazine::RoundsReady(*Slot, *Slot->Definition);
		}
		return -1;
	}
	return -1;
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
	B.Color = TracerColor();
	const UVerseWeaponDefinition* W = FVerseWeaponRegistry::FindWeapon(E.WeaponId);
	if (W)
	{
		B.SpeedCmS = W->ProjectileSpeed * 100.0;
		B.MaxRangeCm = W->MaxRange * 100.0;
	}
	const FVerseVisualBolt* Seen = Bolts.FindByPredicate([&B](const FVerseVisualBolt& X) { return X.ShooterId == B.ShooterId && X.ShotCounter == B.ShotCounter; });
	if (Seen)
	{
		// The server's echo of an own predicted shot: same round, same tracer, same seen muzzle.
		B.VisualOffset = Seen->VisualOffset;
		B.bTracer = Seen->bTracer;
	}
	else
	{
		B.bTracer = W && W->IsTracerRound(E.ShotCounter, RoundsLeft(E.ShooterId, E.WeaponId));
		FVector Muzzle = B.Origin + B.Dir * 45.0;
		if (B.bOwn && VisualMuzzle && VisualMuzzle(B.ShooterId, Muzzle))
		{
			B.VisualOffset = Muzzle - B.Origin;
		}
		if (!B.bOwn)
		{
			// Another shooter's muzzle (the viewmodel draws the own one): a flash card a little ahead
			// of the eye along the shot, with a short warm light.
			FVerseVisualBurst& F = MuzzleFlashes.AddDefaulted_GetRef();
			F.Location = Muzzle;
			F.Axis = B.Dir;
			F.SpawnTime = B.SpawnTime;
			F.Life = MuzzleFlashLifeS;
			F.Roll = float(uint32(B.ShotCounter) * 47u % 360u);
		}
		// Every shot: a little powder smoke at the muzzle and a brass case out of the ejection port.
		const FVector Side = FVector::CrossProduct(FVector::UpVector, B.Dir).GetSafeNormal(UE_SMALL_NUMBER, FVector::RightVector);
		SpawnPuff(Muzzle + B.Dir * 6.0, B.Dir * 60.0 + FVector(0, 0, 18), B.SpawnTime, 0.55, 4.f, 26.f, 0.16f, FLinearColor(0.23f, 0.22f, 0.21f));
		const bool bLong = !W || W->Slot != EVerseLoadoutSlot::Secondary;
		const FVector Port = Muzzle - B.Dir * (bLong ? 42.0 : 14.0) + Side * 2.0 + FVector(0, 0, 3);
		SpawnCasing(Port, B.Dir, bLong, B.SpawnTime);
	}
	// A round is drawn once: shooter and counter identify it.
	Bolts.RemoveAll([&B](const FVerseVisualBolt& X) { return X.ShooterId == B.ShooterId && X.ShotCounter == B.ShotCounter; });
	Bolts.Add(B);
}

EVerseImpactSurface UVerseBoltPresentation::SurfaceOfWireId(uint8 MaterialWireId)
{
	switch (EVersePenetrationMaterial(MaterialWireId))
	{
	case EVersePenetrationMaterial::Glass: return EVerseImpactSurface::Glass;
	case EVersePenetrationMaterial::Concrete:
	case EVersePenetrationMaterial::CeilingPanel:
	case EVersePenetrationMaterial::CladdingPanel: return EVerseImpactSurface::Concrete;
	default: return EVerseImpactSurface::Metal;
	}
}

EVerseImpactSurface UVerseBoltPresentation::ClassifySurface(const FHitResult& Hit)
{
	FString Names;
	if (const UPrimitiveComponent* C = Hit.GetComponent())
	{
		Names += C->GetName();
		if (const UMaterialInterface* M = C->GetMaterial(FMath::Max<int32>(0, int32(Hit.ElementIndex))))
		{
			Names += TEXT(" ") + M->GetName();
		}
	}
	if (const AActor* A = Hit.GetActor())
	{
		Names += TEXT(" ") + A->GetName();
		if (Cast<APawn>(A))
		{
			return EVerseImpactSurface::Flesh;
		}
	}
	for (const TCHAR* Key : {TEXT("glass"), TEXT("glazing"), TEXT("window"), TEXT("pane")})
	{
		if (Names.Contains(Key, ESearchCase::IgnoreCase))
		{
			return EVerseImpactSurface::Glass;
		}
	}
	for (const TCHAR* Key : {TEXT("concrete"), TEXT("floor"), TEXT("ground"), TEXT("plaster"), TEXT("cladding"), TEXT("ceiling")})
	{
		if (Names.Contains(Key, ESearchCase::IgnoreCase))
		{
			return EVerseImpactSurface::Concrete;
		}
	}
	return EVerseImpactSurface::Metal;
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
			if (X.bTracer)
			{
				FVerseVisualTrail& Trail = Trails.AddDefaulted_GetRef();
				Trail.Start = X.Origin + X.VisualOffset;
				Trail.End = E.ImpactWorld;
				Trail.SpawnTime = WorldNow();
				Trail.bOwn = X.bOwn;
			}
		}
	}
	Bolts.RemoveAll([&E](const FVerseVisualBolt& X) { return X.ShooterId == E.InstigatorId && X.ShotCounter == E.ShotCounter; });
	if (Bolts.Num() == Before && E.VictimId != -1)
	{
		return;
	}
	const double Now = WorldNow();
	FVerseVisualImpact& I = Impacts.AddDefaulted_GetRef();
	I.Location = E.ImpactWorld;
	I.SpawnTime = Now;
	// A body hit: the gore system draws the blood; nothing more here.
	if (E.VictimId >= 0)
	{
		I.Surface = EVerseImpactSurface::Flesh;
		return;
	}

	const FVector Dir = FVector(E.Direction).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
	FVector Normal = -Dir;
	EVerseImpactSurface Surface = EVerseImpactSurface::Metal;
	const UWorld* World = GetWorld();
	if (World && FApp::CanEverRender())
	{
		FHitResult Hit;
		FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseBulletImpactSurface), false);
		if (World->LineTraceSingleByChannel(Hit, E.ImpactWorld - Dir * 12.0, E.ImpactWorld + Dir * 12.0, ECC_Visibility, Params))
		{
			Normal = Hit.ImpactNormal;
			Surface = ClassifySurface(Hit);
			if (Surface != EVerseImpactSurface::Flesh)
			{
				PlaceHole(Hit.ImpactPoint, Normal, Surface);
			}
		}
	}
	I.Surface = Surface;
	if (Surface == EVerseImpactSurface::Flesh)
	{
		return;
	}
	FVerseVisualBurst& S = Sparks.AddDefaulted_GetRef();
	S.Location = E.ImpactWorld;
	// Ricochet sparks and chips glance off: mostly back out along the normal, a little along the shot.
	S.Axis = (Normal + Dir * 0.35).GetSafeNormal(UE_SMALL_NUMBER, Normal);
	S.SpawnTime = Now;
	S.Life = Surface == EVerseImpactSurface::Glass ? SparkLifeS * 1.6 : SparkLifeS;
	S.Roll = float(uint32(E.ShotCounter) * 71u % 360u);
	S.bOwn = bOwnBolt;
	S.Surface = Surface;
	if (Surface == EVerseImpactSurface::Concrete)
	{
		// Concrete and plaster: a grey dust puff blown out of the hole.
		SpawnPuff(E.ImpactWorld + Normal * 4.0, Normal * 90.0 + FVector(0, 0, 10), Now, 0.9, 6.f, 46.f, 0.32f, FLinearColor(0.32f, 0.3f, 0.27f));
	}
	else if (Surface == EVerseImpactSurface::Metal)
	{
		SpawnPuff(E.ImpactWorld + Normal * 3.0, Normal * 40.0, Now, 0.35, 3.f, 14.f, 0.12f, FLinearColor(0.16f, 0.16f, 0.16f));
	}
}

void UVerseBoltPresentation::HandlePenetration(const FVersePenetrationEvent& E)
{
	if (!E.bPassed || !FApp::CanEverRender())
	{
		return;
	}
	const EVerseImpactSurface Surface = SurfaceOfWireId(E.MaterialWireId);
	const FVector Along = (FVector(E.Exit) - FVector(E.Entry)).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
	PlaceHole(E.Entry, -Along, Surface);
	PlaceHole(E.Exit, Along, Surface);
	if (Surface == EVerseImpactSurface::Concrete)
	{
		SpawnPuff(FVector(E.Exit) + Along * 6.0, Along * 120.0, WorldNow(), 0.8, 6.f, 40.f, 0.28f, FLinearColor(0.32f, 0.3f, 0.27f));
	}
}

void UVerseBoltPresentation::SpawnPuff(const FVector& Location, const FVector& Velocity, double Now, double Life, float StartCm,
	float EndCm, float Opacity, const FLinearColor& Tint)
{
	if (Puffs.Num() >= MaxPuffs)
	{
		Puffs.RemoveAt(0, 1, EAllowShrinking::No);
	}
	FVerseVisualPuff& P = Puffs.AddDefaulted_GetRef();
	P.Location = Location;
	P.Velocity = Velocity;
	P.SpawnTime = Now;
	P.Life = Life;
	P.StartCm = StartCm;
	P.EndCm = EndCm;
	P.Opacity = Opacity;
	P.Tint = Tint;
}

void UVerseBoltPresentation::SpawnCasing(const FVector& Port, const FVector& ShotDir, bool bLong, double Now)
{
	if (Casings.Num() >= MaxCasings)
	{
		Casings.RemoveAt(0, 1, EAllowShrinking::No);
	}
	const FVector Side = FVector::CrossProduct(FVector::UpVector, ShotDir).GetSafeNormal(UE_SMALL_NUMBER, FVector::RightVector);
	FVerseVisualCasing& C = Casings.AddDefaulted_GetRef();
	C.Location = Port;
	// Out of the right side, up and a little back, with some scatter (cm/s).
	C.Velocity = Side * FMath::FRandRange(260.0, 360.0) + FVector(0, 0, FMath::FRandRange(170.0, 260.0)) - ShotDir * FMath::FRandRange(20.0, 80.0);
	C.Rotation = FQuat(FRotationMatrix::MakeFromZ(Side).ToQuat());
	C.SpinAxis = (ShotDir + FVector(0, 0, 0.3)).GetSafeNormal();
	C.SpinRate = FMath::FRandRange(25.0, 45.0);
	C.SpawnTime = Now;
	C.bLong = bLong;
}

void UVerseBoltPresentation::StepCasings(double Now, double Dt)
{
	Casings.RemoveAll([Now](const FVerseVisualCasing& C) { return Now - C.SpawnTime > CasingLifeS; });
	if (Dt <= 0.0)
	{
		return;
	}
	const UWorld* World = GetWorld();
	const bool bTrace = World && FApp::CanEverRender();
	const FVector Gravity(0.0, 0.0, -UVerseProjectileManager::GravityCmS2);
	for (FVerseVisualCasing& C : Casings)
	{
		if (C.bResting)
		{
			continue;
		}
		const FVector From = C.Location;
		C.Velocity += Gravity * Dt;
		FVector To = From + C.Velocity * Dt;
		C.Rotation = FQuat(C.SpinAxis, C.SpinRate * Dt) * C.Rotation;
		FHitResult Hit;
		FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseCasing), false);
		if (bTrace && World->LineTraceSingleByChannel(Hit, From, To, ECC_Visibility, Params) && !Cast<APawn>(Hit.GetActor()))
		{
			// Bounce: brass on steel or concrete keeps a third of its speed off the surface.
			const FVector N = Hit.ImpactNormal;
			const FVector Vn = N * FVector::DotProduct(C.Velocity, N);
			const FVector Vt = C.Velocity - Vn;
			C.Velocity = Vt * 0.55 - Vn * 0.32;
			C.SpinRate *= 0.6;
			C.Location = FVector(Hit.ImpactPoint) + N * 0.5;
			++C.Bounces;
			if (N.Z > 0.6 && (C.Velocity.Size() < 45.0 || C.Bounces >= 4))
			{
				// Lies on its side on the floor.
				C.bResting = true;
				C.Velocity = FVector::ZeroVector;
				const FVector Along = C.Rotation.GetAxisZ();
				const FVector Flat = FVector::VectorPlaneProject(Along, N).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
				C.Rotation = FRotationMatrix::MakeFromZX(Flat, N).ToQuat();
				C.Location = FVector(Hit.ImpactPoint) + N * (C.bLong ? 0.55 : 0.45);
			}
			continue;
		}
		C.Location = To;
	}
}

void UVerseBoltPresentation::PlaceHole(const FVector& Location, const FVector& Normal, EVerseImpactSurface Surface)
{
	EnsureRender();
	const int32 Look = Surface == EVerseImpactSurface::Concrete ? 1 : Surface == EVerseImpactSurface::Glass ? 2 : 0;
	if (!RenderActor || !HoleLooks.IsValidIndex(Look) || !HoleLooks[Look])
	{
		return;
	}
	UDecalComponent* Decal = nullptr;
	if (Holes.Num() < MaxHoleDecals)
	{
		Decal = NewObject<UDecalComponent>(RenderActor);
		Decal->SetFadeScreenSize(0.0012f);
		Decal->RegisterComponent();
		Holes.Add(Decal);
	}
	else
	{
		Decal = Holes[NextHole].Get();
		NextHole = (NextHole + 1) % MaxHoleDecals;
	}
	if (!Decal)
	{
		return;
	}
	Decal->SetDecalMaterial(HoleLooks[Look]);
	FRotator Rotation = (-Normal).Rotation();
	Rotation.Roll = FMath::FRandRange(0.f, 360.f);
	// Decal box half extents: a ~1.4 cm hole with a dark ring on metal, a wider grey chip on
	// concrete, a pale crack star on glass.
	const double Half = Surface == EVerseImpactSurface::Concrete ? 2.6 : Surface == EVerseImpactSurface::Glass ? 4.5 : 1.4;
	Decal->DecalSize = FVector(3.0, Half, Half);
	Decal->SetWorldLocationAndRotation(Location, Rotation);
	Decal->MarkRenderStateDirty();
}

void UVerseBoltPresentation::HandleRejected(int32 ShooterId, uint16 ShotCounter)
{
	Bolts.RemoveAll([ShooterId, ShotCounter](const FVerseVisualBolt& X) { return X.ShooterId == ShooterId && X.ShotCounter == ShotCounter; });
}

FVector UVerseBoltPresentation::HeadAt(const FVerseVisualBolt& B, double Now)
{
	const double MaxT = B.MaxRangeCm / FMath::Max(1.0, B.SpeedCmS);
	const double T = FMath::Clamp(Now - B.SpawnTime, 0.0, MaxT);
	return UVerseProjectileManager::BallisticPosition(B.Origin, B.Dir, B.SpeedCmS, T);
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

int32 UVerseBoltPresentation::NumTracers() const
{
	int32 N = 0;
	for (const FVerseVisualBolt& B : Bolts)
	{
		N += B.bTracer ? 1 : 0;
	}
	return N;
}

void UVerseBoltPresentation::Advance(double Now)
{
	const double Dt = LastAdvance < 0.0 ? 0.0 : FMath::Clamp(Now - LastAdvance, 0.0, 0.1);
	LastAdvance = Now;
	Bolts.RemoveAll([Now](const FVerseVisualBolt& B) { return (Now - B.SpawnTime) * B.SpeedCmS >= B.MaxRangeCm; });
	Impacts.RemoveAll([Now](const FVerseVisualImpact& I) { return Now - I.SpawnTime > ImpactLifeS; });
	Sparks.RemoveAll([Now](const FVerseVisualBurst& S) { return Now - S.SpawnTime > S.Life; });
	MuzzleFlashes.RemoveAll([Now](const FVerseVisualBurst& F) { return Now - F.SpawnTime > F.Life; });
	Trails.RemoveAll([Now](const FVerseVisualTrail& T) { return Now - T.SpawnTime > TrailLifeS; });
	Puffs.RemoveAll([Now](const FVerseVisualPuff& P) { return Now - P.SpawnTime > P.Life; });
	StepCasings(Now, Dt);
	UpdateRender(Now);
}

void UVerseBoltPresentation::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	Advance(WorldNow());
}

namespace VerseBulletArt
{
	// art/verse/weapons/specs.py VFX: the streak rod is 60 cm long with its tip at the origin, flying
	// along +X; the flash cards and the spark burst point along +X too. The looks are recoloured here.
	const TCHAR* RodMesh = TEXT("/Game/Verse/VFX/Weapons/SM_Vfx_Bolt.SM_Vfx_Bolt");
	const TCHAR* FlashMesh = TEXT("/Game/Verse/VFX/Weapons/SM_Vfx_MuzzleFlash.SM_Vfx_MuzzleFlash");
	const TCHAR* SparkMesh = TEXT("/Game/Verse/VFX/Weapons/SM_Vfx_ImpactSparks.SM_Vfx_ImpactSparks");
	const TCHAR* RodMi = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_BoltOwn.MI_Weapon_Vfx_BoltOwn");
	const TCHAR* FlashMi = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_MuzzleFoe.MI_Weapon_Vfx_MuzzleFoe");
	const TCHAR* SparksMi = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_Sparks.MI_Weapon_Vfx_Sparks");
	const TCHAR* HoleMi = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_Scorch.MI_Weapon_Vfx_Scorch");
	const TCHAR* SoftMaster = TEXT("/Game/Verse/Materials/Master/M_Verse_Glass.M_Verse_Glass");
	const TCHAR* SurfaceMaster = TEXT("/Game/Verse/Materials/Master/M_Verse_Surface.M_Verse_Surface");
	constexpr double RodLengthCm = 60.0;

	template <typename T>
	T* Load(const TCHAR* Path)
	{
		return LoadObject<T>(nullptr, Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	}

	/** A recoloured emissive look: the shot crosses the hangar in a few frames, so it is bright. */
	UMaterialInterface* Emissive(UMaterialInterface* Base, UObject* Outer, const FLinearColor& Color, float Nits)
	{
		if (!Base)
		{
			return nullptr;
		}
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, Outer);
		Mid->SetVectorParameterValue(TEXT("EmissiveColor"), Color);
		Mid->SetScalarParameterValue(TEXT("EmissiveNits"), Nits);
		return Mid;
	}

	UMaterialInterface* Hole(UMaterialInterface* Base, UObject* Outer, const FLinearColor& Tint, float Opacity)
	{
		if (!Base)
		{
			return nullptr;
		}
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, Outer);
		Mid->SetVectorParameterValue(TEXT("BaseTint"), Tint);
		Mid->SetScalarParameterValue(TEXT("Opacity"), Opacity);
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
	using namespace VerseBulletArt;
	UStaticMesh* Rod = Load<UStaticMesh>(RodMesh);
	UStaticMesh* Flash = Load<UStaticMesh>(FlashMesh);
	UStaticMesh* Spark = Load<UStaticMesh>(SparkMesh);
	UMaterialInterface* RodBase = Load<UMaterialInterface>(RodMi);
	UMaterialInterface* FlashBase = Load<UMaterialInterface>(FlashMi);
	UMaterialInterface* SparkBase = Load<UMaterialInterface>(SparksMi);
	UMaterialInterface* HoleBase = Load<UMaterialInterface>(HoleMi);
	UMaterialInterface* Soft = Load<UMaterialInterface>(SoftMaster);
	UMaterialInterface* Brass = Load<UMaterialInterface>(SurfaceMaster);
	bArtBolts = Rod && Flash && Spark && RodBase && FlashBase && SparkBase;

	FActorSpawnParameters Params;
	Params.ObjectFlags |= RF_Transient;
	RenderActor = World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
	if (!RenderActor)
	{
		return;
	}
	auto Make = [this, Base](UStaticMesh* Mesh, const FLinearColor& Color, const TCHAR* Name, UMaterialInterface* Look)
	{
		UInstancedStaticMeshComponent* C = NewObject<UInstancedStaticMeshComponent>(RenderActor, Name);
		C->SetStaticMesh(Mesh);
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		C->SetCastShadow(false);
		UMaterialInterface* Use = Look;
		if (!Use)
		{
			UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, C);
			Mid->SetVectorParameterValue(TEXT("Color"), Color);
			Use = Mid;
		}
		C->SetMaterial(0, Use);
		RenderActor->SetRootComponent(RenderActor->GetRootComponent() ? RenderActor->GetRootComponent() : C);
		C->RegisterComponent();
		RenderActor->AddInstanceComponent(C);
		return C;
	};
	if (bArtBolts)
	{
		RodArt = Rod;
		FlashArt = Flash;
		SparkArt = Spark;
		TracerLook = Emissive(RodBase, RenderActor, TracerColor(), 140.f);
		FlashLook = Emissive(FlashBase, RenderActor, FLinearColor(1.f, 0.58f, 0.2f), 70.f);
		SparkLook = Emissive(SparkBase, RenderActor, FLinearColor(1.f, 0.72f, 0.36f), 90.f);
		ShardLook = Emissive(SparkBase, RenderActor, FLinearColor(0.75f, 0.85f, 0.95f), 6.f);
	}
	TracerMeshes = Make(Cylinder, TracerColor(), TEXT("Tracers"), nullptr);
	ImpactMeshes = Make(Sphere, FLinearColor(1.f, 0.8f, 0.5f), TEXT("Impacts"), nullptr);
	// Brass: bare metal, warm, fairly smooth. The placeholder colour stands in without the master.
	UMaterialInterface* BrassLook = nullptr;
	if (Brass)
	{
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Brass, RenderActor);
		Mid->SetVectorParameterValue(TEXT("BaseTint"), FLinearColor(0.55f, 0.36f, 0.1f));
		Mid->SetScalarParameterValue(TEXT("Metallic"), 1.f);
		Mid->SetScalarParameterValue(TEXT("RoughnessMin"), 0.25f);
		Mid->SetScalarParameterValue(TEXT("RoughnessMax"), 0.4f);
		Mid->SetScalarParameterValue(TEXT("EdgeWear"), 0.f);
		Mid->SetScalarParameterValue(TEXT("GrimeAmount"), 0.1f);
		BrassLook = Mid;
	}
	CasingMeshes = Make(Cylinder, FLinearColor(0.7f, 0.5f, 0.15f), TEXT("Casings"), BrassLook);
	CasingMeshes->SetCastShadow(true);

	// Bullet holes per surface: a dark hole with a ring on metal, a grey chip on concrete, a pale crack on glass.
	HoleLooks.Reset();
	HoleLooks.Add(Hole(HoleBase, RenderActor, FLinearColor(0.004f, 0.004f, 0.004f), 0.95f));
	HoleLooks.Add(Hole(HoleBase, RenderActor, FLinearColor(0.09f, 0.085f, 0.08f), 0.9f));
	HoleLooks.Add(Hole(HoleBase, RenderActor, FLinearColor(0.6f, 0.62f, 0.64f), 0.55f));

	// Puffs: translucent soft spheres, one material each so each fades on its own.
	for (int32 I = 0; Soft && I < MaxPuffs; ++I)
	{
		UStaticMeshComponent* P = NewObject<UStaticMeshComponent>(RenderActor);
		P->SetStaticMesh(Sphere);
		P->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		P->SetCastShadow(false);
		P->SetMobility(EComponentMobility::Movable);
		P->SetCanEverAffectNavigation(false);
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Soft, P);
		Mid->SetScalarParameterValue(TEXT("Roughness"), 1.f);
		Mid->SetScalarParameterValue(TEXT("EmissiveNits"), 0.f);
		P->SetMaterial(0, Mid);
		P->SetVisibility(false);
		P->RegisterComponent();
		PuffPool.Add(P);
		PuffLooks.Add(Mid);
	}

	// A handful of short lights: a muzzle flash and metal sparks light their surroundings for a frame or two.
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
	if (Bolts.Num() == 0 && Impacts.Num() == 0 && Sparks.Num() == 0 && MuzzleFlashes.Num() == 0 && Trails.Num() == 0
		&& Puffs.Num() == 0 && Casings.Num() == 0 && !RenderActor)
	{
		return;
	}
	EnsureRender();
	if (!TracerMeshes || !ImpactMeshes || !CasingMeshes)
	{
		return;
	}
	TracerMeshes->ClearInstances();
	ImpactMeshes->ClearInstances();
	CasingMeshes->ClearInstances();
	ArtUsed = 0;
	for (const FVerseVisualBolt& B : Bolts)
	{
		if (!B.bTracer)
		{
			continue; // ball ammunition: invisible in flight
		}
		const FVector Head = VisualHeadAt(B, Now);
		const FVector Back = VisualHeadAt(B, FMath::Max(B.SpawnTime, Now - 0.006));
		const FVector Along = (Head - Back).GetSafeNormal(UE_SMALL_NUMBER, B.Dir);
		if (bArtBolts)
		{
			// The rod's tip at the seen head, stretched back along the flight as a thin line.
			const double Length = FMath::Min(ArtStreakLengthCm, FVector::Dist(Head, B.Origin + B.VisualOffset));
			if (Length <= 1.0)
			{
				continue;
			}
			const FRotator Rot = FRotationMatrix::MakeFromX(Along).Rotator();
			const FVector Scale(Length / VerseBulletArt::RodLengthCm, ArtWidthScale, ArtWidthScale);
			DrawArt(RodArt, TracerLook, FTransform(Rot, Head, Scale));
			continue;
		}
		const double Length = FMath::Min(StreakLengthCm, FVector::Dist(Head, B.Origin));
		if (Length <= 1.0)
		{
			continue;
		}
		const FVector Mid = Head - Along * (0.5 * Length);
		const FRotator Rot = FRotationMatrix::MakeFromZ(Along).Rotator();
		const FVector Scale(StreakRadiusCm * 2.0 / 100.0, StreakRadiusCm * 2.0 / 100.0, Length / 100.0);
		TracerMeshes->AddInstance(FTransform(Rot, Mid, Scale), true);
	}
	for (const FVerseVisualCasing& C : Casings)
	{
		// The placeholder cylinder is 100 cm tall along Z: a case is ~4.5 cm (rifle) or ~2 cm (pistol) long.
		const double Len = C.bLong ? 0.045 : 0.02;
		const double Dia = C.bLong ? 0.011 : 0.009;
		CasingMeshes->AddInstance(FTransform(C.Rotation, C.Location, FVector(Dia, Dia, Len)), true);
	}
	if (bArtBolts)
	{
		for (const FVerseVisualBurst& S : Sparks)
		{
			if (S.Surface == EVerseImpactSurface::Concrete)
			{
				continue; // dust, no sparks
			}
			const float Age = float((Now - S.SpawnTime) / FMath::Max(S.Life, 0.01));
			FRotator Rot = FRotationMatrix::MakeFromX(S.Axis).Rotator();
			Rot.Roll = S.Roll;
			// The burst flies out and thins: grows along its axis, shrinks across it.
			const float Size = S.Surface == EVerseImpactSurface::Glass ? 0.6f : 0.4f;
			const FVector Scale(Size * (0.7f + 1.4f * Age), Size * (1.f - 0.7f * Age), Size * (1.f - 0.7f * Age));
			DrawArt(SparkArt, S.Surface == EVerseImpactSurface::Glass ? ShardLook : SparkLook, FTransform(Rot, S.Location, Scale));
		}
		for (const FVerseVisualTrail& Trail : Trails)
		{
			const FVector Along = Trail.End - Trail.Start;
			const double Length = FMath::Min(Along.Size(), ArtStreakLengthCm);
			if (Length < 10.0)
			{
				continue;
			}
			// The tracer's last streak into the impact, thinning as it fades.
			const double Fade = 1.0 - FMath::Clamp((Now - Trail.SpawnTime) / TrailLifeS, 0.0, 1.0);
			const double Width = ArtWidthScale * (0.4 + 0.6 * Fade);
			const FRotator Rot = FRotationMatrix::MakeFromX(Along.GetSafeNormal()).Rotator();
			DrawArt(RodArt, TracerLook, FTransform(Rot, Trail.End, FVector(Length / VerseBulletArt::RodLengthCm, Width, Width)));
		}
		for (const FVerseVisualBurst& F : MuzzleFlashes)
		{
			const float Age = float((Now - F.SpawnTime) / FMath::Max(F.Life, 0.01));
			FRotator Rot = FRotationMatrix::MakeFromX(F.Axis).Rotator();
			Rot.Roll = F.Roll;
			DrawArt(FlashArt, FlashLook, FTransform(Rot, F.Location, FVector(1.5f * (1.f - 0.4f * Age))));
		}
	}
	else
	{
		for (const FVerseVisualImpact& I : Impacts)
		{
			if (I.Surface != EVerseImpactSurface::Flesh)
			{
				ImpactMeshes->AddInstance(FTransform(FRotator::ZeroRotator, I.Location, FVector(0.04)), true);
			}
		}
	}
	for (int32 I = ArtUsed; I < ArtPool.Num(); ++I)
	{
		if (ArtPool[I] && ArtPool[I]->IsVisible())
		{
			ArtPool[I]->SetVisibility(false);
		}
	}
	for (int32 I = 0; I < PuffPool.Num(); ++I)
	{
		UStaticMeshComponent* P = PuffPool[I];
		if (!P)
		{
			continue;
		}
		if (!Puffs.IsValidIndex(I))
		{
			if (P->IsVisible())
			{
				P->SetVisibility(false);
			}
			continue;
		}
		const FVerseVisualPuff& Puff = Puffs[I];
		const double Age = Now - Puff.SpawnTime;
		const double A = FMath::Clamp(Age / FMath::Max(Puff.Life, 0.01), 0.0, 1.0);
		// Expands fast, then drifts and slows: x = v * tau * (1 - e^(-t / tau)).
		const double Tau = 0.18;
		const FVector Where = Puff.Location + Puff.Velocity * (Tau * (1.0 - FMath::Exp(-Age / Tau))) + FVector(0, 0, 12.0 * Age);
		const double Size = FMath::Lerp(double(Puff.StartCm), double(Puff.EndCm), 1.0 - FMath::Square(1.0 - A));
		P->SetWorldTransform(FTransform(FRotator::ZeroRotator, Where, FVector(Size / 100.0)));
		if (UMaterialInstanceDynamic* Mid = PuffLooks.IsValidIndex(I) ? PuffLooks[I].Get() : nullptr)
		{
			Mid->SetVectorParameterValue(TEXT("BaseTint"), Puff.Tint);
			Mid->SetScalarParameterValue(TEXT("Opacity"), Puff.Opacity);
			Mid->SetScalarParameterValue(TEXT("Fade"), float(FMath::Square(1.0 - A)));
		}
		if (!P->IsVisible())
		{
			P->SetVisibility(true);
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
	static const FLinearColor Flash(1.f, 0.6f, 0.25f);
	static const FLinearColor Spark(1.f, 0.72f, 0.4f);
	static const FLinearColor Tracer(1.f, 0.78f, 0.45f);
	for (const FVerseVisualBurst& F : MuzzleFlashes)
	{
		const float Fade = 1.f - float((Now - F.SpawnTime) / F.Life);
		Candidates.Add({F.Location, Flash, 6000.f * Fade, 3.0});
	}
	for (const FVerseVisualBurst& S : Sparks)
	{
		if (S.Surface != EVerseImpactSurface::Metal)
		{
			continue;
		}
		const float Fade = 1.f - float((Now - S.SpawnTime) / S.Life);
		Candidates.Add({S.Location + S.Axis * 8.0, Spark, 1200.f * Fade * Fade, 2.0});
	}
	for (const FVerseVisualBolt& B : Bolts)
	{
		if (B.bTracer)
		{
			Candidates.Add({VisualHeadAt(B, Now) - B.Dir * 40.0, Tracer, 350.f, 0.5});
		}
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

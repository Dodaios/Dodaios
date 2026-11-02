#include "Gore/VerseGoreSubsystem.h"

#include "AnimationRuntime.h"
#include "Camera/PlayerCameraManager.h"
#include "Components/DecalComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkinnedAsset.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "Gore/VerseGoreActor.h"
#include "HAL/PlatformTime.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/App.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/FileHelper.h"
#include "Stats/Stats.h"
#include "VerseLog.h"
#include "VerseRng.h"

namespace VerseGorePrivate
{
	/** Gore's own assets (work-packages.md WP05 owns /Game/Verse/Gore/**), built by art/verse/gore/. */
	const TCHAR* SpatterMaterialPaths[] = {
		TEXT("/Game/Verse/Gore/MI_Gore_Spatter_0.MI_Gore_Spatter_0"),
		TEXT("/Game/Verse/Gore/MI_Gore_Spatter_1.MI_Gore_Spatter_1"),
		TEXT("/Game/Verse/Gore/MI_Gore_Spatter_2.MI_Gore_Spatter_2"),
		TEXT("/Game/Verse/Gore/MI_Gore_Spatter_3.MI_Gore_Spatter_3"),
	};
	const TCHAR* DripMaterialPath = TEXT("/Game/Verse/Gore/MI_Gore_Drip.MI_Gore_Drip");
	const TCHAR* PoolMaterialPath = TEXT("/Game/Verse/Gore/MI_Gore_Pool.MI_Gore_Pool");
	const TCHAR* DropletMaterialPath = TEXT("/Game/Verse/Gore/M_Gore_Droplet.M_Gore_Droplet");
	const TCHAR* FlashMaterialPath = TEXT("/Game/Verse/Gore/M_Gore_Flash.M_Gore_Flash");
	/** Engine primitive used as the droplet and flash shape (referenced, never committed). */
	const TCHAR* DropletMeshPath = TEXT("/Engine/BasicShapes/Sphere.Sphere");
	/** The settings section UVerseSettings (module Verse) saves to; read as text, no include. */
	const TCHAR* SettingsSection = TEXT("/Script/Verse.VerseSettings");

	/** Pools for one victim closer together than this are one pool (death after finisher kill). */
	constexpr double PoolDedupeSeconds = 3.0;

	double CyclesToMs(uint64 Cycles)
	{
		return FPlatformTime::ToMilliseconds64(Cycles);
	}

	template <typename T>
	T* LoadOptional(const TCHAR* Path)
	{
		return Cast<T>(StaticLoadObject(T::StaticClass(), nullptr, Path, nullptr, LOAD_NoWarn | LOAD_Quiet));
	}

	float SmoothGrowth(float Alpha)
	{
		const float A = FMath::Clamp(Alpha, 0.f, 1.f);
		return 1.f - FMath::Square(1.f - A);   // ease out: fast spread, slow stop
	}
}

// ---------------------------------------------------------------------------------------------
// Tuning tables

FName VerseGoreParams::WoundSlot(int32 Index)
{
	static TArray<FName> Names = []
	{
		TArray<FName> Result;
		for (int32 I = 0; I < 16; ++I)
		{
			Result.Add(FName(*FString::Printf(TEXT("Verse_Wound_%02d"), I)));
		}
		return Result;
	}();
	return Names.IsValidIndex(Index) ? Names[Index] : NAME_None;
}

int32 FVerseGoreTuning::BaseDroplets(EVerseHitZone Zone)
{
	switch (Zone)
	{
	case EVerseHitZone::Head: return 30;
	case EVerseHitZone::Neck: return 26;
	case EVerseHitZone::UpperTorso: return 20;
	case EVerseHitZone::LowerTorso: return 18;
	case EVerseHitZone::Arm: return 12;
	case EVerseHitZone::Leg: return 12;
	default: return 10;
	}
}

int32 FVerseGoreTuning::SpatterTraces(EVerseHitZone Zone)
{
	switch (Zone)
	{
	case EVerseHitZone::Head: return 3;
	case EVerseHitZone::Neck: return 3;
	case EVerseHitZone::UpperTorso: return 2;
	case EVerseHitZone::LowerTorso: return 2;
	default: return 1;
	}
}

// ---------------------------------------------------------------------------------------------
// Lifetime

UVerseGoreSubsystem* UVerseGoreSubsystem::Get(const UObject* WorldContextObject)
{
	if (!WorldContextObject || !GEngine)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull);
	return World ? World->GetSubsystem<UVerseGoreSubsystem>() : nullptr;
}

bool UVerseGoreSubsystem::ProcessCanShowGore()
{
	return !IsRunningDedicatedServer() && FApp::CanEverRender();
}

bool UVerseGoreSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	if (IsRunningDedicatedServer())
	{
		return false;   // a dedicated server never shows gore (combat-state.md 8)
	}
	const UWorld* World = Cast<UWorld>(Outer);
	if (!World || !(World->WorldType == EWorldType::Game || World->WorldType == EWorldType::PIE))
	{
		return false;
	}
	return Super::ShouldCreateSubsystem(Outer);
}

void UVerseGoreSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Collection.InitializeDependency<UVerseEventHub>();
	Super::Initialize(Collection);
	ReloadLevelFromSettings();
	UpdateActive();
}

void UVerseGoreSubsystem::Deinitialize()
{
	UnbindHub();
	Purge();
	if (AVerseGoreActor* Actor = GoreActor.Get())
	{
		Actor->Destroy();
	}
	GoreActor.Reset();
	SyntheticEvents.Reset();
	SyntheticCursor = 0;
	bActive = false;
	Super::Deinitialize();
}

void UVerseGoreSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	UpdateActive();
}

TStatId UVerseGoreSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseGoreSubsystem, STATGROUP_Tickables);
}

void UVerseGoreSubsystem::SetForceActive(bool bForce)
{
	bForceActive = bForce;
	UpdateActive();
}

void UVerseGoreSubsystem::UpdateActive()
{
	const UWorld* World = GetWorld();
	const bool bServerOnly = World && World->GetNetMode() == NM_DedicatedServer;
	const bool bWant = bForceActive || (ProcessCanShowGore() && !bServerOnly);
	if (bWant == bActive && bWant == bBound)
	{
		return;
	}
	bActive = bWant;
	if (bActive)
	{
		BindHub();
	}
	else
	{
		UnbindHub();
		Purge();
	}
}

void UVerseGoreSubsystem::BindHub()
{
	if (bBound)
	{
		return;
	}
	UVerseEventHub* EventHub = UVerseEventHub::Get(this);
	if (!EventHub)
	{
		UE_LOG(LogVerseGore, Warning, TEXT("No event hub in this world; gore listens to nothing"));
		return;
	}
	Hub = EventHub;
	HitHandle = EventHub->OnHit.AddUObject(this, &UVerseGoreSubsystem::HandleHit);
	DeathHandle = EventHub->OnDeath.AddUObject(this, &UVerseGoreSubsystem::HandleDeath);
	FinisherHandle = EventHub->OnFinisher.AddUObject(this, &UVerseGoreSubsystem::HandleFinisher);
	bBound = true;
}

void UVerseGoreSubsystem::UnbindHub()
{
	if (UVerseEventHub* EventHub = Hub.Get())
	{
		EventHub->OnHit.Remove(HitHandle);
		EventHub->OnDeath.Remove(DeathHandle);
		EventHub->OnFinisher.Remove(FinisherHandle);
	}
	HitHandle.Reset();
	DeathHandle.Reset();
	FinisherHandle.Reset();
	Hub.Reset();
	bBound = false;
}

// ---------------------------------------------------------------------------------------------
// Level

void UVerseGoreSubsystem::ReloadLevelFromSettings()
{
	FString Value;
	EVerseGoreLevel FromSettings = EVerseGoreLevel::Full;
	if (GConfig && GConfig->GetString(VerseGorePrivate::SettingsSection, TEXT("GoreLevel"), Value, GGameUserSettingsIni))
	{
		FromSettings = Value.TrimStartAndEnd().Equals(TEXT("Reduced"), ESearchCase::IgnoreCase) ? EVerseGoreLevel::Reduced : EVerseGoreLevel::Full;
	}
	SetGoreLevel(FromSettings);
}

void UVerseGoreSubsystem::SetGoreLevel(EVerseGoreLevel NewLevel)
{
	if (NewLevel == Level)
	{
		return;
	}
	Level = NewLevel;
	UE_LOG(LogVerseGore, Log, TEXT("Gore level %s"), Level == EVerseGoreLevel::Full ? TEXT("Full") : TEXT("Reduced"));
	if (Level == EVerseGoreLevel::Reduced)
	{
		Purge();   // live switch purges existing gore (WP05.7)
	}
	else if (CutToBlack.bActive)
	{
		EndCutToBlack();
	}
}

void UVerseGoreSubsystem::Purge()
{
	for (UDecalComponent* Decal : SpatterRing)
	{
		if (IsValid(Decal))
		{
			Decal->DestroyComponent();
		}
	}
	SpatterRing.Reset();
	SpatterNext = 0;
	for (FPool& Pool : Pools)
	{
		if (UDecalComponent* Decal = Pool.Decal.Get())
		{
			Decal->DestroyComponent();
		}
	}
	Pools.Reset();
	DropletsSim.Reset();
	FlashesSim.Reset();
	if (AVerseGoreActor* Actor = GoreActor.Get())
	{
		Actor->Droplets->ClearInstances();
		Actor->Flashes->ClearInstances();
	}
	for (FWoundSet& Set : WoundSets)
	{
		Set.Wounds.Reset();
		Set.Next = 0;
		ApplyWounds(Set);
	}
	WoundSets.Reset();
	if (CutToBlack.bActive)
	{
		EndCutToBlack();
	}
	++Budget.Purges;
	RefreshBudgetLive();
}

// ---------------------------------------------------------------------------------------------
// Assets and the gore actor

void UVerseGoreSubsystem::LoadLook()
{
	if (bLookLoaded)
	{
		return;
	}
	bLookLoaded = true;
	using namespace VerseGorePrivate;
	for (const TCHAR* Path : SpatterMaterialPaths)
	{
		if (UMaterialInterface* Material = LoadOptional<UMaterialInterface>(Path))
		{
			SpatterMaterials.Add(Material);
		}
	}
	DripMaterial = LoadOptional<UMaterialInterface>(DripMaterialPath);
	PoolMaterial = LoadOptional<UMaterialInterface>(PoolMaterialPath);
	if (SpatterMaterials.Num() == 0 || !PoolMaterial)
	{
		UE_LOG(LogVerseGore, Warning, TEXT("Gore materials missing under /Game/Verse/Gore; gore is counted but not drawn"));
	}
	if (AVerseGoreActor* Actor = GoreActor.Get())
	{
		Actor->SetLook(LoadOptional<UStaticMesh>(DropletMeshPath), LoadOptional<UMaterialInterface>(DropletMaterialPath),
			LoadOptional<UMaterialInterface>(FlashMaterialPath));
	}
}

AVerseGoreActor* UVerseGoreSubsystem::EnsureGoreActor()
{
	if (AVerseGoreActor* Existing = GoreActor.Get())
	{
		return Existing;
	}
	UWorld* World = GetWorld();
	if (!World)
	{
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.Name = MakeUniqueObjectName(World->PersistentLevel, AVerseGoreActor::StaticClass(), TEXT("VerseGore"));
	Params.ObjectFlags |= RF_Transient;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AVerseGoreActor* Actor = World->SpawnActor<AVerseGoreActor>(AVerseGoreActor::StaticClass(), FTransform::Identity, Params);
	GoreActor = Actor;
	bLookLoaded = false;
	LoadLook();
	return Actor;
}

// ---------------------------------------------------------------------------------------------
// Victims

void UVerseGoreSubsystem::SetVictimResolver(FVerseGoreVictimResolver Resolver)
{
	VictimResolver = MoveTemp(Resolver);
}

USkeletalMeshComponent* UVerseGoreSubsystem::ResolveVictim(int32 PlayerId) const
{
	return VictimResolver ? VictimResolver(PlayerId) : DefaultResolve(PlayerId);
}

USkeletalMeshComponent* UVerseGoreSubsystem::DefaultResolve(int32 PlayerId) const
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return nullptr;
	}
	for (TActorIterator<APawn> It(World); It; ++It)
	{
		const APlayerState* PlayerState = It->GetPlayerState();
		if (PlayerState && PlayerState->GetPlayerId() == PlayerId)
		{
			return It->FindComponentByClass<USkeletalMeshComponent>();
		}
	}
	return nullptr;
}

FVector UVerseGoreSubsystem::BodyPoint(USkeletalMeshComponent* Mesh, FName Bone, const FVector& Fallback) const
{
	if (Mesh && !Bone.IsNone() && Mesh->DoesSocketExist(Bone))
	{
		return Mesh->GetSocketLocation(Bone);
	}
	return Mesh ? Mesh->GetComponentLocation() + FVector(0.0, 0.0, 40.0) : Fallback;
}

bool UVerseGoreSubsystem::BoneLocalToRefPose(const USkeletalMeshComponent* Mesh, FName Bone, const FVector& BoneLocal, FVector& OutRefPose)
{
	const USkinnedAsset* Asset = Mesh ? Mesh->GetSkinnedAsset() : nullptr;
	if (!Asset)
	{
		return false;
	}
	const FReferenceSkeleton& RefSkeleton = Asset->GetRefSkeleton();
	const int32 BoneIndex = RefSkeleton.FindBoneIndex(Bone);
	if (BoneIndex == INDEX_NONE)
	{
		return false;
	}
	const FTransform BoneRef = FAnimationRuntime::GetComponentSpaceTransformRefPose(RefSkeleton, BoneIndex);
	OutRefPose = BoneRef.TransformPosition(BoneLocal);
	return true;
}

// ---------------------------------------------------------------------------------------------
// Events

void UVerseGoreSubsystem::HandleHit(const FVerseHitEvent& Event)
{
	if (!bActive)
	{
		return;
	}
	const uint64 Start = FPlatformTime::Cycles64();
	++Budget.HitsHandled;

	const FVector Origin = Event.ImpactWorld;
	const FVector Direction = FVector(Event.Direction).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);

	if (Level == EVerseGoreLevel::Reduced || Event.bBlockedBySpawnProtection || Event.Damage <= 0.f)
	{
		SpawnFlash(Origin);
	}
	else
	{
		EnsureGoreActor();
		USkeletalMeshComponent* Mesh = ResolveVictim(Event.VictimId);
		const uint32 Seed = FVerseRng::Hash(uint32(Event.VictimId), uint32(Event.ShotCounter), uint32(Event.InstigatorId));
		const float Scale = FMath::Clamp(Event.Damage / 30.f, 0.5f, 2.f);
		SpawnBurst(Origin, Direction, FMath::RoundToInt32(FVerseGoreTuning::BaseDroplets(Event.Zone) * Scale), Seed);
		const int32 Traces = FVerseGoreTuning::SpatterTraces(Event.Zone) + (Event.bKillingBlow ? 1 : 0);
		SpawnSpatter(Origin, Direction, Traces, Seed, Mesh ? Mesh->GetOwner() : nullptr);
		if (Mesh && !Event.Bone.IsNone())
		{
			AddWound(Mesh, Event.Bone, Event.ImpactBoneLocal, Event.Damage);
		}
	}

	const double Ms = VerseGorePrivate::CyclesToMs(FPlatformTime::Cycles64() - Start);
	Budget.HitTotalMs += Ms;
	Budget.HitMaxMs = FMath::Max(Budget.HitMaxMs, Ms);
	Budget.HitMeanMs = Budget.HitTotalMs / FMath::Max(1, Budget.HitsHandled);
	RefreshBudgetLive();
}

void UVerseGoreSubsystem::HandleDeath(const FVerseDeathEvent& Event)
{
	if (!bActive)
	{
		return;
	}
	++Budget.DeathsHandled;
	if (Level == EVerseGoreLevel::Reduced)
	{
		return;
	}
	USkeletalMeshComponent* Mesh = ResolveVictim(Event.VictimId);
	if (!Mesh)
	{
		return;   // nowhere to put a pool
	}
	StartPool(Event.VictimId, BodyPoint(Mesh, TEXT("Hips"), Mesh->GetComponentLocation()), Mesh->GetOwner());

	// The body comes back clean after respawn.
	const float Delay = FMath::Max(0.f, Event.RespawnAt - Event.ServerTime);
	if (Delay > 0.f)
	{
		TWeakObjectPtr<USkeletalMeshComponent> WeakMesh = Mesh;
		const double ClearAt = GoreTime + Delay;
		PendingWoundClears.Add({WeakMesh, ClearAt});
	}
	RefreshBudgetLive();
}

void UVerseGoreSubsystem::HandleFinisher(const FVerseFinisherEvent& Event)
{
	if (!bActive)
	{
		return;
	}
	++Budget.FinisherPhasesHandled;

	if (Level == EVerseGoreLevel::Reduced)
	{
		switch (Event.Phase)
		{
		case EVerseFinisherPhase::Takedown:
			StartCutToBlack(Event);
			break;
		case EVerseFinisherPhase::Recover:
		case EVerseFinisherPhase::Aborted:
			EndCutToBlack();
			break;
		default:
			break;
		}
		return;
	}

	USkeletalMeshComponent* Mesh = ResolveVictim(Event.VictimId);
	const FVector Fallback = Event.WarpTarget.GetLocation() + Event.WarpTarget.GetRotation().GetForwardVector() * 60.0 + FVector(0.0, 0.0, 30.0);
	const FVector Neck = BodyPoint(Mesh, TEXT("Neck"), Fallback);
	const FVector Across = Event.WarpTarget.GetRotation().GetRightVector();
	const uint32 Seed = FVerseRng::Hash(uint32(Event.AttackerId), uint32(Event.VictimId), uint32(Event.Phase) + 0x51u);

	switch (Event.Phase)
	{
	case EVerseFinisherPhase::Takedown:
		EnsureGoreActor();
		SpawnBurst(Neck, (Across + FVector(0.0, 0.0, 0.4)).GetSafeNormal(), 10, Seed);
		break;
	case EVerseFinisherPhase::Kill:
		EnsureGoreActor();
		SpawnBurst(Neck, (Across + FVector(0.0, 0.0, 0.2)).GetSafeNormal(), 64, Seed);
		SpawnSpatter(Neck, (Across + FVector(0.0, 0.0, -0.8)).GetSafeNormal(), 4, Seed, Mesh ? Mesh->GetOwner() : nullptr);
		if (Mesh)
		{
			AddWound(Mesh, TEXT("Neck"), FVector(0.0, 5.0, 0.0), 80.f);
			StartPool(Event.VictimId, Neck, Mesh->GetOwner());
		}
		break;
	default:
		break;
	}
	RefreshBudgetLive();
}

// ---------------------------------------------------------------------------------------------
// Bursts, spatter, flashes

void UVerseGoreSubsystem::SpawnBurst(const FVector& Origin, const FVector& Direction, int32 Count, uint32 Seed)
{
	if (Count <= 0)
	{
		return;
	}
	FVerseRng Rng(Seed, 1, EVerseRngSalt::None);
	const int32 BackSpray = FMath::RoundToInt32(Count * Tuning.DropletBackSprayFraction);
	for (int32 Index = 0; Index < Count; ++Index)
	{
		if (DropletsSim.Num() >= Tuning.MaxDroplets)
		{
			DropletsSim.RemoveAt(0, 1, EAllowShrinking::No);   // oldest first
		}
		const bool bBack = Index < BackSpray;
		const FVector Axis = bBack ? -Direction : Direction;
		const FVector Dir = Rng.ConeDirection(Axis, bBack ? 40.0 : 22.0);
		FDroplet Droplet;
		Droplet.Position = Origin;
		Droplet.Velocity = Dir * Tuning.DropletSpeedCm * Rng.Range(bBack ? 0.25 : 0.5, bBack ? 0.6 : 1.15);
		Droplet.Life = Tuning.DropletLifeSeconds * float(Rng.Range(0.6, 1.2));
		Droplet.Size = Tuning.DropletSizeCm * float(Rng.Range(0.5, 1.4));
		DropletsSim.Add(Droplet);
		++Budget.DropletsSpawned;
	}
}

void UVerseGoreSubsystem::SpawnSpatter(const FVector& Origin, const FVector& Direction, int32 Traces, uint32 Seed, const AActor* Ignore)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseGoreSpatter), false);
	if (Ignore)
	{
		Params.AddIgnoredActor(Ignore);
	}
	if (const AVerseGoreActor* Actor = GoreActor.Get())
	{
		Params.AddIgnoredActor(Actor);
	}
	const float Range = FMath::Max(1.f, Tuning.SpatterRangeCm);
	for (int32 Index = 0; Index < Traces; ++Index)
	{
		FVerseRng Rng(Seed, 100 + Index, EVerseRngSalt::None);
		const FVector Dir = (Rng.ConeDirection(Direction, Tuning.SpatterConeDeg) + FVector(0.0, 0.0, -0.12)).GetSafeNormal();
		const FVector From = Origin + Dir * 4.0;
		FHitResult Hit;
		if (World->LineTraceSingleByChannel(Hit, From, Origin + Dir * Range, ECC_Visibility, Params))
		{
			const float Alpha = FMath::Clamp(float(Hit.Distance) / Range, 0.f, 1.f);
			const float Size = FMath::Lerp(Tuning.SpatterSizeNearCm, Tuning.SpatterSizeFarCm, Alpha) * float(Rng.Range(0.8, 1.2));
			PlaceSpatterDecal(Hit.ImpactPoint, Hit.ImpactNormal, Size, Rng.NextU32());
		}
	}

	// One drip onto the floor below the wound.
	FHitResult Floor;
	if (World->LineTraceSingleByChannel(Floor, Origin, Origin + FVector(0.0, 0.0, -Tuning.DripTraceCm) + Direction * 25.0, ECC_Visibility, Params))
	{
		PlaceSpatterDecal(Floor.ImpactPoint, Floor.ImpactNormal, -Tuning.DripSizeCm, Seed ^ 0xD219u);
	}
}

bool UVerseGoreSubsystem::PlaceSpatterDecal(const FVector& Location, const FVector& Normal, float Size, uint32 Seed)
{
	AVerseGoreActor* Actor = EnsureGoreActor();
	if (!Actor || Tuning.MaxSpatterDecals <= 0)
	{
		return false;
	}
	// A negative size marks a floor drip (its own material).
	const bool bDrip = Size < 0.f;
	const float Extent = FMath::Abs(Size);
	FVerseRng Rng(Seed, 7, EVerseRngSalt::None);
	UMaterialInterface* Material = bDrip && DripMaterial ? DripMaterial.Get()
		: (SpatterMaterials.Num() > 0 ? SpatterMaterials[Rng.RangeInt(0, SpatterMaterials.Num() - 1)].Get() : nullptr);

	UDecalComponent* Decal = nullptr;
	if (SpatterRing.Num() < Tuning.MaxSpatterDecals)
	{
		Decal = Actor->NewDecal(Material, FVector(Tuning.DecalDepthCm, Extent, Extent));
		SpatterRing.Add(Decal);
	}
	else
	{
		SpatterNext %= SpatterRing.Num();
		Decal = SpatterRing[SpatterNext];
		SpatterNext = (SpatterNext + 1) % SpatterRing.Num();
		++Budget.DecalsRecycled;
		if (!IsValid(Decal))
		{
			return false;
		}
		Decal->SetDecalMaterial(Material);
		Decal->DecalSize = FVector(Tuning.DecalDepthCm, Extent, Extent);
		Decal->MarkRenderStateDirty();
	}
	FRotator Rotation = (-Normal).Rotation();
	Rotation.Roll = float(Rng.Range(0.0, 360.0));
	Decal->SetWorldLocationAndRotation(Location, Rotation);
	Decal->SetDecalColor(FLinearColor(1.f, float(Rng.Range(0.7, 1.0)), 1.f, float(Rng.Range(0.85, 1.0))));
	Decal->SetSortOrder(1);
	++Budget.DecalsSpawned;
	return true;
}

void UVerseGoreSubsystem::SpawnFlash(const FVector& Location)
{
	if (Tuning.MaxFlashes <= 0)
	{
		return;
	}
	EnsureGoreActor();
	if (FlashesSim.Num() >= Tuning.MaxFlashes)
	{
		FlashesSim.RemoveAt(0, 1, EAllowShrinking::No);
	}
	FlashesSim.Add({Location, 0.f});
	++Budget.FlashesSpawned;
}

// ---------------------------------------------------------------------------------------------
// Wounds

void UVerseGoreSubsystem::AddWound(USkeletalMeshComponent* Mesh, FName Bone, const FVector& BoneLocal, float Damage)
{
	FVector RefPose;
	if (!BoneLocalToRefPose(Mesh, Bone, BoneLocal, RefPose) || Tuning.MaxWoundsPerCharacter <= 0)
	{
		return;
	}
	FWoundSet* Set = WoundSets.FindByPredicate([Mesh](const FWoundSet& S) { return S.Mesh.Get() == Mesh; });
	if (!Set)
	{
		Set = &WoundSets.AddDefaulted_GetRef();
		Set->Mesh = Mesh;
	}
	const float Alpha = FMath::Clamp((Damage - 10.f) / 50.f, 0.f, 1.f);
	const FVector4f Wound(FVector3f(RefPose), FMath::Lerp(Tuning.WoundRadiusMinCm, Tuning.WoundRadiusMaxCm, Alpha));
	const int32 Max = FMath::Min(Tuning.MaxWoundsPerCharacter, 16);
	if (Set->Wounds.Num() < Max)
	{
		Set->Wounds.Add(Wound);
	}
	else
	{
		Set->Wounds[Set->Next] = Wound;   // oldest first
		Set->Next = (Set->Next + 1) % Max;
		++Budget.WoundsRecycled;
	}
	ApplyWounds(*Set);
}

void UVerseGoreSubsystem::ApplyWounds(FWoundSet& Set)
{
	USkeletalMeshComponent* Mesh = Set.Mesh.Get();
	if (!Mesh)
	{
		return;
	}
	if (!Set.bMaterialsResolved)
	{
		Set.bMaterialsResolved = true;
		for (int32 Slot = 0; Slot < Mesh->GetNumMaterials(); ++Slot)
		{
			UMaterialInterface* Material = Mesh->GetMaterial(Slot);
			float Unused = 0.f;
			if (Material && Material->GetScalarParameterValue(FHashedMaterialParameterInfo(VerseGoreParams::WoundCount), Unused))
			{
				Set.Materials.Add(Mesh->CreateDynamicMaterialInstance(Slot, Material));
			}
		}
	}
	const TArray<FVector4f> Ordered = GetWounds(Mesh);
	for (const TWeakObjectPtr<UMaterialInstanceDynamic>& Weak : Set.Materials)
	{
		UMaterialInstanceDynamic* Mid = Weak.Get();
		if (!Mid)
		{
			continue;
		}
		Mid->SetScalarParameterValue(VerseGoreParams::WoundCount, float(Ordered.Num()));
		for (int32 Index = 0; Index < 16; ++Index)
		{
			const FVector4f W = Ordered.IsValidIndex(Index) ? Ordered[Index] : FVector4f(0.f, 0.f, 0.f, 0.f);
			Mid->SetVectorParameterValue(VerseGoreParams::WoundSlot(Index), FLinearColor(W.X, W.Y, W.Z, W.W));
		}
	}
}

TArray<FVector4f> UVerseGoreSubsystem::GetWounds(const USkeletalMeshComponent* Mesh) const
{
	TArray<FVector4f> Result;
	const FWoundSet* Set = WoundSets.FindByPredicate([Mesh](const FWoundSet& S) { return S.Mesh.Get() == Mesh; });
	if (!Set)
	{
		return Result;
	}
	const int32 Num = Set->Wounds.Num();
	const bool bFull = Num >= FMath::Min(Tuning.MaxWoundsPerCharacter, 16);
	for (int32 Index = 0; Index < Num; ++Index)
	{
		Result.Add(Set->Wounds[bFull ? (Set->Next + Index) % Num : Index]);
	}
	return Result;
}

// ---------------------------------------------------------------------------------------------
// Pools

void UVerseGoreSubsystem::StartPool(int32 VictimId, const FVector& BodyLocation, const AActor* Ignore)
{
	UWorld* World = GetWorld();
	AVerseGoreActor* Actor = EnsureGoreActor();
	if (!World || !Actor || Tuning.MaxPools <= 0)
	{
		return;
	}
	for (const FPool& Pool : Pools)
	{
		if (Pool.VictimId == VictimId && GoreTime - Pool.StartTime < VerseGorePrivate::PoolDedupeSeconds)
		{
			return;
		}
	}
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseGorePool), false);
	if (Ignore)
	{
		Params.AddIgnoredActor(Ignore);
	}
	Params.AddIgnoredActor(Actor);
	FHitResult Floor;
	if (!World->LineTraceSingleByChannel(Floor, BodyLocation + FVector(0.0, 0.0, 20.0), BodyLocation - FVector(0.0, 0.0, Tuning.PoolTraceCm), ECC_Visibility, Params))
	{
		return;
	}

	if (Pools.Num() >= Tuning.MaxPools)
	{
		if (UDecalComponent* Oldest = Pools[0].Decal.Get())
		{
			Oldest->DestroyComponent();
		}
		Pools.RemoveAt(0);
		++Budget.PoolsRecycled;
	}
	FPool Pool;
	Pool.VictimId = VictimId;
	Pool.StartTime = GoreTime;
	Pool.Radius = Tuning.PoolRadiusCm;
	UDecalComponent* Decal = Actor->NewDecal(PoolMaterial, FVector(Tuning.DecalDepthCm, Pool.Radius, Pool.Radius));
	FRotator Rotation = (-Floor.ImpactNormal).Rotation();
	Rotation.Roll = float(FVerseRng(uint64(VictimId), uint64(Budget.DeathsHandled), EVerseRngSalt::None).Range(0.0, 360.0));
	Decal->SetWorldLocationAndRotation(Floor.ImpactPoint, Rotation);
	Decal->SetWorldScale3D(FVector(1.0, Tuning.PoolStartFraction, Tuning.PoolStartFraction));
	Decal->SetSortOrder(0);
	Pool.Decal = Decal;
	Pools.Add(Pool);
}

void UVerseGoreSubsystem::UpdatePools()
{
	for (int32 Index = Pools.Num() - 1; Index >= 0; --Index)
	{
		UDecalComponent* Decal = Pools[Index].Decal.Get();
		if (!Decal)
		{
			Pools.RemoveAt(Index);
			continue;
		}
		const float Alpha = Tuning.PoolGrowSeconds > 0.f ? float((GoreTime - Pools[Index].StartTime) / Tuning.PoolGrowSeconds) : 1.f;
		if (Alpha > 1.05f && Decal->GetComponentScale().Y >= 1.0)
		{
			continue;
		}
		const float Fraction = FMath::Lerp(Tuning.PoolStartFraction, 1.f, VerseGorePrivate::SmoothGrowth(Alpha));
		Decal->SetWorldScale3D(FVector(1.0, Fraction, Fraction));
	}
}

TArray<UDecalComponent*> UVerseGoreSubsystem::GetSpatterDecals() const
{
	TArray<UDecalComponent*> Result;
	const int32 Num = SpatterRing.Num();
	const bool bFull = Num >= Tuning.MaxSpatterDecals && Num > 0;
	for (int32 Index = 0; Index < Num; ++Index)
	{
		UDecalComponent* Decal = SpatterRing[bFull ? (SpatterNext + Index) % Num : Index];
		if (IsValid(Decal))
		{
			Result.Add(Decal);
		}
	}
	return Result;
}

TArray<UDecalComponent*> UVerseGoreSubsystem::GetPoolDecals() const
{
	TArray<UDecalComponent*> Result;
	for (const FPool& Pool : Pools)
	{
		if (UDecalComponent* Decal = Pool.Decal.Get())
		{
			Result.Add(Decal);
		}
	}
	return Result;
}

// ---------------------------------------------------------------------------------------------
// Time

void UVerseGoreSubsystem::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	if (bActive)
	{
		AdvanceTime(DeltaTime);
	}
}

void UVerseGoreSubsystem::AdvanceTime(float DeltaSeconds)
{
	const uint64 Start = FPlatformTime::Cycles64();
	const float Dt = FMath::Max(0.f, DeltaSeconds);
	GoreTime += Dt;

	// Synthetic playback goes through the hub, the same path Combat's events take.
	if (SyntheticCursor < SyntheticEvents.Num())
	{
		UVerseEventHub* EventHub = UVerseEventHub::Get(this);
		while (SyntheticCursor < SyntheticEvents.Num() && SyntheticEvents[SyntheticCursor].Time <= GoreTime - SyntheticStart + UE_KINDA_SMALL_NUMBER)
		{
			const FVerseGoreSyntheticEvent Event = SyntheticEvents[SyntheticCursor++];
			if (!EventHub)
			{
				continue;
			}
			switch (Event.Type)
			{
			case FVerseGoreSyntheticEvent::EType::Hit: EventHub->OnHit.Broadcast(Event.Hit); break;
			case FVerseGoreSyntheticEvent::EType::Death: EventHub->OnDeath.Broadcast(Event.Death); break;
			case FVerseGoreSyntheticEvent::EType::Finisher: EventHub->OnFinisher.Broadcast(Event.Finisher); break;
			}
		}
	}

	UpdateDroplets(Dt);
	UpdateFlashes(Dt);
	UpdatePools();

	for (int32 Index = PendingWoundClears.Num() - 1; Index >= 0; --Index)
	{
		if (GoreTime < PendingWoundClears[Index].Value)
		{
			continue;
		}
		const TWeakObjectPtr<USkeletalMeshComponent> Mesh = PendingWoundClears[Index].Key;
		PendingWoundClears.RemoveAt(Index);
		for (int32 SetIndex = WoundSets.Num() - 1; SetIndex >= 0; --SetIndex)
		{
			if (WoundSets[SetIndex].Mesh == Mesh)
			{
				WoundSets[SetIndex].Wounds.Reset();
				WoundSets[SetIndex].Next = 0;
				ApplyWounds(WoundSets[SetIndex]);
				WoundSets.RemoveAt(SetIndex);
			}
		}
	}

	if (CutToBlack.bActive && GoreTime - CutToBlack.StartTime > Tuning.CutToBlackTimeoutSeconds)
	{
		UE_LOG(LogVerseGore, Warning, TEXT("Finisher cut to black ended by timeout (no Recover or Aborted)"));
		EndCutToBlack();
	}

	RefreshBudgetLive();
	const double Ms = VerseGorePrivate::CyclesToMs(FPlatformTime::Cycles64() - Start);
	++Budget.Ticks;
	Budget.TickTotalMs += Ms;
	Budget.TickMaxMs = FMath::Max(Budget.TickMaxMs, Ms);
	Budget.TickMeanMs = Budget.TickTotalMs / double(Budget.Ticks);
}

void UVerseGoreSubsystem::UpdateDroplets(float DeltaSeconds)
{
	AVerseGoreActor* Actor = GoreActor.Get();
	if (!Actor)
	{
		DropletsSim.Reset();
		return;
	}
	int32 Write = 0;
	for (int32 Read = 0; Read < DropletsSim.Num(); ++Read)
	{
		FDroplet D = DropletsSim[Read];
		D.Age += DeltaSeconds;
		if (D.Age >= D.Life)
		{
			continue;
		}
		D.Velocity.Z -= Tuning.GravityCm * DeltaSeconds;
		D.Velocity *= FMath::Max(0.f, 1.f - 1.6f * DeltaSeconds);   // air drag
		D.Position += D.Velocity * DeltaSeconds;
		DropletsSim[Write++] = D;
	}
	DropletsSim.SetNum(Write, EAllowShrinking::No);

	UInstancedStaticMeshComponent* Ism = Actor->Droplets;
	TArray<FTransform> Transforms;
	Transforms.Reserve(DropletsSim.Num());
	for (const FDroplet& D : DropletsSim)
	{
		const float Shrink = 1.f - FMath::Clamp(D.Age / FMath::Max(D.Life, 0.01f), 0.f, 1.f) * 0.6f;
		const FVector Stretch = D.Velocity.GetSafeNormal(UE_SMALL_NUMBER, FVector::UpVector);
		const float Speed = float(D.Velocity.Size());
		const float S = D.Size * Shrink / 50.f;   // the primitive sphere is 100 cm across
		Transforms.Emplace(Stretch.ToOrientationQuat(), D.Position, FVector(S * (1.f + Speed / 400.f), S, S));
	}
	const int32 Have = Ism->GetInstanceCount();
	if (Have > Transforms.Num())
	{
		TArray<int32> Remove;
		for (int32 Index = Have - 1; Index >= Transforms.Num(); --Index)
		{
			Remove.Add(Index);
		}
		Ism->RemoveInstances(Remove, true);
	}
	else if (Have < Transforms.Num())
	{
		TArray<FTransform> Add;
		Add.Init(FTransform::Identity, Transforms.Num() - Have);
		Ism->AddInstances(Add, false, true, false);
	}
	if (Transforms.Num() > 0)
	{
		Ism->BatchUpdateInstancesTransforms(0, Transforms, true, true, true);
	}
}

void UVerseGoreSubsystem::UpdateFlashes(float DeltaSeconds)
{
	AVerseGoreActor* Actor = GoreActor.Get();
	if (!Actor)
	{
		FlashesSim.Reset();
		return;
	}
	for (int32 Index = FlashesSim.Num() - 1; Index >= 0; --Index)
	{
		FlashesSim[Index].Age += DeltaSeconds;
		if (FlashesSim[Index].Age >= Tuning.FlashLifeSeconds)
		{
			FlashesSim.RemoveAt(Index, 1, EAllowShrinking::No);
		}
	}
	UInstancedStaticMeshComponent* Ism = Actor->Flashes;
	if (Ism->GetInstanceCount() != FlashesSim.Num())
	{
		Ism->ClearInstances();
		TArray<FTransform> Add;
		for (const FFlash& Flash : FlashesSim)
		{
			const float S = Tuning.FlashSizeCm / 100.f;
			Add.Emplace(FQuat::Identity, Flash.Position, FVector(S));
		}
		if (Add.Num() > 0)
		{
			Ism->AddInstances(Add, false, true, false);
		}
	}
}

// ---------------------------------------------------------------------------------------------
// Cut to black (Reduced finisher)

void UVerseGoreSubsystem::StartCutToBlack(const FVerseFinisherEvent& Event)
{
	if (CutToBlack.bActive)
	{
		return;
	}
	CutToBlack.bActive = true;
	CutToBlack.AttackerId = Event.AttackerId;
	CutToBlack.VictimId = Event.VictimId;
	CutToBlack.StartFrame = GFrameCounter;
	CutToBlack.EndFrame = 0;
	CutToBlack.StartTime = GoreTime;
	++CutToBlack.Count;
	SetCameraFade(true);
}

void UVerseGoreSubsystem::EndCutToBlack()
{
	if (!CutToBlack.bActive)
	{
		return;
	}
	CutToBlack.bActive = false;
	CutToBlack.EndFrame = GFrameCounter;
	SetCameraFade(false);
}

void UVerseGoreSubsystem::SetCameraFade(bool bBlack)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	for (FConstPlayerControllerIterator It = World->GetPlayerControllerIterator(); It; ++It)
	{
		APlayerController* Controller = It->Get();
		if (!Controller || !Controller->IsLocalController() || !Controller->PlayerCameraManager)
		{
			continue;
		}
		if (bBlack)
		{
			Controller->PlayerCameraManager->SetManualCameraFade(1.f, FLinearColor::Black, false);
		}
		else
		{
			Controller->PlayerCameraManager->StopCameraFade();
		}
	}
}

// ---------------------------------------------------------------------------------------------
// Synthetic playback

void UVerseGoreSubsystem::PlaySynthetic(const FVerseGoreSyntheticParams& Params)
{
	SyntheticEvents = FVerseGoreSyntheticStream::Build(Params);
	SyntheticCursor = 0;
	SyntheticStart = GoreTime;
}

void UVerseGoreSubsystem::StopSynthetic()
{
	SyntheticEvents.Reset();
	SyntheticCursor = 0;
}

// ---------------------------------------------------------------------------------------------
// Budget

void UVerseGoreSubsystem::RefreshBudgetLive()
{
	Budget.SpatterDecals = SpatterRing.Num();
	Budget.Pools = Pools.Num();
	Budget.Droplets = DropletsSim.Num();
	Budget.Flashes = FlashesSim.Num();
	Budget.WoundedCharacters = 0;
	Budget.MaxWoundsOnOneCharacter = 0;
	for (const FWoundSet& Set : WoundSets)
	{
		if (Set.Wounds.Num() > 0)
		{
			++Budget.WoundedCharacters;
			Budget.MaxWoundsOnOneCharacter = FMath::Max(Budget.MaxWoundsOnOneCharacter, Set.Wounds.Num());
		}
	}
	Budget.PeakSpatterDecals = FMath::Max(Budget.PeakSpatterDecals, Budget.SpatterDecals);
	Budget.PeakPools = FMath::Max(Budget.PeakPools, Budget.Pools);
	Budget.PeakDroplets = FMath::Max(Budget.PeakDroplets, Budget.Droplets);
	Budget.PeakWoundsOnOneCharacter = FMath::Max(Budget.PeakWoundsOnOneCharacter, Budget.MaxWoundsOnOneCharacter);
}

void UVerseGoreSubsystem::ResetBudget()
{
	Budget = FVerseGoreBudget();
	RefreshBudgetLive();
}

FString UVerseGoreSubsystem::BudgetJson() const
{
	const FVerseGoreBudget& B = Budget;
	return FString::Printf(
		TEXT("{\n")
		TEXT("  \"schema\": \"verse.gore.budget/1\",\n")
		TEXT("  \"level\": \"%s\",\n")
		TEXT("  \"active\": %s,\n")
		TEXT("  \"caps\": {\"spatter_decals\": %d, \"pools\": %d, \"wounds_per_character\": %d, \"droplets\": %d},\n")
		TEXT("  \"live\": {\"spatter_decals\": %d, \"pools\": %d, \"droplets\": %d, \"flashes\": %d, \"wounded_characters\": %d, \"max_wounds_on_one_character\": %d},\n")
		TEXT("  \"peak\": {\"spatter_decals\": %d, \"pools\": %d, \"droplets\": %d, \"wounds_on_one_character\": %d},\n")
		TEXT("  \"totals\": {\"hits\": %d, \"deaths\": %d, \"finisher_phases\": %d, \"decals_spawned\": %d, \"decals_recycled\": %d, \"pools_recycled\": %d, \"wounds_recycled\": %d, \"droplets_spawned\": %d, \"flashes_spawned\": %d, \"purges\": %d},\n")
		TEXT("  \"game_thread_ms\": {\"hit_mean\": %.5f, \"hit_max\": %.5f, \"tick_mean\": %.5f, \"tick_max\": %.5f, \"ticks\": %lld},\n")
		TEXT("  \"cut_to_black\": {\"count\": %d, \"active\": %s, \"start_frame\": %llu, \"end_frame\": %llu}\n")
		TEXT("}\n"),
		Level == EVerseGoreLevel::Full ? TEXT("full") : TEXT("reduced"), bActive ? TEXT("true") : TEXT("false"),
		Tuning.MaxSpatterDecals, Tuning.MaxPools, Tuning.MaxWoundsPerCharacter, Tuning.MaxDroplets,
		B.SpatterDecals, B.Pools, B.Droplets, B.Flashes, B.WoundedCharacters, B.MaxWoundsOnOneCharacter,
		B.PeakSpatterDecals, B.PeakPools, B.PeakDroplets, B.PeakWoundsOnOneCharacter,
		B.HitsHandled, B.DeathsHandled, B.FinisherPhasesHandled, B.DecalsSpawned, B.DecalsRecycled, B.PoolsRecycled,
		B.WoundsRecycled, B.DropletsSpawned, B.FlashesSpawned, B.Purges,
		B.HitMeanMs, B.HitMaxMs, B.TickMeanMs, B.TickMaxMs, B.Ticks,
		CutToBlack.Count, CutToBlack.bActive ? TEXT("true") : TEXT("false"), CutToBlack.StartFrame, CutToBlack.EndFrame);
}

bool UVerseGoreSubsystem::WriteBudgetJson(const FString& Path) const
{
	return FFileHelper::SaveStringToFile(BudgetJson(), *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

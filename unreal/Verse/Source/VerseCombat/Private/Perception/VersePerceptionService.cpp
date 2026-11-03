#include "Perception/VersePerceptionService.h"

#include "Components/SkeletalMeshComponent.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Character.h"
#include "GameFramework/Controller.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerState.h"
#include "Movement/VerseMovementQuery.h"
#include "Noise/VerseAudibilityTable.h"
#include "Perception/VersePlainSightQuery.h"
#include "Stats/Stats.h"

const FName UVersePerceptionService::SampleBones[8] = {
	TEXT("Head"),
	TEXT("Neck"),
	TEXT("Spine_03"),
	TEXT("Hips"),
	TEXT("UpperArm_L"),
	TEXT("UpperArm_R"),
	TEXT("Calf_L"),
	TEXT("Calf_R"),
};

const FName UVersePerceptionService::EyeBone(TEXT("Camera"));

namespace
{
	const IVerseMovementQuery* FindMovementQuery(const APawn& Pawn)
	{
		if (const IVerseMovementQuery* OnPawn = Cast<IVerseMovementQuery>(const_cast<APawn*>(&Pawn)))
		{
			return OnPawn;
		}
		TInlineComponentArray<UActorComponent*> Components(&Pawn);
		for (UActorComponent* Component : Components)
		{
			if (const IVerseMovementQuery* Query = Cast<IVerseMovementQuery>(Component))
			{
				return Query;
			}
		}
		return nullptr;
	}

	const USkeletalMeshComponent* FindMesh(const APawn& Pawn)
	{
		if (const ACharacter* Character = Cast<ACharacter>(&Pawn))
		{
			if (Character->GetMesh())
			{
				return Character->GetMesh();
			}
		}
		return Pawn.FindComponentByClass<USkeletalMeshComponent>();
	}

	bool BoneLocation(const USkeletalMeshComponent* Mesh, const FName& Bone, FVector& Out)
	{
		if (!Mesh || !Mesh->GetSkeletalMeshAsset() || Mesh->GetBoneIndex(Bone) == INDEX_NONE)
		{
			return false;
		}
		Out = Mesh->GetBoneLocation(Bone);
		return true;
	}

	EVerseStance StanceOf(const APawn& Pawn, const IVerseMovementQuery* Query)
	{
		if (Query)
		{
			return Query->GetStance();
		}
		const ACharacter* Character = Cast<ACharacter>(&Pawn);
		return Character && Character->bIsCrouched ? EVerseStance::Crouch : EVerseStance::Stand;
	}
}

UVersePerceptionService* UVersePerceptionService::Get(const UObject* WorldContextObject)
{
	const UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UVersePerceptionService>() : nullptr;
}

void UVersePerceptionService::Initialize(FSubsystemCollectionBase& Collection)
{
	Collection.InitializeDependency(UVerseEventHub::StaticClass());
	Super::Initialize(Collection);
	SetSightQuery(NewObject<UVersePlainSightQuery>(this));
	Audibility = NewObject<UVerseAudibilityTable>(this);
	BindHub();
}

void UVersePerceptionService::Deinitialize()
{
	UnbindHub();
	Registered.Reset();
	Super::Deinitialize();
}

bool UVersePerceptionService::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

TStatId UVersePerceptionService::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVersePerceptionService, STATGROUP_Tickables);
}

void UVersePerceptionService::BindHub()
{
	UVerseEventHub* HubPtr = UVerseEventHub::Get(this);
	if (!HubPtr)
	{
		return;
	}
	Hub = HubPtr;
	NoiseHandle = HubPtr->OnNoise.AddUObject(this, &UVersePerceptionService::HandleNoise);
	FireHandle = HubPtr->OnFire.AddUObject(this, &UVersePerceptionService::HandleFire);
	ReloadHandle = HubPtr->OnReload.AddUObject(this, &UVersePerceptionService::HandleReload);
	HitHandle = HubPtr->OnHit.AddUObject(this, &UVersePerceptionService::HandleHit);
	DeathHandle = HubPtr->OnDeath.AddUObject(this, &UVersePerceptionService::HandleDeath);
	ArenaHandle = HubPtr->OnArenaSwitch.AddUObject(this, &UVersePerceptionService::HandleArenaSwitch);
}

void UVersePerceptionService::UnbindHub()
{
	if (UVerseEventHub* HubPtr = Hub.Get())
	{
		HubPtr->OnNoise.Remove(NoiseHandle);
		HubPtr->OnFire.Remove(FireHandle);
		HubPtr->OnReload.Remove(ReloadHandle);
		HubPtr->OnHit.Remove(HitHandle);
		HubPtr->OnDeath.Remove(DeathHandle);
		HubPtr->OnArenaSwitch.Remove(ArenaHandle);
	}
	Hub.Reset();
}

int32 UVersePerceptionService::PlayerIdOf(const AController& Controller)
{
	return Controller.PlayerState ? Controller.PlayerState->GetPlayerId() : INDEX_NONE;
}

bool UVersePerceptionService::IsServer() const
{
	const UWorld* World = GetWorld();
	return World && World->GetNetMode() != NM_Client;
}

void UVersePerceptionService::RegisterObserver(AController* Observer, const FVersePerceptionProfile& Profile)
{
	if (!Observer)
	{
		return;
	}
	UnregisterObserver(Observer);
	FRegistered& Entry = Registered.AddDefaulted_GetRef();
	Entry.Controller = Observer;
	Entry.PlayerId = PlayerIdOf(*Observer);
	Model.AddObserver(Entry.PlayerId, Profile);
}

void UVersePerceptionService::UnregisterObserver(AController* Observer)
{
	for (int32 Index = Registered.Num() - 1; Index >= 0; --Index)
	{
		if (Registered[Index].Controller.Get() == Observer || !Registered[Index].Controller.IsValid())
		{
			Model.RemoveObserver(Registered[Index].PlayerId);
			Registered.RemoveAt(Index);
		}
	}
}

bool UVersePerceptionService::IsRegistered(const AController* Observer) const
{
	return Registered.ContainsByPredicate([Observer](const FRegistered& Entry) { return Entry.Controller.Get() == Observer; });
}

void UVersePerceptionService::SetSightQuery(TScriptInterface<IVersePenetrationQuery> Query)
{
	SightQueryObject = Query.GetObject();
	SightQuery = Query.GetInterface();
}

void UVersePerceptionService::SetAudibilityTable(const UVerseAudibilityTable* Table)
{
	if (Table)
	{
		Audibility = Table;
	}
}

void UVersePerceptionService::SetVisibilityFactorProvider(TFunction<float(const FVector&)> Provider)
{
	VisibilityProvider = MoveTemp(Provider);
}

void UVersePerceptionService::SetLevelBands(float InMidMinZCm, float InUpperMinZCm)
{
	MidMinZCm = InMidMinZCm;
	UpperMinZCm = InUpperMinZCm;
}

void UVersePerceptionService::SetSelfPerceptFiller(TFunction<void(const APawn&, FVerseSelfPercept&)> Filler)
{
	SelfFiller = MoveTemp(Filler);
}

void UVersePerceptionService::SetBodyFiller(TFunction<void(const APawn&, FVersePerceptionBody&)> Filler)
{
	BodyFiller = MoveTemp(Filler);
}

void UVersePerceptionService::HandleReload(const FVerseReloadEvent& Event)
{
	Model.OnReload(Event);
}

void UVersePerceptionService::HandleNoise(const FVerseNoiseEvent& Event)
{
	Model.OnNoise(Event);
}

void UVersePerceptionService::HandleFire(const FVerseFireEvent& Event)
{
	Model.OnFire(Event);
}

void UVersePerceptionService::HandleHit(const FVerseHitEvent& Event)
{
	Model.OnHit(Event);
}

void UVersePerceptionService::HandleDeath(const FVerseDeathEvent& Event)
{
	TOptional<FVersePerceptionBody> Killer;
	if (const UWorld* World = GetWorld())
	{
		for (TActorIterator<APawn> It(World); It; ++It)
		{
			const APlayerState* State = It->GetPlayerState();
			if (State && State->GetPlayerId() == Event.KillerId)
			{
				Killer = MakeBody(**It, Event.KillerId);
				break;
			}
		}
	}
	Model.OnDeath(Event, Killer.GetPtrOrNull());
}

void UVersePerceptionService::HandleArenaSwitch(const FVerseArenaSwitchEvent& Event)
{
	Model.ResetEvents();
}

FVersePerceptionBody UVersePerceptionService::MakeBody(const APawn& Pawn, int32 PlayerId)
{
	FVersePerceptionBody Body;
	Body.PlayerId = PlayerId;
	const IVerseMovementQuery* Query = FindMovementQuery(Pawn);
	const USkeletalMeshComponent* Mesh = FindMesh(Pawn);

	Body.Velocity = Pawn.GetVelocity();
	Body.FacingYawDeg = float(Pawn.GetActorRotation().Yaw);
	const FRotator Aim = Pawn.GetBaseAimRotation();
	Body.FacingPitchDeg = float(FRotator::NormalizeAxis(Aim.Pitch));
	Body.Stance = StanceOf(Pawn, Query);
	Body.LeanQuantized = Query ? Query->GetLeanQuantized() : 0;
	if (const UVerseCombatStateComponent* Combat = Pawn.FindComponentByClass<UVerseCombatStateComponent>())
	{
		Body.bAlive = Combat->Phase != EVerseCombatPhase::Dead;
		Body.bSpawnProtected = Combat->bSpawnProtected;
	}

	if (!BoneLocation(Mesh, SampleBones[int32(EVerseSightSample::Pelvis)], Body.Pelvis))
	{
		Body.Pelvis = Pawn.GetActorLocation();
	}
	bool bAllBones = Mesh != nullptr;
	for (int32 Index = 0; Index < 8 && bAllBones; ++Index)
	{
		bAllBones = BoneLocation(Mesh, SampleBones[Index], Body.SamplePoints[Index]);
	}
	if (!bAllBones)
	{
		Body.SetSamplePointsFromStance();
	}

	if (!BoneLocation(Mesh, EyeBone, Body.Eye))
	{
		FRotator Unused;
		Pawn.GetActorEyesViewPoint(Body.Eye, Unused);
	}
	Body.View = Aim;
	return Body;
}

void UVersePerceptionService::GatherBodies(TArray<FVersePerceptionBody>& OutBodies) const
{
	OutBodies.Reset();
	const UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	for (TActorIterator<APawn> It(World); It; ++It)
	{
		const APlayerState* State = It->GetPlayerState();
		if (!State)
		{
			continue;
		}
		FVersePerceptionBody& Body = OutBodies.Add_GetRef(MakeBody(**It, State->GetPlayerId()));
		if (BodyFiller)
		{
			BodyFiller(**It, Body);
		}
	}
	// Actor iteration order is not part of the contract; sort so frames are deterministic (B5).
	OutBodies.Sort([](const FVersePerceptionBody& A, const FVersePerceptionBody& B) { return A.PlayerId < B.PlayerId; });
}

FVersePerceptionWorld UVersePerceptionService::MakeWorld() const
{
	FVersePerceptionWorld World;
	if (IVersePenetrationQuery* Query = SightQuery)
	{
		World.TestSight = [Query](const FVector& Eye, const FVector& Target) { return Query->TestSight(Eye, Target); };
	}
	World.VisibilityFactor = VisibilityProvider;
	World.Audibility = Audibility.Get();
	World.MidMinZCm = MidMinZCm;
	World.UpperMinZCm = UpperMinZCm;
	return World;
}

void UVersePerceptionService::Tick(float DeltaTime)
{
	if (IsServer())
	{
		StepPerception(DeltaTime);
	}
}

void UVersePerceptionService::StepPerception(float DeltaS)
{
	const UWorld* World = GetWorld();
	if (!World || Registered.Num() == 0)
	{
		return;
	}
	LastStepDeltaS = DeltaS;
	TArray<FVersePerceptionBody> Bodies;
	GatherBodies(Bodies);
	const FVersePerceptionWorld PerceptionWorld = MakeWorld();
	const uint32 NowMs = uint32(FMath::RoundToInt64(World->GetTimeSeconds() * 1000.0));

	// Copy: a delegate may unregister an observer.
	const TArray<FRegistered> Entries = Registered;
	for (const FRegistered& Entry : Entries)
	{
		AController* Controller = Entry.Controller.Get();
		if (!Controller)
		{
			continue;
		}
		FVersePerceptionObserverInput Input;
		if (const APawn* Pawn = Controller->GetPawn())
		{
			const FVersePerceptionBody* Own =
				Bodies.FindByPredicate([&Entry](const FVersePerceptionBody& Body) { return Body.PlayerId == Entry.PlayerId; });
			FVersePerceptionBody Body = Own ? *Own : MakeBody(*Pawn, Entry.PlayerId);
			if (!Own && BodyFiller)
			{
				BodyFiller(*Pawn, Body);
			}
			Input.Self.Location = Pawn->GetActorLocation();
			Input.Self.Velocity = Body.Velocity;
			Input.Self.EyeLocation = Body.Eye;
			Input.Self.ViewRotation = Controller->GetControlRotation();
			Input.Self.Stance = Body.Stance;
			Input.Self.bSpawnProtected = Body.bSpawnProtected;
			Input.Self.Phase = Body.bAlive ? EVerseCombatPhase::Alive : EVerseCombatPhase::Dead;
			if (const UVerseCombatStateComponent* Combat = Pawn->FindComponentByClass<UVerseCombatStateComponent>())
			{
				Input.Self.Phase = Combat->Phase;
			}
			Input.bAds = Body.bAds;
			Input.AdsFovDeg = Body.AdsFovDeg;
			if (SelfFiller)
			{
				SelfFiller(*Pawn, Input.Self);
			}
		}
		else
		{
			Input.Self.Phase = EVerseCombatPhase::Dead;
		}
		const FVersePerceptFrame Frame = Model.BuildFrame(Entry.PlayerId, Input, Bodies, PerceptionWorld, NowMs, DeltaS);
		OnPerceptFrame.Broadcast(Controller, Frame);
	}
}

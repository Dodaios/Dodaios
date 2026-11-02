#include "Debris/VerseDebrisSubsystem.h"

#include "Components/PrimitiveComponent.h"
#include "Destruction/VersePenetrationTable.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "Misc/App.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VerseDestructionManager.h"
#include "VerseCollision.h"
#include "VerseLog.h"
#include "VerseRng.h"

namespace
{
	/** The engine's geometry collection actor, found by name so this module needs no plugin link. */
	UClass* GeometryCollectionActorClass()
	{
		static TWeakObjectPtr<UClass> Cached;
		if (!Cached.IsValid())
		{
			Cached = FindObject<UClass>(nullptr, TEXT("/Script/GeometryCollectionEngine.GeometryCollectionActor"));
		}
		return Cached.Get();
	}

	/** Calls UGeometryCollectionComponent::SetRestCollection through reflection. */
	bool SetRestCollection(UPrimitiveComponent& Component, UObject* Collection)
	{
		UFunction* Function = Component.FindFunction(TEXT("SetRestCollection"));
		if (!Function)
		{
			return false;
		}
		uint8* Params = static_cast<uint8*>(FMemory_Alloca(Function->ParmsSize));
		FMemory::Memzero(Params, Function->ParmsSize);
		for (TFieldIterator<FProperty> It(Function); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
		{
			if (FObjectPropertyBase* Object = CastField<FObjectPropertyBase>(*It))
			{
				Object->SetObjectPropertyValue_InContainer(Params, Collection);
			}
			else if (FBoolProperty* Flag = CastField<FBoolProperty>(*It))
			{
				Flag->SetPropertyValue_InContainer(Params, true);
			}
		}
		Component.ProcessEvent(Function, Params);
		return true;
	}
}

bool UVerseDebrisSubsystem::ShouldSpawnDebris(const UWorld& World)
{
	return World.GetNetMode() != NM_DedicatedServer && FApp::CanEverRender() && !IsRunningDedicatedServer();
}

bool UVerseDebrisSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return World && World->IsGameWorld() && Super::ShouldCreateSubsystem(Outer);
}

void UVerseDebrisSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	bEnabled = ShouldSpawnDebris(InWorld);
	if (UVerseEventHub* Hub = UVerseEventHub::Get(&InWorld))
	{
		FractureHandle = Hub->OnFracture.AddUObject(this, &UVerseDebrisSubsystem::HandleFracture);
	}
}

void UVerseDebrisSubsystem::Deinitialize()
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(GetWorld()))
	{
		Hub->OnFracture.Remove(FractureHandle);
	}
	for (const int32 Id : Budget.PurgeAll())
	{
		DestroyBurst(Id);
	}
	Super::Deinitialize();
}

void UVerseDebrisSubsystem::SetLowPreset(bool bLow)
{
	Budget = FVerseDebrisBudget(bLow ? FVerseDebrisBudget::FConfig::Low() : FVerseDebrisBudget::FConfig::High());
}

TStatId UVerseDebrisSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseDebrisSubsystem, STATGROUP_Tickables);
}

void UVerseDebrisSubsystem::HandleFracture(const FVerseFractureEvent& Event)
{
	if (!bEnabled)
	{
		return; // DR3: no debris on a dedicated server or without a renderer
	}
	const UWorld* World = GetWorld();
	const double NowS = World ? World->GetTimeSeconds() : 0.0;
	if (Event.Cause == EVerseFractureCause::Reset)
	{
		for (const int32 Id : Budget.PurgeAll())
		{
			DestroyBurst(Id);
		}
		return;
	}
	if (Event.Cause == EVerseFractureCause::Repair || Event.ToState == EVersePieceState::Repairing || Event.ToState == EVersePieceState::Intact)
	{
		return;
	}
	const AVerseDestructionManager* Manager = AVerseDestructionManager::Get(this);
	if (!Manager || !Manager->GetSim().IsValidPiece(Event.PieceIndex))
	{
		return;
	}
	const FVersePieceDef& Def = Manager->GetSim().GetDef(Event.PieceIndex);
	const FVersePenetrationRow* Row = GetDefault<UVersePenetrationTable>()->FindRow(uint8(Def.Material));
	FVerseDebrisBudget::FRequest Request;
	Request.PieceIndex = Event.PieceIndex;
	Request.Type = Row ? Row->DebrisType : EVerseDebrisType::SparksOnly;
	Request.ToState = Event.ToState;
	const FVerseDebrisBudget::FGrant Grant = Budget.Request(Request, NowS);
	for (const int32 Id : Grant.Removed)
	{
		DestroyBurst(Id);
	}
	for (const int32 Id : Grant.Evicted)
	{
		if (const TWeakObjectPtr<AActor>* Actor = BurstActors.Find(Id))
		{
			if (UPrimitiveComponent* Root = Actor->IsValid() ? Cast<UPrimitiveComponent>((*Actor)->GetRootComponent()) : nullptr)
			{
				Root->PutAllRigidBodiesToSleep(); // fading: no longer simulated
			}
		}
	}
	if (Grant.BurstId != 0)
	{
		if (AActor* Actor = SpawnBurst(Event, Grant.Bodies))
		{
			BurstActors.Add(Grant.BurstId, Actor);
			++SpawnedBursts;
		}
	}
	// Niagara shards, dust and sparks belong to the look of the class; WP06 art adds the systems (NS_*).
}

AActor* UVerseDebrisSubsystem::SpawnBurst(const FVerseFractureEvent& Event, int32 Bodies)
{
	UWorld* World = GetWorld();
	const AVerseDestructionManager* Manager = AVerseDestructionManager::Get(this);
	AVerseDestructible* Piece = Manager ? Manager->GetPieceActor(Event.PieceIndex) : nullptr;
	UClass* ActorClass = GeometryCollectionActorClass();
	if (!World || !Piece || !ActorClass || Piece->GeometryCollection.IsNull())
	{
		return nullptr;
	}
	UObject* Collection = Piece->GeometryCollection.LoadSynchronous();
	if (!Collection)
	{
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Params.ObjectFlags |= RF_Transient;
	AActor* Actor = World->SpawnActor<AActor>(ActorClass, Piece->GetActorTransform(), Params);
	UPrimitiveComponent* Root = Actor ? Cast<UPrimitiveComponent>(Actor->GetRootComponent()) : nullptr;
	if (!Root || !SetRestCollection(*Root, Collection))
	{
		if (Actor)
		{
			Actor->Destroy();
		}
		return nullptr;
	}
	Root->SetCollisionProfileName(VerseCollision::Profile::Debris);
	Root->SetCanEverAffectNavigation(false);
	Root->SetIsReplicated(false); // GC replication off (architecture 4)
	Root->SetSimulatePhysics(true);
	// Same location, impulse and seed on every client; the crack pattern may still differ (architecture 4).
	FVerseRng Rng(Event.Seed);
	const FVector Local = FVector(Event.Location[0], Event.Location[1], Event.Location[2]) / 10.0;
	const FVector Origin = Piece->GetActorTransform().TransformPosition(Local) + Rng.UnitVector() * 2.0;
	const FVector Impulse = FVector(Event.Impulse[0], Event.Impulse[1], Event.Impulse[2]) * 0.1; // N s
	Root->AddRadialImpulse(Origin, FMath::Max<float>(Event.Radius, 10.f), float(Impulse.Size()) / FMath::Max(1, Bodies), RIF_Linear, true);
	return Actor;
}

void UVerseDebrisSubsystem::DestroyBurst(int32 BurstId)
{
	TWeakObjectPtr<AActor> Actor;
	if (BurstActors.RemoveAndCopyValue(BurstId, Actor) && Actor.IsValid())
	{
		Actor->Destroy();
	}
}

void UVerseDebrisSubsystem::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	const UWorld* World = GetWorld();
	if (!World || BurstActors.Num() == 0)
	{
		Budget.Tick(World ? World->GetTimeSeconds() : 0.0);
		return;
	}
	for (const FVerseDebrisBudget::FBurst& Burst : Budget.GetBursts())
	{
		if (Burst.bAsleep)
		{
			if (const TWeakObjectPtr<AActor>* Actor = BurstActors.Find(Burst.Id))
			{
				UPrimitiveComponent* Root = Actor->IsValid() ? Cast<UPrimitiveComponent>((*Actor)->GetRootComponent()) : nullptr;
				if (Root && Root->IsAnyRigidBodyAwake())
				{
					Root->PutAllRigidBodiesToSleep(); // sleeps after 3 s
				}
			}
		}
	}
	for (const int32 Id : Budget.Tick(World->GetTimeSeconds()))
	{
		DestroyBurst(Id);
	}
}

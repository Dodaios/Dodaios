#include "Debris/VerseDebrisSubsystem.h"

#include "Destruction/VersePenetrationTable.h"
#include "Engine/AssetManager.h"
#include "Engine/StreamableManager.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GeometryCollection/GeometryCollection.h"
#include "GeometryCollection/GeometryCollectionActor.h"
#include "GeometryCollection/GeometryCollectionComponent.h"
#include "GeometryCollection/GeometryCollectionObject.h"
#include "Misc/App.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VerseDestructionManager.h"
#include "VerseCollision.h"
#include "VerseLog.h"
#include "VerseRng.h"

bool UVerseDebrisSubsystem::ShouldSpawnDebris(const UWorld& World)
{
	return World.GetNetMode() != NM_DedicatedServer && FApp::CanEverRender() && !IsRunningDedicatedServer();
}

bool UVerseDebrisSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return World && World->IsGameWorld() && Super::ShouldCreateSubsystem(Outer);
}

int32 UVerseDebrisSubsystem::PickSet(TConstArrayView<int32> SetBodies, int32 Grant)
{
	int32 Best = INDEX_NONE;
	for (int32 Index = 0; Index < SetBodies.Num(); ++Index)
	{
		const int32 Bodies = SetBodies[Index];
		if (Bodies > 0 && Bodies <= Grant && (Best == INDEX_NONE || Bodies > SetBodies[Best]))
		{
			Best = Index;
		}
	}
	return Best;
}

int32 UVerseDebrisSubsystem::CountBodies(const UGeometryCollection& Collection)
{
	return Collection.NumElements(FGeometryCollection::GeometryGroup);
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
		ReleaseBurst(Id);
	}
	for (AGeometryCollectionActor* Actor : Pool)
	{
		if (IsValid(Actor))
		{
			Actor->Destroy();
		}
	}
	Pool.Reset();
	PoolSize = 0;
	for (const TSharedPtr<FStreamableHandle>& Handle : Preloads)
	{
		if (Handle.IsValid())
		{
			Handle->CancelHandle();
		}
	}
	Preloads.Reset();
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

void UVerseDebrisSubsystem::PreloadPiece(const AVerseDestructible& Piece)
{
	const UWorld* World = GetWorld();
	if (!World || !ShouldSpawnDebris(*World) || Piece.DebrisSets.Num() == 0)
	{
		return; // servers and headless runs never load debris
	}
	TArray<FSoftObjectPath> Paths;
	for (const FVersePieceDebrisSet& Set : Piece.DebrisSets)
	{
		if (!Set.Collection.IsNull() && !Set.Collection.IsValid())
		{
			Paths.AddUnique(Set.Collection.ToSoftObjectPath());
		}
	}
	if (Paths.Num() > 0)
	{
		Preloads.Add(UAssetManager::GetStreamableManager().RequestAsyncLoad(MoveTemp(Paths)));
	}
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
			ReleaseBurst(Id);
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
		ReleaseBurst(Id);
	}
	for (const int32 Id : Grant.Evicted)
	{
		if (const TWeakObjectPtr<AGeometryCollectionActor>* Actor = BurstActors.Find(Id))
		{
			if (UGeometryCollectionComponent* Component = Actor->IsValid() ? (*Actor)->GetGeometryCollectionComponent() : nullptr)
			{
				Component->PutAllRigidBodiesToSleep(); // fading: no longer simulated
			}
		}
	}
	if (Grant.BurstId != 0)
	{
		const int32 Real = SpawnBurst(Grant.BurstId, Event, Grant.Bodies);
		// The budget now counts the bodies the component really simulates (0 frees the reservation).
		Budget.Commit(Grant.BurstId, Real);
		SpawnedBursts += Real > 0 ? 1 : 0;
	}
	// Niagara shards, dust and sparks belong to the look of the class (NS_*, not authored yet).
}

AGeometryCollectionActor* UVerseDebrisSubsystem::AcquireActor()
{
	while (Pool.Num() > 0)
	{
		AGeometryCollectionActor* Actor = Pool.Pop(EAllowShrinking::No);
		if (IsValid(Actor))
		{
			return Actor;
		}
		--PoolSize;
	}
	UWorld* World = GetWorld();
	if (!World || PoolSize >= Budget.GetConfig().MaxGeometryCollectionActors)
	{
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Params.ObjectFlags |= RF_Transient;
	AGeometryCollectionActor* Actor = World->SpawnActor<AGeometryCollectionActor>(AGeometryCollectionActor::StaticClass(), FTransform::Identity, Params);
	if (Actor)
	{
		++PoolSize;
	}
	return Actor;
}

int32 UVerseDebrisSubsystem::SpawnBurst(int32 BurstId, const FVerseFractureEvent& Event, int32 Grant)
{
	const AVerseDestructionManager* Manager = AVerseDestructionManager::Get(this);
	AVerseDestructible* Piece = Manager ? Manager->GetPieceActor(Event.PieceIndex) : nullptr;
	if (!Piece)
	{
		return 0;
	}
	// The authored set for this state with the most chunks that fit the grant. Only loaded sets
	// count: a set still streaming in is skipped rather than loaded on the game thread.
	const TArray<const FVersePieceDebrisSet*> Sets = Piece->FindDebrisSets(Event.ToState, Event.Variant);
	TArray<int32> Bodies;
	TArray<UGeometryCollection*> Loaded;
	for (const FVersePieceDebrisSet* Set : Sets)
	{
		UGeometryCollection* Collection = Set->Collection.Get();
		Loaded.Add(Collection);
		Bodies.Add(Collection ? CountBodies(*Collection) : 0);
	}
	const int32 Pick = PickSet(Bodies, Grant);
	if (Pick == INDEX_NONE)
	{
		return 0;
	}
	AGeometryCollectionActor* Actor = AcquireActor();
	UGeometryCollectionComponent* Component = Actor ? Actor->GetGeometryCollectionComponent() : nullptr;
	if (!Component)
	{
		if (Actor)
		{
			Pool.Add(Actor);
		}
		return 0;
	}
	Actor->SetActorTransform(Piece->GetActorTransform());
	Component->UnregisterComponent();
	Component->SetRestCollection(Loaded[Pick]);
	Component->SetCollisionProfileName(VerseCollision::Profile::Debris);
	Component->SetCanEverAffectNavigation(false);
	Component->SetIsReplicated(false); // GC replication off (architecture 4)
	Component->SetSimulatePhysics(true);
	Component->RegisterComponent();
	Actor->SetActorHiddenInGame(false);
	Actor->SetActorEnableCollision(true);
	const int32 Real = Component->GetRestCollection() ? CountBodies(*Component->GetRestCollection()) : 0;
	if (Real <= 0 || Real > Grant)
	{
		UE_LOG(LogVerseDestruction, Error, TEXT("debris set of piece %u has %d bodies, the grant is %d; not spawned"), Event.PieceIndex, Real, Grant);
		BurstActors.Add(BurstId, Actor);
		ReleaseBurst(BurstId);
		return 0;
	}
	// Same location, impulse and seed on every client; the crack pattern may still differ (architecture 4).
	FVerseRng Rng(Event.Seed);
	const FVector Local = FVector(Event.Location[0], Event.Location[1], Event.Location[2]) / 10.0;
	const FVector Origin = Piece->GetActorTransform().TransformPosition(Local) + Rng.UnitVector() * 2.0;
	const FVector Impulse = FVector(Event.Impulse[0], Event.Impulse[1], Event.Impulse[2]) * 0.1; // N s
	Component->AddRadialImpulse(Origin, FMath::Max<float>(Event.Radius, 10.f), float(Impulse.Size()) / float(Real), RIF_Linear, true);
	BurstActors.Add(BurstId, Actor);
	return Real;
}

void UVerseDebrisSubsystem::ReleaseBurst(int32 BurstId)
{
	TWeakObjectPtr<AGeometryCollectionActor> Actor;
	if (!BurstActors.RemoveAndCopyValue(BurstId, Actor) || !Actor.IsValid())
	{
		return;
	}
	// Back to the pool: hidden, no collision, not simulating.
	if (UGeometryCollectionComponent* Component = Actor->GetGeometryCollectionComponent())
	{
		Component->SetSimulatePhysics(false);
	}
	Actor->SetActorHiddenInGame(true);
	Actor->SetActorEnableCollision(false);
	Pool.Add(Actor.Get());
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
			if (const TWeakObjectPtr<AGeometryCollectionActor>* Actor = BurstActors.Find(Burst.Id))
			{
				UGeometryCollectionComponent* Component = Actor->IsValid() ? (*Actor)->GetGeometryCollectionComponent() : nullptr;
				if (Component && Component->IsAnyRigidBodyAwake())
				{
					Component->PutAllRigidBodiesToSleep(); // sleeps after 3 s
				}
			}
		}
	}
	for (const int32 Id : Budget.Tick(World->GetTimeSeconds()))
	{
		ReleaseBurst(Id);
	}
}

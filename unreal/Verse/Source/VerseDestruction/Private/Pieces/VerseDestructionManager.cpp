#include "Pieces/VerseDestructionManager.h"

#include "AI/NavigationSystemBase.h"
#include "Components/StaticMeshComponent.h"
#include "Destruction/VerseDestructionTuning.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "Net/UnrealNetwork.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VersePieceManifest.h"
#include "Repair/VerseRepairDrone.h"
#include "VerseLog.h"

AVerseDestructionManager::AVerseDestructionManager()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PrePhysics;
	bReplicates = true;
	bAlwaysRelevant = true;
	SetNetUpdateFrequency(30.f);
	DroneClass = AVerseRepairDrone::StaticClass();
	Pieces.Owner = this;
	DamageSink.Owner = this;
}

AVerseDestructionManager* AVerseDestructionManager::Get(const UObject* WorldContextObject)
{
	const UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	if (!World)
	{
		return nullptr;
	}
	for (TActorIterator<AVerseDestructionManager> It(World); It; ++It)
	{
		return *It;
	}
	return nullptr;
}

void AVerseDestructionManager::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	DOREPLIFETIME(AVerseDestructionManager, Pieces);
	DOREPLIFETIME(AVerseDestructionManager, Epoch);
}

uint32 AVerseDestructionManager::GetServerTimeMs() const
{
	const UWorld* World = GetWorld();
	return World ? uint32(FMath::Max(0.0, World->GetTimeSeconds()) * 1000.0) : 0u;
}

void AVerseDestructionManager::BeginPlay()
{
	Super::BeginPlay();
	Pieces.Owner = this;
	DamageSink.Owner = this;
	RegisterPieces();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		ArenaSwitchHandle = Hub->OnArenaSwitch.AddUObject(this, &AVerseDestructionManager::HandleArenaSwitch);
	}
	if (HasAuthority())
	{
		SpawnDrones();
	}
}

void AVerseDestructionManager::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnArenaSwitch.Remove(ArenaSwitchHandle);
	}
	for (AVerseRepairDrone* Drone : DroneActors)
	{
		if (IsValid(Drone))
		{
			Drone->Destroy();
		}
	}
	DroneActors.Reset();
	Super::EndPlay(EndPlayReason);
}

void AVerseDestructionManager::RegisterPieces()
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	TMap<FGuid, AVerseDestructible*> ByGuid;
	for (TActorIterator<AVerseDestructible> It(World); It; ++It)
	{
		AVerseDestructible* Piece = *It;
		if (!Piece->GetPieceGuid().IsValid())
		{
			UE_LOG(LogVerseDestruction, Error, TEXT("%s has no piece GUID; it stays out of the manifest"), *Piece->GetName());
			continue;
		}
		ByGuid.Add(Piece->GetPieceGuid(), Piece);
	}
	TArray<FGuid> Order;
	if (Manifest && Manifest->PieceGuids.Num() > 0)
	{
		Order = Manifest->PieceGuids;
	}
	else
	{
		ByGuid.GenerateKeyArray(Order);
		UVersePieceManifest::SortGuids(Order);
	}
	PieceActors.Reset();
	TArray<FVersePieceDef> Defs;
	for (const FGuid& Guid : Order)
	{
		AVerseDestructible* const* Found = ByGuid.Find(Guid);
		AVerseDestructible* Piece = Found ? *Found : nullptr;
		if (!Piece)
		{
			UE_LOG(LogVerseDestruction, Warning, TEXT("manifest piece %s is not in the world"), *Guid.ToString());
		}
		if (Piece)
		{
			Piece->SetPieceIndex(PieceActors.Num());
			Defs.Add(Piece->MakeDef());
		}
		else
		{
			// Keep the index stable: a missing piece is an inert slot.
			FVersePieceDef Missing;
			Missing.Guid = Guid;
			Missing.Material = EVersePenetrationMaterial::Concrete;
			Defs.Add(Missing);
		}
		PieceActors.Add(Piece);
	}
	const UVerseDestructionTuning* Asset = Tuning ? Tuning.Get() : GetDefault<UVerseDestructionTuning>();
	Sim.Init(MoveTemp(Defs), FVerseDestructionSimTuning::FromAsset(*Asset), DroneDocks, uint64(FractureSeed));
	if (HasAuthority())
	{
		Pieces.Items = Sim.GetItems();
		Pieces.MarkArrayDirty();
	}
	else
	{
		// Items that replicated before the pieces were registered.
		for (const FVersePieceItem& Item : Pieces.Items)
		{
			OnItemReplicated(Item, true);
		}
	}
	bRegistered = true;
}

void AVerseDestructionManager::SpawnDrones()
{
	UWorld* World = GetWorld();
	if (!World || !DroneClass)
	{
		return;
	}
	for (int32 Index = 0; Index < DroneDocks.Num(); ++Index)
	{
		FActorSpawnParameters Params;
		Params.Owner = this;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		AVerseRepairDrone* Drone = World->SpawnActor<AVerseRepairDrone>(DroneClass, DroneDocks[Index], FRotator::ZeroRotator, Params);
		if (Drone)
		{
			Drone->DroneIndex = Index;
			DroneActors.Add(Drone);
		}
	}
}

AVerseDestructible* AVerseDestructionManager::GetPieceActor(uint16 PieceIndex) const
{
	return PieceActors.IsValidIndex(PieceIndex) ? PieceActors[PieceIndex].Get() : nullptr;
}

const FVersePieceItem* AVerseDestructionManager::FindItem(uint16 PieceIndex) const
{
	if (Pieces.Items.IsValidIndex(PieceIndex) && Pieces.Items[PieceIndex].PieceIndex == PieceIndex)
	{
		return &Pieces.Items[PieceIndex]; // the server writes items in manifest order
	}
	return Pieces.Items.FindByPredicate([PieceIndex](const FVersePieceItem& Item) { return Item.PieceIndex == PieceIndex; });
}

void AVerseDestructionManager::ApplyPieceDamage(const FVersePieceDamage& Damage)
{
	if (!HasAuthority())
	{
		ensureMsgf(false, TEXT("ApplyPieceDamage on a client (DR1)"));
		return;
	}
	Sim.ApplyDamage(Damage, GetServerTimeMs());
	ServerStep(GetServerTimeMs());
}

void AVerseDestructionManager::ApplyHoleCap(uint16 PieceIndex, const FVector& LocalCentroidCm)
{
	if (!HasAuthority())
	{
		return;
	}
	Sim.ApplyHoleCap(PieceIndex, LocalCentroidCm, GetServerTimeMs());
	ServerStep(GetServerTimeMs());
}

void AVerseDestructionManager::ApplyDroneDamage(int32 DroneIndex, float Amount)
{
	if (!HasAuthority())
	{
		return;
	}
	Sim.ApplyDroneDamage(DroneIndex, Amount, GetServerTimeMs());
	ServerStep(GetServerTimeMs());
}

void AVerseDestructionManager::FullReset()
{
	if (!HasAuthority())
	{
		return;
	}
	Sim.FullReset(GetServerTimeMs());
	ServerStep(GetServerTimeMs());
}

void AVerseDestructionManager::HandleArenaSwitch(const FVerseArenaSwitchEvent& Event)
{
	// Arena on and arena off both reset, so the normal deck is always intact (destruction.md 11).
	if (bResetOnArenaSwitch && HasAuthority())
	{
		FullReset();
	}
}

bool AVerseDestructionManager::IsEncroached(const FBox& WorldBox) const
{
	const UWorld* World = GetWorld();
	if (!World || !WorldBox.IsValid)
	{
		return false;
	}
	FCollisionObjectQueryParams Objects;
	Objects.AddObjectTypesToQuery(ECC_Pawn);
	return World->OverlapAnyTestByObjectType(WorldBox.GetCenter(), FQuat::Identity, Objects, FCollisionShape::MakeBox(WorldBox.GetExtent()));
}

void AVerseDestructionManager::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (HasAuthority() && bRegistered)
	{
		const uint32 NowMs = GetServerTimeMs();
		Sim.Tick(NowMs, [this](const FBox& Box) { return IsEncroached(Box); });
		ServerStep(NowMs);
	}
}

void AVerseDestructionManager::ServerStep(uint32 NowMs)
{
	for (const uint16 Index : Sim.DrainDirtyItems())
	{
		if (!Pieces.Items.IsValidIndex(Index))
		{
			continue;
		}
		FVersePieceItem& Item = Pieces.Items[Index];
		const FVersePieceItem& Truth = Sim.GetItem(Index);
		// Copy the gameplay fields; keep the fast-array bookkeeping of the replicated item.
		Item.State = Truth.State;
		Item.HealthQ = Truth.HealthQ;
		Item.Variant = Truth.Variant;
		Item.RepairFrom = Truth.RepairFrom;
		Item.LastSeed = Truth.LastSeed;
		FMemory::Memcpy(Item.LastImpulse, Truth.LastImpulse, sizeof(Item.LastImpulse));
		FMemory::Memcpy(Item.LastLocation, Truth.LastLocation, sizeof(Item.LastLocation));
		Item.StateTimeMs = Truth.StateTimeMs;
		Item.Epoch = Truth.Epoch;
		Pieces.MarkItemDirty(Item);
		if (AVerseDestructible* Piece = GetPieceActor(Index))
		{
			Piece->ApplyPresentation(Item.State, Item.Variant, Item.RepairFrom);
		}
	}
	if (Epoch != Sim.GetEpoch())
	{
		Epoch = Sim.GetEpoch();
	}
	for (const FVersePendingFracture& Pending : Sim.DrainEvents())
	{
		PublishLocal(Pending.Event);
		if (Pending.bMulticast && GetNetMode() != NM_Standalone)
		{
			MulticastFracture(Pending.Event);
		}
	}
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		for (const FVerseNoiseEvent& Noise : Sim.DrainNoise())
		{
			Hub->OnNoise.Broadcast(Noise);
		}
	}
	else
	{
		Sim.DrainNoise();
	}
	ReleaseNavTiles();
	SyncDrones();
}

void AVerseDestructionManager::ReleaseNavTiles()
{
	// The generic navigation hook has no completion callback, so every server tick frees the
	// slots of the previous release: at most NavMaxTilesInFlight tiles are handed over per tick.
	FVerseNavDirtyQueue& Nav = Sim.GetNav();
	for (const FVerseNavDirtyQueue::FTile& Tile : Nav.Release(Nav.NumInFlight()))
	{
		AVerseDestructible* Piece = Tile.PieceIndex != INDEX_NONE ? GetPieceActor(uint16(Tile.PieceIndex)) : nullptr;
		UStaticMeshComponent* Proxy = Piece ? Piece->GetProxyComponent() : nullptr;
		if (Proxy && Proxy->IsRegistered())
		{
			// The proxy's own octree bounds stay its bounds; the tile (old and new proxy +50 cm) is the dirty area.
			const FBox Dirty = Tile.GetBox();
			FNavigationSystem::OnObjectBoundsChanged(*Proxy, Proxy->Bounds.GetBox(), MakeArrayView(&Dirty, 1));
		}
	}
}

void AVerseDestructionManager::SyncDrones()
{
	const TArray<FVerseDroneState>& Drones = Sim.GetDrones();
	for (AVerseRepairDrone* Drone : DroneActors)
	{
		if (IsValid(Drone) && Drones.IsValidIndex(Drone->DroneIndex))
		{
			const FVerseDroneState& State = Drones[Drone->DroneIndex];
			Drone->SyncFromSim(State.Location, uint8(State.Task), State.Generation, State.Hp);
		}
	}
}

void AVerseDestructionManager::PublishLocal(const FVerseFractureEvent& Event)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnFracture.Broadcast(Event);
	}
}

void AVerseDestructionManager::MulticastFracture_Implementation(const FVerseFractureEvent& Event)
{
	if (HasAuthority())
	{
		return; // the server published it when it happened
	}
	if (Event.Epoch < Epoch)
	{
		return; // events with an old epoch are dropped (destruction.md 4)
	}
	PublishLocal(Event);
}

void AVerseDestructionManager::OnRep_Epoch()
{
}

void AVerseDestructionManager::OnItemReplicated(const FVersePieceItem& Item, bool bInitial)
{
	// Late joiners and dropped events: the item is the truth; it never spawns debris.
	if (AVerseDestructible* Piece = GetPieceActor(Item.PieceIndex))
	{
		Piece->ApplyPresentation(Item.State, Item.Variant, Item.RepairFrom);
	}
}

void AVerseDestructionManager::ReceiveItemsForTest(TConstArrayView<FVersePieceItem> InItems, bool bInitial)
{
	for (const FVersePieceItem& Incoming : InItems)
	{
		FVersePieceItem* Existing = Pieces.Items.FindByPredicate([&Incoming](const FVersePieceItem& Item) { return Item.PieceIndex == Incoming.PieceIndex; });
		if (!Existing)
		{
			Existing = &Pieces.Items.Add_GetRef(Incoming);
		}
		else
		{
			*Existing = Incoming;
		}
		if (bInitial)
		{
			Existing->PostReplicatedAdd(Pieces);
		}
		else
		{
			Existing->PostReplicatedChange(Pieces);
		}
	}
}

EVersePieceState AVerseDestructionManager::GetPieceState(uint16 PieceIndex) const
{
	const FVersePieceItem* Item = FindItem(PieceIndex);
	return Item ? Item->State : EVersePieceState::Intact;
}

EVersePenetrationMaterial AVerseDestructionManager::GetPieceMaterial(uint16 PieceIndex) const
{
	return Sim.IsValidPiece(PieceIndex) ? Sim.GetDef(PieceIndex).Material : EVersePenetrationMaterial::Concrete;
}

FBox AVerseDestructionManager::GetPieceBounds(uint16 PieceIndex) const
{
	const FVersePieceItem* Item = FindItem(PieceIndex);
	if (!Item || !Sim.IsValidPiece(PieceIndex))
	{
		return FBox(ForceInit);
	}
	return Sim.GetDef(PieceIndex).GetWorldBounds(Item->GetProxyState(), Item->Variant);
}

TArray<uint16> AVerseDestructionManager::GetPiecesInBox(const FBox& WorldBox) const
{
	return Sim.GetPiecesInBox(WorldBox);
}

int32 FVersePieceItem::PackedBits()
{
	// PieceIndex 11 (<= 2,000), State 3, HealthQ 8, Variant 2 (<= 4), RepairFrom 3, Seed 32,
	// Impulse 3 x 16, Location 3 x 16, StateTimeMs 32, Epoch 16 (destruction.md 3.3).
	return 11 + 3 + 8 + 2 + 3 + 32 + 48 + 48 + 32 + 16;
}

void FVersePieceItem::PostReplicatedAdd(const FVersePieceItemArray& InArraySerializer)
{
	if (InArraySerializer.Owner)
	{
		InArraySerializer.Owner->OnItemReplicated(*this, true);
	}
}

void FVersePieceItem::PostReplicatedChange(const FVersePieceItemArray& InArraySerializer)
{
	if (InArraySerializer.Owner)
	{
		InArraySerializer.Owner->OnItemReplicated(*this, false);
	}
}

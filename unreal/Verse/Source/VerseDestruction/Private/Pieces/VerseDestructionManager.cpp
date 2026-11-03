#include "Pieces/VerseDestructionManager.h"

#include "AI/NavigationSystemBase.h"
#include "Components/StaticMeshComponent.h"
#include "Destruction/VerseDestructionTuning.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "Net/UnrealNetwork.h"
#include "Net/Core/PushModel/PushModel.h"
#include "NavigationSystem.h"
#include "UObject/CoreNet.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VersePieceManifest.h"
#include "Debris/VerseDebrisSubsystem.h"
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
	// Push model (destruction.md 3.3): the properties are only compared after a write marked them.
	FDoRepLifetimeParams Params;
	Params.bIsPushBased = true;
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseDestructionManager, Pieces, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseDestructionManager, Epoch, Params);
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

bool AVerseDestructionManager::IsMissingClientManifest() const
{
	const bool bNetworkedClient = !HasAuthority() && GetNetMode() != NM_Standalone;
	return bNetworkedClient && (!Manifest || Manifest->PieceGuids.Num() == 0);
}

void AVerseDestructionManager::RegisterPieces()
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	if (IsMissingClientManifest())
	{
		// Sorting only the GUIDs this client has loaded would shift PieceIndex against the server.
		UE_LOG(LogVerseDestruction, Error, TEXT("%s: a networked client needs DA_PieceManifest; destruction stays off here"), *GetName());
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
	SlotOfGuid.Reset();
	TArray<FVersePieceDef> Defs;
	for (const FGuid& Guid : Order)
	{
		AVerseDestructible* const* Found = ByGuid.Find(Guid);
		AVerseDestructible* Piece = Found ? *Found : nullptr;
		SlotOfGuid.Add(Guid, PieceActors.Num());
		if (Piece)
		{
			Piece->SetPieceIndex(PieceActors.Num());
			Defs.Add(Piece->MakeDef());
		}
		else
		{
			// Not loaded (yet): an inert slot keeps the index stable until the piece streams in.
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
		MARK_PROPERTY_DIRTY_FROM_NAME(AVerseDestructionManager, Pieces, this);
	}
	else
	{
		// Items that replicated before the pieces were registered.
		for (const FVersePieceItem& Item : Pieces.Items)
		{
			OnItemReplicated(Item, true);
		}
	}
	UVerseDebrisSubsystem* Debris = World->GetSubsystem<UVerseDebrisSubsystem>();
	for (AVerseDestructible* Piece : PieceActors)
	{
		if (Piece && Debris)
		{
			Debris->PreloadPiece(*Piece);
		}
	}
	bRegistered = true;
}

void AVerseDestructionManager::RegisterPiece(AVerseDestructible& Piece)
{
	if (!bRegistered)
	{
		return; // RegisterPieces at BeginPlay picks it up
	}
	const int32* Slot = SlotOfGuid.Find(Piece.GetPieceGuid());
	if (!Slot)
	{
		UE_LOG(LogVerseDestruction, Error, TEXT("%s (%s) is not in the manifest; it stays inert"), *Piece.GetName(), *Piece.GetPieceGuid().ToString());
		return;
	}
	if (PieceActors[*Slot] == &Piece)
	{
		return;
	}
	PieceActors[*Slot] = &Piece;
	Piece.SetPieceIndex(*Slot);
	Sim.SetDef(uint16(*Slot), Piece.MakeDef());
	if (const FVersePieceItem* Item = FindItem(uint16(*Slot)))
	{
		Piece.ApplyPresentation(Item->State, Item->Variant, Item->RepairFrom);
	}
	if (UVerseDebrisSubsystem* Debris = GetWorld() ? GetWorld()->GetSubsystem<UVerseDebrisSubsystem>() : nullptr)
	{
		Debris->PreloadPiece(Piece);
	}
}

void AVerseDestructionManager::UnregisterPiece(AVerseDestructible& Piece)
{
	const int32 Index = Piece.GetPieceIndex();
	if (PieceActors.IsValidIndex(Index) && PieceActors[Index] == &Piece)
	{
		PieceActors[Index] = nullptr;
	}
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
	ApplyDirtyItems();
}

void AVerseDestructionManager::ApplyHoleCap(uint16 PieceIndex, const FVector& LocalCentroidCm)
{
	if (!HasAuthority())
	{
		return;
	}
	Sim.ApplyHoleCap(PieceIndex, LocalCentroidCm, GetServerTimeMs());
	ApplyDirtyItems();
}

void AVerseDestructionManager::ApplyDroneDamage(int32 DroneIndex, float Amount)
{
	if (!HasAuthority())
	{
		return;
	}
	Sim.ApplyDroneDamage(DroneIndex, Amount, GetServerTimeMs());
	ApplyDirtyItems();
}

void AVerseDestructionManager::FullReset()
{
	if (!HasAuthority())
	{
		return;
	}
	Sim.FullReset(GetServerTimeMs());
	ApplyDirtyItems();
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
		ApplyDirtyItems();
		PublishTick();
	}
}

void AVerseDestructionManager::ApplyDirtyItems()
{
	const TArray<uint16> DirtyItems = Sim.DrainDirtyItems();
	if (DirtyItems.Num() > 0)
	{
		MARK_PROPERTY_DIRTY_FROM_NAME(AVerseDestructionManager, Pieces, this);
	}
	for (const uint16 Index : DirtyItems)
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
		MARK_PROPERTY_DIRTY_FROM_NAME(AVerseDestructionManager, Epoch, this);
	}
}

void AVerseDestructionManager::PublishTick()
{
	// Every input of this tick is in the sim by now, so several hits on one piece in one frame
	// (pellets, a breach plus bolts) leave one event (destruction.md 4).
	for (const FVersePendingFracture& Pending : Sim.DrainEvents())
	{
		if (Pending.bPublishLocal)
		{
			PublishLocal(Pending.Event);
		}
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

int32 AVerseDestructionManager::CompletedNavTiles() const
{
	const FVerseNavDirtyQueue& Nav = Sim.GetNav();
	if (Nav.NumInFlight() == 0)
	{
		return 0;
	}
	const UNavigationSystemV1* NavSys = FNavigationSystem::GetCurrent<UNavigationSystemV1>(GetWorld());
	if (!NavSys || !NavSys->GetDefaultNavDataInstance())
	{
		return Nav.NumInFlight(); // no navmesh in this world: nothing rebuilds, nothing to wait for
	}
	// Real feedback: the released tiles are rebuilt once the navigation system has taken every
	// dirty area and has no tile job queued or running.
	if (NavSys->HasDirtyAreasQueued() || NavSys->GetNumRemainingBuildTasks() > 0 || NavSys->GetNumRunningBuildTasks() > 0)
	{
		return 0;
	}
	return Nav.NumInFlight();
}

void AVerseDestructionManager::ReleaseNavTiles()
{
	// Once per server tick: slots free only when the navmesh confirms the rebuild, so at most
	// NavMaxTilesInFlight tiles are ever handed over and not yet rebuilt (destruction.md 6.1).
	FVerseNavDirtyQueue& Nav = Sim.GetNav();
	for (const FVerseNavDirtyQueue::FTile& Tile : Nav.Release(CompletedNavTiles()))
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

bool FVersePieceItem::HasFractureRecord() const
{
	return LastSeed != 0 || LastImpulse[0] != 0 || LastImpulse[1] != 0 || LastImpulse[2] != 0 || LastLocation[0] != 0
		|| LastLocation[1] != 0 || LastLocation[2] != 0;
}

namespace
{
	template <typename T>
	void SerializeBitsOf(FArchive& Ar, T& Value, int32 Bits)
	{
		uint64 Raw = Ar.IsSaving() ? uint64(Value) & ((uint64(1) << Bits) - 1) : 0;
		Ar.SerializeBits(&Raw, Bits);
		if (Ar.IsLoading())
		{
			Value = T(Raw);
		}
	}

	void SerializeInt16(FArchive& Ar, int16& Value)
	{
		uint16 Raw = uint16(Value);
		SerializeBitsOf(Ar, Raw, 16);
		Value = int16(Raw);
	}
}

bool FVersePieceItem::NetSerialize(FArchive& Ar, UPackageMap* Map, bool& bOutSuccess)
{
	bOutSuccess = PieceIndex < (1u << MaxPieceIndexBits);
	SerializeBitsOf(Ar, PieceIndex, MaxPieceIndexBits);
	uint8 StateBits = uint8(State);
	SerializeBitsOf(Ar, StateBits, 3);
	State = EVersePieceState(StateBits);
	SerializeBitsOf(Ar, HealthQ, 8);
	SerializeBitsOf(Ar, Variant, 2);
	if (State == EVersePieceState::Repairing)
	{
		uint8 From = uint8(RepairFrom);
		SerializeBitsOf(Ar, From, 3);
		RepairFrom = EVersePieceState(From);
	}
	else if (Ar.IsLoading())
	{
		RepairFrom = EVersePieceState::Intact;
	}
	uint8 bRecord = Ar.IsSaving() && HasFractureRecord() ? 1 : 0;
	SerializeBitsOf(Ar, bRecord, 1);
	if (bRecord)
	{
		SerializeBitsOf(Ar, LastSeed, 32);
		for (int32 Axis = 0; Axis < 3; ++Axis)
		{
			SerializeInt16(Ar, LastImpulse[Axis]);
		}
		for (int32 Axis = 0; Axis < 3; ++Axis)
		{
			SerializeInt16(Ar, LastLocation[Axis]);
		}
	}
	else if (Ar.IsLoading())
	{
		LastSeed = 0;
		FMemory::Memzero(LastImpulse, sizeof(LastImpulse));
		FMemory::Memzero(LastLocation, sizeof(LastLocation));
	}
	SerializeBitsOf(Ar, StateTimeMs, 32);
	SerializeBitsOf(Ar, Epoch, 16);
	bOutSuccess = bOutSuccess && !Ar.IsError();
	return true;
}

int32 FVersePieceItem::MeasureWireBytes(const FVersePieceItem& Item)
{
	FNetBitWriter Writer(nullptr, 1024);
	FVersePieceItem Copy = Item;
	bool bOk = false;
	Copy.NetSerialize(Writer, nullptr, bOk);
	return int32((Writer.GetNumBits() + 7) / 8);
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

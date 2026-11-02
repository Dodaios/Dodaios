#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "GameFramework/Actor.h"
#include "Pieces/VerseDestructionSim.h"
#include "Pieces/VersePieceItem.h"

#include "VerseDestructionManager.generated.h"

class AVerseDestructible;
class AVerseRepairDrone;
class UVerseDestructionTuning;
class UVersePieceManifest;
struct FVerseArenaSwitchEvent;

/**
 * Server fracture authority and replicated piece state of one arena (destruction.md 3.3,
 * architecture 4). One per arena world; always relevant. The server runs FVerseDestructionSim
 * and replicates its items in a fast array; clients apply the items to the piece actors
 * (late joiners build the broken look without debris) and receive an unreliable multicast
 * per fracture for instant debris. Every state change, repair and reset is published on the
 * event hub on server and clients.
 */
UCLASS()
class VERSEDESTRUCTION_API AVerseDestructionManager : public AActor, public IVersePieceQuery
{
	GENERATED_BODY()

public:
	AVerseDestructionManager();

	/** The manager of the object's world, or nullptr. */
	static AVerseDestructionManager* Get(const UObject* WorldContextObject);

	/** Thresholds, HP, times, budgets; the contract defaults when unset. */
	UPROPERTY(EditAnywhere, Category = "Destruction")
	TObjectPtr<UVerseDestructionTuning> Tuning;

	/**
	 * DA_PieceManifest of this arena. Required on networked clients (PieceIndex must match the
	 * server); a standalone or server world without it orders the loaded pieces by the same GUID rule.
	 */
	UPROPERTY(EditAnywhere, Category = "Destruction")
	TObjectPtr<UVersePieceManifest> Manifest;

	/** One repair drone per dock (destruction.md 7), world cm. */
	UPROPERTY(EditAnywhere, Category = "Repair")
	TArray<FVector> DroneDocks;

	UPROPERTY(EditAnywhere, Category = "Repair")
	TSubclassOf<AVerseRepairDrone> DroneClass;

	/** Server seed of the fracture RNG stream. */
	UPROPERTY(EditAnywhere, Category = "Destruction")
	int64 FractureSeed = 0x5EED;

	/** Reset on the hangar's arena switch (destruction.md 11). */
	UPROPERTY(EditAnywhere, Category = "Destruction")
	bool bResetOnArenaSwitch = true;

	/**
	 * IVersePieceDamage of this arena. A plain native interface (no UINTERFACE, see Core), so it
	 * is handed out as a reference instead of being a base class of the actor.
	 */
	IVersePieceDamage& GetPieceDamage() { return DamageSink; }

	/** Server only (DR1); what GetPieceDamage().ApplyPieceDamage calls. */
	void ApplyPieceDamage(const FVersePieceDamage& Damage);

	// IVersePieceQuery
	virtual EVersePieceState GetPieceState(uint16 PieceIndex) const override;
	virtual EVersePenetrationMaterial GetPieceMaterial(uint16 PieceIndex) const override;
	virtual FBox GetPieceBounds(uint16 PieceIndex) const override;
	virtual TArray<uint16> GetPiecesInBox(const FBox& WorldBox) const override;

	/** Full reset (destruction.md 11); VerseCombat calls it when the ruleset asks. Server only. */
	void FullReset();

	/** Hole 25 on a wall piece (destruction.md 5); called by the hole store. Server only. */
	void ApplyHoleCap(uint16 PieceIndex, const FVector& LocalCentroidCm);

	/** A bolt or melee hit on a repair drone. Server only. */
	void ApplyDroneDamage(int32 DroneIndex, float Amount);

	/** Registers the world's pieces in manifest order. Called from BeginPlay; tests may call it again. */
	void RegisterPieces();

	/**
	 * A piece that began play (World Partition streaming) takes its manifest slot and, on a
	 * client, shows the current replicated item at once. Called by AVerseDestructible::BeginPlay.
	 */
	void RegisterPiece(AVerseDestructible& Piece);
	/** A piece that streamed out leaves its slot (the replicated state stays). */
	void UnregisterPiece(AVerseDestructible& Piece);

	/** True when this manager is a client of a networked game and has no manifest (refuses to register). */
	bool IsMissingClientManifest() const;

	int32 NumPieces() const { return Pieces.Items.Num(); }
	AVerseDestructible* GetPieceActor(uint16 PieceIndex) const;
	const FVersePieceItem* FindItem(uint16 PieceIndex) const;
	uint16 GetEpoch() const { return Epoch; }
	const FVerseDestructionSim& GetSim() const { return Sim; }

	/** Server time in ms used for every state record. */
	uint32 GetServerTimeMs() const;

	/** Nav tiles handed to the navigation system and not confirmed rebuilt yet. */
	int32 GetNavTilesInFlight() const { return Sim.GetNav().NumInFlight(); }
	int32 GetPeakNavTilesInFlight() const { return Sim.GetNav().GetPeakInFlight(); }

	/** Tests: stands in for the fast array delivering these items to a client. */
	void ReceiveItemsForTest(TConstArrayView<FVersePieceItem> InItems, bool bInitial);

	/** Client side: a replicated item arrived or changed (fast array callback). */
	void OnItemReplicated(const FVersePieceItem& Item, bool bInitial);

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;
	virtual void Tick(float DeltaSeconds) override;

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

	UFUNCTION(NetMulticast, Unreliable)
	void MulticastFracture(const FVerseFractureEvent& Event);

	UFUNCTION()
	void OnRep_Epoch();

private:
	/** After any server input: copies dirty sim items into the fast array and the piece actors. */
	void ApplyDirtyItems();
	/** Once per server tick: events (coalesced per piece and tick), noise, nav tiles, drones. */
	void PublishTick();
	void PublishLocal(const FVerseFractureEvent& Event);
	void HandleArenaSwitch(const FVerseArenaSwitchEvent& Event);
	void SpawnDrones();
	void SyncDrones();
	void ReleaseNavTiles();
	int32 CompletedNavTiles() const;
	bool IsEncroached(const FBox& WorldBox) const;

	UPROPERTY(Replicated)
	FVersePieceItemArray Pieces;

	UPROPERTY(ReplicatedUsing = OnRep_Epoch)
	uint16 Epoch = 0;

	UPROPERTY(Transient)
	TArray<TObjectPtr<AVerseDestructible>> PieceActors;

	UPROPERTY(Transient)
	TArray<TObjectPtr<AVerseRepairDrone>> DroneActors;

	struct FDamageSink final : IVersePieceDamage
	{
		AVerseDestructionManager* Owner = nullptr;
		virtual void ApplyPieceDamage(const FVersePieceDamage& Damage) override { Owner->ApplyPieceDamage(Damage); }
	};

	FDamageSink DamageSink;
	FVerseDestructionSim Sim;
	FDelegateHandle ArenaSwitchHandle;
	/** Manifest GUID -> PieceIndex, built at registration. */
	TMap<FGuid, int32> SlotOfGuid;
	bool bRegistered = false;
};

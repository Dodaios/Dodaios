#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "Nav/VerseNavDirtyQueue.h"
#include "Pieces/VersePieceItem.h"
#include "Pieces/VersePieceRules.h"
#include "Pieces/VersePieceTypes.h"

/** A repair drone's task (destruction.md 7). */
enum class EVerseDroneTask : uint8
{
	Docked,
	Outbound,
	Repairing,
	Returning,
	/** Shot down this tick; the dock replaces it with a fresh drone. */
	Down
};

/** Server state of one repair drone. */
struct VERSEDESTRUCTION_API FVerseDroneState
{
	int32 Index = 0;
	FVector Dock = FVector::ZeroVector;
	FVector Location = FVector::ZeroVector;
	FVector FlightFrom = FVector::ZeroVector;
	FVector FlightTo = FVector::ZeroVector;
	EVerseDroneTask Task = EVerseDroneTask::Docked;
	int32 TargetPiece = INDEX_NONE;
	uint32 FlightStartMs = 0;
	uint32 FlightEndMs = 0;
	uint32 RepairEndMs = 0;
	uint32 NextEncroachCheckMs = 0;
	uint32 NextNoiseMs = 0;
	float Hp = 30.f;
	/** Counts downs, so the actor knows to drop debris and respawn. */
	uint32 Generation = 0;

	bool IsActive() const { return Task == EVerseDroneTask::Outbound || Task == EVerseDroneTask::Repairing; }
	bool IsFree() const { return Task == EVerseDroneTask::Docked || Task == EVerseDroneTask::Returning; }
};

/** One fracture event of a tick, plus whether it fits the multicast rate cap. */
struct FVersePendingFracture
{
	FVerseFractureEvent Event;
	bool bMulticast = true;
	/** False for a deferred over-rate event: it was published on the server when it happened. */
	bool bPublishLocal = true;
};

/** Counters of the destruction budgets (destruction.md 10), read by the storm scenario. */
struct VERSEDESTRUCTION_API FVerseDestructionCounters
{
	int32 StateChanges = 0;
	int32 EventsPublished = 0;
	int32 EventsMulticast = 0;
	int32 EventsCoalesced = 0;
	int32 EventsOverRate = 0;
	/** Over-rate events multicast later, and the ones that aged out (> 1 s) first. */
	int32 EventsDeferredSent = 0;
	int32 EventsDeferredDropped = 0;
	int32 PeakEventsPerSecond = 0;
	int32 ItemWrites = 0;
	int32 Repairs = 0;
	int32 RepairsInterrupted = 0;
	int32 PeakActiveDrones = 0;
};

/**
 * The authoritative destruction simulation of one arena (destruction.md 3 to 8, 11). No UWorld:
 * AVerseDestructionManager feeds it damage and server time, and drains its outputs (dirty
 * fast-array items, fracture events, noise, nav tiles) into replication, the event hub and the
 * navigation system. Deterministic for a given seed, piece list and input sequence.
 */
class VERSEDESTRUCTION_API FVerseDestructionSim
{
public:
	/** Answers whether a pawn overlaps a world box (repair encroachment, destruction.md 7). */
	using FEncroachFn = TFunctionRef<bool(const FBox& WorldBox)>;

	/** Replaces the static description of one slot (a piece that registered after Init). */
	void SetDef(uint16 PieceIndex, FVersePieceDef Def);

	/** Pieces in manifest order (index = PieceIndex). Docks: one drone each. */
	void Init(TArray<FVersePieceDef> InDefs, const FVerseDestructionSimTuning& InTuning, TConstArrayView<FVector> DroneDocks, uint64 InSeed);

	// --- Server inputs (DR1: only the server calls these) ---

	/** IVersePieceDamage::ApplyPieceDamage. Breach charges also apply their radius effect. */
	void ApplyDamage(const FVersePieceDamage& Damage, uint32 NowMs);

	/** Hole cap reached (destruction.md 5, hole 25 on a wall piece): Holed with the variant nearest the hole centroid. */
	void ApplyHoleCap(uint16 PieceIndex, const FVector& LocalCentroidCm, uint32 NowMs);

	/** A bolt or melee hit on drone `DroneIndex`. Returns true if it was downed. */
	bool ApplyDroneDamage(int32 DroneIndex, float Amount, uint32 NowMs);

	/** Repair timers, drone flight, repair completion. Call once per server tick. */
	void Tick(uint32 NowMs, FEncroachFn IsEncroached);

	/** destruction.md 11. */
	void FullReset(uint32 NowMs);

	// --- Outputs (drained by the owner once per tick) ---

	TArray<FVersePendingFracture> DrainEvents();
	TArray<FVerseNoiseEvent> DrainNoise();
	/** Piece indices whose replicated item changed since the last drain. */
	TArray<uint16> DrainDirtyItems();
	FVerseNavDirtyQueue& GetNav() { return Nav; }
	const FVerseNavDirtyQueue& GetNav() const { return Nav; }

	// --- Reads ---

	int32 Num() const { return Defs.Num(); }
	const FVersePieceDef& GetDef(uint16 PieceIndex) const { return Defs[PieceIndex]; }
	const FVersePieceItem& GetItem(uint16 PieceIndex) const { return Items[PieceIndex]; }
	const TArray<FVersePieceItem>& GetItems() const { return Items; }
	float GetHp(uint16 PieceIndex) const { return Server[PieceIndex].Hp; }
	uint32 GetLastDamageMs(uint16 PieceIndex) const { return Server[PieceIndex].LastDamageMs; }
	const TArray<FVerseDroneState>& GetDrones() const { return Drones; }
	int32 NumActiveDrones() const;
	uint16 GetEpoch() const { return Epoch; }
	const FVerseDestructionSimTuning& GetTuning() const { return Tuning; }
	const FVerseDestructionCounters& GetCounters() const { return Counters; }
	bool IsValidPiece(int32 PieceIndex) const { return Defs.IsValidIndex(PieceIndex); }

	/** World bounds of the live proxy of a piece. */
	FBox GetPieceBounds(uint16 PieceIndex) const;
	TArray<uint16> GetPiecesInBox(const FBox& WorldBox) const;

	/** Nav links live in the piece's current state (mantle while Breached, drop while Destroyed). */
	TArray<FVersePieceNavLink> GetLiveNavLinks(uint16 PieceIndex, EVersePieceNavLinkKind& OutKind) const;

	/** Hash of every piece's proxy state and variant (determinism gate A6.7). */
	static uint32 ProxyHash(TConstArrayView<FVersePieceItem> InItems);

	/** Wire bytes of the last reset burst: fast array header plus element id and NetSerialize bytes per written item. */
	int32 GetLastResetBurstBytes() const { return LastResetBurstBytes; }

private:
	struct FServerPiece
	{
		float Hp = 0.f;
		uint32 LastDamageMs = 0;
		uint32 BrokenSinceMs = 0;
		FVector HitSumLocal = FVector::ZeroVector;
		int32 HitCount = 0;
		bool bDamagedSinceRepair = false;
		int32 AssignedDrone = INDEX_NONE;
	};

	void ApplyOne(uint16 PieceIndex, const FVersePieceDamage& Damage, Verse::Destruction::Rules::EHitRole Role, uint32 NowMs);
	void SetState(uint16 PieceIndex, EVersePieceState NewState, uint8 Variant, EVerseFractureCause Cause,
		const FVector& WorldLocation, const FVector& Direction, float ImpulseNs, uint8 RadiusCm, uint8 Instigator, uint32 NowMs);
	void WriteHealth(uint16 PieceIndex);
	void CancelRepair(uint16 PieceIndex, EVerseFractureCause Cause, uint8 Instigator, uint32 NowMs);
	void Recall(FVerseDroneState& Drone, uint32 NowMs);
	void Dispatch(uint32 NowMs);
	void StartFlight(FVerseDroneState& Drone, const FVector& To, uint32 NowMs);
	void UpdateDroneLocation(FVerseDroneState& Drone, uint32 NowMs) const;
	void PushEvent(const FVerseFractureEvent& Event, uint32 NowMs);
	void PushNoise(const FGameplayTag& Tag, const FVector& Location, float Loudness, uint32 NowMs);
	void MarkDirty(uint16 PieceIndex);
	void MarkNav(uint16 PieceIndex, EVersePieceState OldState, uint8 OldVariant);
	uint32 NextSeed();
	bool CanBreak(uint16 PieceIndex) const;

	TArray<FVersePieceDef> Defs;
	TArray<FVersePieceItem> Items;
	TArray<FServerPiece> Server;
	TArray<FVerseDroneState> Drones;
	FVerseDestructionSimTuning Tuning;
	FVerseNavDirtyQueue Nav;

	TArray<FVersePendingFracture> Events;
	/** Piece -> index into Events for this tick (coalescing). */
	TMap<uint16, int32> EventOfPiece;
	/** Over-rate events waiting for room in the multicast window, one per piece (coalesced). */
	TMap<uint16, FVerseFractureEvent> Deferred;
	uint32 EventTickMs = 0;
	uint32 LastTickMs = 0;
	TArray<uint32> MulticastTimesMs;
	TArray<FVerseNoiseEvent> Noise;
	TSet<uint16> Dirty;

	FVerseDestructionCounters Counters;
	uint64 Seed = 0;
	uint64 SeedCounter = 0;
	uint16 Epoch = 0;
	int32 LastResetBurstBytes = 0;
};

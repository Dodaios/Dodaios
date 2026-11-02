#pragma once

#include "CoreMinimal.h"
#include "Debris/VerseDebrisBudget.h"
#include "Subsystems/WorldSubsystem.h"
#include "Tickable.h"

#include "VerseDebrisSubsystem.generated.h"

class AGeometryCollectionActor;
class AVerseDestructible;
class UGeometryCollection;
struct FStreamableHandle;
struct FVerseFractureEvent;
struct FVersePieceDebrisSet;

/**
 * Client-side cosmetic debris (destruction.md 4, 10; DR3). Listens to OnFracture on the hub and
 * spawns one geometry collection burst per fracture inside FVerseDebrisBudget. The burst is the
 * piece's authored debris set for the new state (GC_<Piece>_<State>_<n>: only the chunks of the
 * opening, so a Holed wall that still stands gets no full chunk set inside it) with the most
 * chunks that still fit the grant; the budget is then charged with the rigid bodies the spawned
 * component really has. Actors come from a pool of at most 32; the sets are loaded
 * asynchronously when a piece registers, never on the game thread at the first fracture.
 * A dedicated server and every -nullrhi run spawn nothing; replicated items (late join) never
 * spawn debris. Debris uses the Verse_Debris profile, so it never blocks pawns, bolts or sight (DR2).
 */
UCLASS()
class VERSEDESTRUCTION_API UVerseDebrisSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	/** False on a dedicated server and without a renderer (DR3). */
	static bool ShouldSpawnDebris(const UWorld& World);

	/**
	 * Index of the set to spawn for a grant: the one with the most bodies that is still at most
	 * Grant, INDEX_NONE when none fits (then only the Niagara part plays).
	 */
	static int32 PickSet(TConstArrayView<int32> SetBodies, int32 Grant);

	/** Rigid bodies of a geometry collection: its leaf geometry count (every chunk once broken). */
	static int32 CountBodies(const UGeometryCollection& Collection);

	/** Low preset: 150 bodies, 6 s lifetime. */
	void SetLowPreset(bool bLow);

	/** Starts the async load of a piece's debris sets (called when the piece registers). */
	void PreloadPiece(const AVerseDestructible& Piece);

	const FVerseDebrisBudget& GetBudget() const { return Budget; }
	int32 GetSpawnedBursts() const { return SpawnedBursts; }
	int32 GetPooledActors() const { return Pool.Num(); }

	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;

private:
	void HandleFracture(const FVerseFractureEvent& Event);
	/** Spawns the burst and returns the real rigid body count (0 = nothing spawned). */
	int32 SpawnBurst(int32 BurstId, const FVerseFractureEvent& Event, int32 Grant);
	void ReleaseBurst(int32 BurstId);
	AGeometryCollectionActor* AcquireActor();

	FVerseDebrisBudget Budget;
	TMap<int32, TWeakObjectPtr<AGeometryCollectionActor>> BurstActors;
	/** Idle pooled actors (hidden, no collision, not simulating). */
	UPROPERTY(Transient)
	TArray<TObjectPtr<AGeometryCollectionActor>> Pool;
	int32 PoolSize = 0;
	TArray<TSharedPtr<FStreamableHandle>> Preloads;
	FDelegateHandle FractureHandle;
	int32 SpawnedBursts = 0;
	bool bEnabled = false;
};

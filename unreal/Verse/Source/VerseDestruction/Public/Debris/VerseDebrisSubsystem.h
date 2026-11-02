#pragma once

#include "CoreMinimal.h"
#include "Debris/VerseDebrisBudget.h"
#include "Subsystems/WorldSubsystem.h"
#include "Tickable.h"

#include "VerseDebrisSubsystem.generated.h"

struct FVerseFractureEvent;

/**
 * Client-side cosmetic debris (destruction.md 4, 10; DR3). Listens to OnFracture on the hub and
 * spawns a pooled geometry collection burst per fracture inside FVerseDebrisBudget. A dedicated
 * server and every -nullrhi run spawn nothing; replicated items (late join) never spawn debris.
 * Debris uses the Verse_Debris profile, so it never blocks pawns, bolts or sight (DR2).
 */
UCLASS()
class VERSEDESTRUCTION_API UVerseDebrisSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	/** False on a dedicated server and without a renderer (DR3). */
	static bool ShouldSpawnDebris(const UWorld& World);

	/** Low preset: 150 bodies, 6 s lifetime. */
	void SetLowPreset(bool bLow);

	const FVerseDebrisBudget& GetBudget() const { return Budget; }
	int32 GetSpawnedBursts() const { return SpawnedBursts; }

	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;

private:
	void HandleFracture(const FVerseFractureEvent& Event);
	AActor* SpawnBurst(const FVerseFractureEvent& Event, int32 Bodies);
	void DestroyBurst(int32 BurstId);

	FVerseDebrisBudget Budget;
	TMap<int32, TWeakObjectPtr<AActor>> BurstActors;
	FDelegateHandle FractureHandle;
	int32 SpawnedBursts = 0;
	bool bEnabled = false;
};

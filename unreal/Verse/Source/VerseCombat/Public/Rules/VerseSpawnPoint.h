#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerStart.h"

#include "VerseSpawnPoint.generated.h"

/**
 * A duel spawn in the arena data layer (combat-state.md 9.2, 11.2). Placed from the `spawn`
 * sockets of the hangar arena placement files (docs/verse/unreal/arena.md). The probe points
 * are the heights above the floor the opponent's sight is tested against.
 */
UCLASS()
class VERSECOMBAT_API AVerseSpawnPoint : public APlayerStart
{
	GENERATED_BODY()

public:
	AVerseSpawnPoint(const FObjectInitializer& ObjectInitializer);

	UPROPERTY(EditInstanceOnly, Category = "Verse|Spawn")
	TArray<float> ProbeHeightsM = {0.3f, 1.0f, 1.65f};

	/** The socket id of the placement file, e.g. "sp_booth" (for logs and tests). */
	UPROPERTY(EditInstanceOnly, Category = "Verse|Spawn")
	FName SpawnId;

	/** Floor point under the capsule, world cm. */
	FVector GetFloorLocation() const;
};

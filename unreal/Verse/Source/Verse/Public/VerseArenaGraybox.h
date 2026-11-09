#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseArenaGraybox.generated.h"

class UInstancedStaticMeshComponent;
class UMaterialInterface;

/**
 * The hangar arena of WP11 as runtime graybox (arena.md 10: its placements and meshes are not in
 * LV_Hangar yet). Built from unreal/Verse/Data/arena/hangar_graybox.json, which
 * scripts/unreal/arena_graybox.py writes from art/verse/decks/hangar/unreal_arena/layout.py:
 * boxes and ramps as instanced cubes per surface (Verse_Architecture or Verse_Glass collision),
 * the nine spawn points and the work lights. LV_Hangar's nav bounds cover the arena and the nav mesh
 * generates at runtime, so the bot and the scripted player path through it. Removed again when the hangar goes back to day.
 */
UCLASS(NotPlaceable, Transient)
class VERSE_API AVerseArenaGraybox : public AActor
{
	GENERATED_BODY()

public:
	AVerseArenaGraybox();

	/** Server and clients: spawns the graybox when the world has no arena spawn points; nullptr when it has. */
	static AVerseArenaGraybox* BuildIfMissing(UWorld& World);
	/** The graybox of a world, if built. */
	static AVerseArenaGraybox* Find(const UWorld& World);

	/** Reads the JSON and creates everything; false when the file is missing or broken. */
	bool Build(const FString& JsonPath);

	static FString DefaultJsonPath();

	int32 NumBoxes() const { return Boxes; }
	int32 NumSpawns() const { return Spawned.Num(); }

	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
	UInstancedStaticMeshComponent* SurfaceFor(const FString& Material, bool bSolid, bool bGlass);
	void AddSlab(UInstancedStaticMeshComponent* Surface, const FTransform& Transform);

	UPROPERTY()
	TMap<FString, TObjectPtr<UInstancedStaticMeshComponent>> Surfaces;

	UPROPERTY()
	TArray<TObjectPtr<AActor>> Spawned;

	int32 Boxes = 0;
};

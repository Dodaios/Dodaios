#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseArenaGraybox.generated.h"

class AVerseDestructible;
class AVerseDestructionManager;
class UExponentialHeightFogComponent;
class UInstancedStaticMeshComponent;
class UMaterialInterface;
class UStaticMesh;
class UStaticMeshComponent;
struct FVerseFractureEvent;

/**
 * The hangar arena of WP11 as runtime graybox (arena.md 10: its placements and meshes are not in
 * LV_Hangar yet). Built from unreal/Verse/Data/arena/hangar_graybox.json, which
 * scripts/unreal/arena_graybox.py writes from art/verse/decks/hangar/unreal_arena/layout.py:
 *
 * - boxes and ramps as instanced cubes per surface (Verse_Architecture or Verse_Glass collision),
 * - the 114 breakable boxes (`piece`) as WP06 AVerseDestructible pieces under one
 *   AVerseDestructionManager with three repair drones (arena.md 6, 7): bolts hole them, breach
 *   charges open them, glass, catwalks and ceiling panels can come down, chunks fly on every
 *   breach and the drones close the openings again,
 * - the nine spawn points,
 * - the work lights and the arena look of WP11.12 (arena.md 9): warm work lights against a cool
 *   fill, manual exposure, height and volumetric fog, bloom and vignette.
 *
 * LV_Hangar's nav bounds cover the arena and the nav mesh generates at runtime, so the bot and the
 * scripted player path through it. Removed again when the hangar goes back to day.
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

	/** Exposure of the arena look (arena.md 9 "manual exposure"), EV100. */
	static constexpr float ArenaExposureEV100 = 2.2f;
	/** Debris chunks alive at once, and how long one lies before it goes. */
	static constexpr int32 MaxDebrisChunks = 90;
	static constexpr float DebrisLifeS = 7.f;

	int32 NumBoxes() const { return Boxes; }
	int32 NumSpawns() const { return SpawnPoints; }
	int32 NumPieces() const { return Pieces.Num(); }
	int32 NumDebris() const { return Debris.Num(); }
	AVerseDestructionManager* GetDestructionManager() const { return Manager; }
	/** The arena look's exposure (tests sweep it; ArenaExposureEV100 is the default). */
	void SetExposureEV100(float EV100);

	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
	UInstancedStaticMeshComponent* SurfaceFor(const FString& Material, bool bSolid, bool bGlass);
	void AddSlab(UInstancedStaticMeshComponent* Surface, const FTransform& Transform);
	UMaterialInterface* MaterialFor(const FString& Material);
	void ApplyLook(UWorld& World);
	void RestoreLook();
	AVerseDestructible* SpawnPiece(UWorld& World, const TSharedPtr<class FJsonObject>& Box);
	void SpawnDestruction(UWorld& World, const TArray<TSharedPtr<class FJsonObject>>& PieceBoxes);
	void DressDrones();
	void HandleFracture(const FVerseFractureEvent& Event);

	UPROPERTY()
	TMap<FString, TObjectPtr<UInstancedStaticMeshComponent>> Surfaces;

	UPROPERTY()
	TMap<FString, TObjectPtr<UMaterialInterface>> Materials;

	UPROPERTY()
	TArray<TObjectPtr<AActor>> Spawned;

	UPROPERTY()
	TArray<TObjectPtr<AVerseDestructible>> Pieces;

	UPROPERTY()
	TObjectPtr<AVerseDestructionManager> Manager;

	/** The breach frames by the piece's thin axis (X, Y, Z): a cube with a hole through it. */
	UPROPERTY()
	TArray<TObjectPtr<UStaticMesh>> BreachFrames;

	struct FDebrisChunk
	{
		TWeakObjectPtr<UStaticMeshComponent> Component;
		double DieAt = 0.0;
	};
	TArray<FDebrisChunk> Debris;

	/** The deck fog as it was before the arena look, restored on leave. */
	TWeakObjectPtr<UExponentialHeightFogComponent> DeckFog;
	float SavedFogDensity = 0.f;
	float SavedFogFalloff = 0.f;
	float SavedFogStart = 0.f;
	bool bFogSaved = false;

	TWeakObjectPtr<class APostProcessVolume> ArenaPost;
	FDelegateHandle FractureHandle;
	int32 Boxes = 0;
	int32 SpawnPoints = 0;
};

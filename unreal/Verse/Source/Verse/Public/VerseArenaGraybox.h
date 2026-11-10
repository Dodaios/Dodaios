#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "Decks/VerseDeckManifest.h"
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
 *   fill, manual exposure, height and volumetric fog, bloom and vignette,
 * - the dressing (arena.md 9.2): every box gets a kit material instance by what it is (deck plates,
 *   hull walls, barriers, containers, shuttle hull, booth), and kit meshes, trusses, light fixtures,
 *   railings, fences, hazard bands, floor markings and hall props are added without collision, so
 *   the dressing never changes what blocks a pawn, a bolt or the bot's sight.
 *
 * LV_Hangar's nav bounds cover the arena and the nav mesh generates at runtime, so the bot and the
 * scripted player path through it. The duel removes it again when the hangar goes back to day;
 * the deck view keeps a hall-only graybox (EVerseGrayboxPart::Hall) so the hangar is dressed there too.
 */
/** What a graybox carries. */
enum class EVerseGrayboxPart : uint8
{
	/** The hangar hall alone (layout layer "base"): hull, floor, ceiling, armoury, hall dressing,
	 *  floor markings, the truss and armoury lights and the hangar look. The deck view stands in it. */
	Hall,
	/** Hall and arena (layers "base" and "arena"): cover, catwalks, booth, shuttle, the breakable
	 *  pieces, spawn points and the nav mesh on top. The duel plays in it. */
	Full,
};

UCLASS(NotPlaceable, Transient)
class VERSE_API AVerseArenaGraybox : public AActor
{
	GENERATED_BODY()

public:
	AVerseArenaGraybox();

	/** Server and clients: spawns the graybox when the world has no arena spawn points; nullptr when it has. */
	static AVerseArenaGraybox* BuildIfMissing(UWorld& World);
	/** The duel's (full) graybox of a world, if built. */
	static AVerseArenaGraybox* Find(const UWorld& World);
	/**
	 * The hangar hall for the deck view: built unless the duel's full graybox already stands (it
	 * contains the hall) or the level has its own arena. BuildIfMissing replaces it with the full one.
	 */
	static AVerseArenaGraybox* BuildHall(UWorld& World, const TArray<FVerseDeckRoom>& KeepClear = {});
	/** The hall-only graybox of a world, if built. */
	static AVerseArenaGraybox* FindHall(const UWorld& World);

	/** Reads the JSON and creates the part; false when the file is missing or broken. */
	bool Build(const FString& JsonPath, EVerseGrayboxPart InPart = EVerseGrayboxPart::Full);
	EVerseGrayboxPart GetPart() const { return Part; }

	static FString DefaultJsonPath();

	/** Exposure of the arena look (arena.md 9 "manual exposure"), EV100. */
	static constexpr float ArenaExposureEV100 = 4.0f;
	/** Debris chunks alive at once, and how long one lies before it goes. */
	static constexpr int32 MaxDebrisChunks = 90;
	static constexpr float DebrisLifeS = 7.f;

	int32 NumBoxes() const { return Boxes; }
	int32 NumSpawns() const { return SpawnPoints; }
	int32 NumPieces() const { return Pieces.Num(); }
	int32 NumDebris() const { return Debris.Num(); }
	/** Dressing instances (kit meshes and trim) added around the boxes. */
	int32 NumDressing() const { return DressingInstances; }
	AVerseDestructionManager* GetDestructionManager() const { return Manager; }
	/** The arena look's exposure (tests sweep it; ArenaExposureEV100 is the default). */
	void SetExposureEV100(float EV100);

	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
	/** One instanced surface per look (kit MI) and collision kind; hidden ones only collide. */
	UInstancedStaticMeshComponent* SurfaceFor(const FString& Look, bool bSolid, bool bGlass, bool bVisible = true);
	void AddSlab(UInstancedStaticMeshComponent* Surface, const FTransform& Transform);
	/** The kit MI of a look (`MI_<Name>` under /Game/Verse/Materials/Instances), a tinted fallback without it. */
	UMaterialInterface* MaterialFor(const FString& Look);
	/** The look of a box by its id, zone and penetration material (arena.md 9.2). */
	static FString LookFor(const TSharedPtr<class FJsonObject>& Box);
	/** Collision-free instances of a mesh with an optional material over every slot. */
	UInstancedStaticMeshComponent* DressingFor(UStaticMesh* Mesh, UMaterialInterface* Override, bool bShadow = true);
	void AddDressing(const TCHAR* MeshPath, const FTransform& Transform, const TCHAR* Override = nullptr, bool bShadow = true);
	/** A collision-free box (cm) in a look: trim, trusses, bands, strips. */
	void AddTrim(const FString& Look, const FVector& Center, const FVector& Size, const FRotator& Rotation = FRotator::ZeroRotator, bool bShadow = true);
	void Dress(UWorld& World, const TSharedPtr<class FJsonObject>& Root);
	void DressHall();
	void DressBox(const TSharedPtr<class FJsonObject>& Box);
	/** Oil stains and scuffs on the arena floor (deferred decals, seeded). */
	void DressDecals();
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
	TMap<FString, TObjectPtr<UInstancedStaticMeshComponent>> Dressing;

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
	float SavedFogScattering = 0.2f;
	bool bFogSaved = false;

	TWeakObjectPtr<class APostProcessVolume> ArenaPost;
	/** Directional lights of the world turned off while the arena's fill is the only one. */
	TArray<TWeakObjectPtr<class UDirectionalLightComponent>> MutedLights;
	FDelegateHandle FractureHandle;
	EVerseGrayboxPart Part = EVerseGrayboxPart::Full;
	/** Deck rooms the hall's loose props stay out of (where the deck's own stations stand). */
	TArray<FVerseDeckRoom> KeepClear;
	bool InKeptClearRoom(const FVector& At) const;
	/** Whether a box, ramp or light of the JSON belongs to this part (by its "layer"). */
	bool Includes(const TSharedPtr<class FJsonObject>& Entry) const;
	int32 Boxes = 0;
	int32 SpawnPoints = 0;
	int32 DressingInstances = 0;
};

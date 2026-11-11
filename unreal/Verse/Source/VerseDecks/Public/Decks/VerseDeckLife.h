#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "VerseDeckLife.generated.h"

struct FVerseDeckManifest;
class UInstancedStaticMeshComponent;
class UMaterialInterface;
class UStaticMesh;
class UStaticMeshComponent;

/**
 * The lived-in pass of a deck (charcoal + gold): every console screen shows a read-out, a holo globe
 * turns over each holo table, gold guide lights run along the room edges, and the desks and floors
 * carry tablets, mugs, data pads, headsets, tool cases and cable coils.
 *
 * Purely visual: everything it adds has no collision and no nav, sits on surfaces found by traces
 * at runtime, and leaves the deck's sockets and the coordinates contract untouched. WP16's live
 * monitors replace a read-out when they bind their render target to the same slot.
 */
UCLASS()
class VERSEDECKS_API AVerseDeckLife : public AActor
{
	GENERATED_BODY()

public:
	AVerseDeckLife();

	/** Dresses the loaded deck level. Returns the number of things it placed or re-skinned. */
	int32 Build(const FVerseDeckManifest& Manifest);

	virtual void Tick(float DeltaSeconds) override;

	/** Read-out layouts a deck's screens cycle through, by deck id. */
	static TArray<FName> ReadoutsFor(FName Deck);

	/** Counts of the last Build, for the tests. */
	int32 ScreensLit = 0;
	int32 HoloGlobes = 0;
	int32 GuideLights = 0;
	int32 WallDisplays = 0;
	int32 DeskProps = 0;
	int32 FloorProps = 0;

private:
	int32 LightScreens(FName Deck);
	void PlaceHolos(const FVerseDeckManifest& Manifest);
	void PlaceGuides(const FVerseDeckManifest& Manifest);
	void PlaceDeskProps(const FVerseDeckManifest& Manifest);
	void PlaceWallDisplays(const FVerseDeckManifest& Manifest);
	void PlaceSurfaceProps(const FVerseDeckManifest& Manifest);
	void PlaceFloorProps(const FVerseDeckManifest& Manifest);
	static TArray<const TCHAR*> DeskKinds(FName Deck);
	/** Nothing placed within 30 cm, and open space above the spot. */
	bool Free(const FVector& Top) const;
	/** A 26 cm footprint around the spot lands at one height. */
	bool Flat(const FVector& Top) const;

	/** One instanced component per clutter mesh, made on first use. */
	UInstancedStaticMeshComponent* Instances(const TCHAR* MeshName);
	/** Downward trace against the deck's static geometry. */
	bool TraceDown(const FVector& From, double Depth, FHitResult& Hit) const;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks")
	TObjectPtr<USceneComponent> Root;

	UPROPERTY(Transient)
	TMap<FName, TObjectPtr<UInstancedStaticMeshComponent>> InstanceSets;

	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> Globes;

	/** Where props already stand (world), so two never overlap. */
	TArray<FVector> Taken;
};

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseGoreActor.generated.h"

class UDecalComponent;
class UInstancedStaticMeshComponent;
class UMaterialInterface;
class UStaticMesh;

/**
 * The one local, transient actor that owns every gore component of a world (WP05). It never
 * replicates, never collides, never affects navigation and is invisible to every trace channel,
 * so the bot and gameplay can never see it (contracts/combat-state.md 8, bot.md 3.1).
 */
UCLASS(Transient, NotPlaceable, NotBlueprintable)
class VERSEGORE_API AVerseGoreActor : public AActor
{
	GENERATED_BODY()

public:
	AVerseGoreActor();

	/** A new decal component (no collision, not saved), registered on this actor at `Transform`. */
	UDecalComponent* NewDecal(UMaterialInterface* Material, const FVector& Size, const FLinearColor& Color, int32 SortOrder,
		const FTransform& Transform);

	/** Droplets of blood bursts. */
	UPROPERTY(VisibleAnywhere, Category = "Gore")
	TObjectPtr<UInstancedStaticMeshComponent> Droplets;

	/** Neutral impact flashes of the Reduced level. */
	UPROPERTY(VisibleAnywhere, Category = "Gore")
	TObjectPtr<UInstancedStaticMeshComponent> Flashes;

	/** Applies mesh and materials once they are loaded (null keeps the component empty). */
	void SetLook(UStaticMesh* DropletMesh, UMaterialInterface* DropletMaterial, UMaterialInterface* FlashMaterial);

	/** Makes a primitive cosmetic-only: no collision, no overlaps, no navigation, no shadows. */
	static void MakeCosmetic(UPrimitiveComponent* Component);

private:
	UInstancedStaticMeshComponent* NewInstanced(FName Name);
};

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "VerseContentTools.generated.h"

class UPhysicsAsset;
class USkeletalMesh;

// Editor helpers for the content generators in scripts/unreal/ (G0.8, G0.9).
// Called from editor Python; nothing here runs in a packaged game.
UCLASS()
class VERSE_API UVerseContentTools : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
#if WITH_EDITOR
	// Replaces every body and constraint of PhysicsAsset with one capsule per
	// entry of Bones, running from that bone to EndBones[i] (or, when the end is
	// None, onward along the parent-to-bone direction) with radius Radii[i] in cm.
	// Hit bodies only (art-pipeline 12.1, architecture 3.3); ragdoll tuning is WP13's.
	UFUNCTION(BlueprintCallable, Category = "Verse|Content")
	static bool RebuildHitBodies(UPhysicsAsset* PhysicsAsset, USkeletalMesh* Mesh,
		const TArray<FName>& Bones, const TArray<FName>& EndBones, const TArray<float>& Radii);
#endif
};

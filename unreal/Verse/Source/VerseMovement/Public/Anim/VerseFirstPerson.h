#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"

#include "VerseFirstPerson.generated.h"

class UCameraComponent;
class UPrimitiveComponent;
class USkeletalMeshComponent;

/**
 * First-person body setup (WP13.5, art-pipeline 12.1 "First person"): the full
 * body is the owner's first-person body with the head hidden, rendered with
 * the engine's first-person rendering so arms and weapon never clip walls;
 * a second component on the same mesh is the world-space body others and the
 * shadows see. The first-person body runs its own `UVerseAnimInstance` (a
 * leader-pose follower cannot hide bones of its own: the engine takes the
 * leader's visibility), which scales `Head` to zero while the component carries
 * `OwnerViewTag`. The camera follows the world body's `Camera` bone; the first-
 * person body's `Camera` collapses with the hidden head.
 */
UCLASS()
class VERSEMOVEMENT_API UVerseFirstPersonLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Bone hidden on the owner's first-person body. */
	static const FName HiddenBone;

	/** Component tag of the owner's first-person body; `UVerseAnimInstance` hides the head while it is set. */
	static const FName OwnerViewTag;

	UFUNCTION(BlueprintCallable, Category = "Verse|Anim")
	static void ConfigureOwnerView(USkeletalMeshComponent* FirstPersonBody, USkeletalMeshComponent* WorldBody,
		UCameraComponent* Camera, float FirstPersonFieldOfView = 74.f, float FirstPersonScale = 0.2f);

	/** Weapons and gadgets held by the owner render like the first-person body. */
	UFUNCTION(BlueprintCallable, Category = "Verse|Anim")
	static void MarkFirstPerson(UPrimitiveComponent* Component);

	/** Undo `ConfigureOwnerView` when the pawn is viewed by somebody else (kill cam, spectator). */
	UFUNCTION(BlueprintCallable, Category = "Verse|Anim")
	static void ConfigureThirdPerson(USkeletalMeshComponent* FirstPersonBody, USkeletalMeshComponent* WorldBody);
};

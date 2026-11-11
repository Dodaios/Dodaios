#pragma once

#include "Abilities/VerseCloak.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"

#include "VerseSovereignBody.generated.h"

class ACharacter;
class USkeletalMesh;

/**
 * The Sovereign as the person's body (docs/verse/sovereign.md, parity Z-02): the user's own
 * design, `SK_Sovereign`, exported from the same Blender builder as the three.js skin
 * (`art/verse/characters/sovereign.py`) and imported onto `SKEL_Verse_Human` plus its six
 * cloak bones.
 *
 * `Dress` puts it on a character's mesh with `UVerseAnimInstance` driven like the three.js
 * actor (`actors/actor.ts`): the idle clip while standing, the walk clip timed to the floor
 * speed (time scale = speed / 1.4 m/s, backwards when walking backwards). Every frame the
 * cloak springs (`VerseCloak::FSim`) swing the cloak bones as `actors/cloak.ts` does.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSEABILITIES_API UVerseSovereignBody : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseSovereignBody();

	static const TCHAR* MeshPath;
	/** Walk speed the walk clip is authored for, m/s (`characters.json` skeletons.M.walkSpeed). */
	static constexpr float ClipWalkSpeed = 1.4f;
	/** Above this floor speed (m/s) the body walks (the three.js actor's DRIVE_WALK_ABOVE). */
	static constexpr float WalkAbove = 0.2f;

	/**
	 * Wear the Sovereign on `Character`'s mesh: mesh, animation, cloak. Once per character; later
	 * calls return the same component. Null when `SK_Sovereign` is not in the build.
	 */
	static UVerseSovereignBody* Dress(ACharacter* Character);

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	const VerseCloak::FSim& GetCloak() const { return Cloak; }
	/** True while the walk clip plays. */
	bool IsWalking() const { return bWalking; }

	/**
	 * The cloak rotation of one segment in the mesh's component space for `Angles` (radians).
	 * The mesh faces +Y in its own space (coordinates.md 3.3), so +X is the body's left.
	 */
	static FQuat SegmentRotation(const VerseCloak::FAngles& Angles);

private:
	void Animate(float DeltaTime);

	VerseCloak::FSim Cloak;
	float ClipTime = 0.f;
	bool bWalking = false;
};

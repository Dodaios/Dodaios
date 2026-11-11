#pragma once

#include "Components/ActorComponent.h"
#include "CoreMinimal.h"

#include "VerseCrewBody.generated.h"

class AVerseCrewPawn;
class USkeletalMesh;
enum class EVerseCrewActivity : uint8;

/**
 * A crew member's body as the three.js Verse draws it (`actors/ActorsLayer.tsx`, `actor.ts`,
 * `look.ts`): officers wear the officer uniform (SK_Commander_M/F, the three.js SK_Officer_M/F),
 * technicians the coverall (SK_Crew_M/F), picked by `hash32(id) % 2` like `library.model`; the
 * rank's tier and plate dress it (`VerseRanks::ApplyLook`; technicians wear the deck tier), and
 * the activity plays its crew clip (`clips.ts`). Replaces the crew pawn's test body.
 */
UCLASS()
class VERSE_API UVerseCrewBody : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseCrewBody();

	/** Dresses the pawn once (later calls return the same component); null without the meshes. */
	static UVerseCrewBody* Dress(AVerseCrewPawn* Pawn);

	/** The body mesh three.js would pick for this member. */
	static USkeletalMesh* MeshFor(const AVerseCrewPawn& Pawn);
	/** The crew clip of an activity (`clips.ts` with the Unreal clip names). */
	static FName ClipFor(EVerseCrewActivity Activity);

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	/** One step of the clip and the look (tests drive it). */
	void Animate(float DeltaTime);

	FName GetClip() const { return Clip; }
	/** The rank the body last wore. */
	const FString& GetDressedRank() const { return DressedRank; }

	/** Speed the walk clip was authored at, m/s (`A_Crew_Walk`). */
	static constexpr float ClipWalkSpeed = 1.4f;
	static constexpr float WalkAbove = 0.2f;

private:
	void Redress(AVerseCrewPawn& Pawn);

	FString DressedRank;
	FName Clip;
	float ClipTime = 0.f;
	bool bWalking = false;
	FVector LastLocation = FVector::ZeroVector;
	bool bHasLast = false;
};

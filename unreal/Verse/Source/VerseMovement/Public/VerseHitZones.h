#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

class UPhysicsAsset;
class USkeletalMesh;
class UPrimitiveComponent;
struct FHitResult;

/**
 * Bone to EVerseHitZone (combat-state.md 5: "the physics body hit maps to EVerseHitZone through
 * a bone table in the character's physics asset"; art-pipeline.md 12.1 bone names). The hit
 * bodies are the physics asset's bodies on the character mesh, so stance and lean move them.
 */
namespace VerseHitZones
{
	/** The zone of one bone of SKEL_Verse_Human by name; None for bones without a zone. */
	VERSEMOVEMENT_API EVerseHitZone ZoneForBoneName(FName Bone);

	/** Like ZoneForBoneName, but walks up the mesh's bone parents until a bone has a zone. */
	VERSEMOVEMENT_API EVerseHitZone ZoneForBone(const USkeletalMesh* Mesh, FName Bone);

	/**
	 * The table of a physics asset: one entry per body. False (OutError names the body) when a
	 * body maps to no zone, so a new rig cannot silently lose a zone.
	 */
	VERSEMOVEMENT_API bool BuildTable(const UPhysicsAsset* Physics, const USkeletalMesh* Mesh, TMap<FName, EVerseHitZone>& OutTable, FString& OutError);

	/** The zone a VerseHitBody trace hit: a mesh body by bone, the prone body box as Leg. */
	VERSEMOVEMENT_API EVerseHitZone ZoneForHit(const FHitResult& Hit);
}

#pragma once

#include "CoreMinimal.h"

/**
 * `SKEL_Verse_Human`: the frozen bone names of art-pipeline.md 12.1 and the
 * clip names of the WP13 catalogue. The Python twin is
 * `art/verse/characters/fps/skeleton.py` / `catalogue.py`;
 * `tests/verse/test_unreal_characters.py` checks both lists match.
 */
namespace VerseHuman
{
	inline constexpr int32 MaxBones = 200;
	inline constexpr int32 MaxInfluences = 8;
	inline const TCHAR* SkeletonPath = TEXT("/Game/Verse/Characters/Rig/SKEL_Verse_Human.SKEL_Verse_Human");
	inline const TCHAR* PhysicsPath = TEXT("/Game/Verse/Characters/Rig/PHYS_Verse_Human.PHYS_Verse_Human");
	inline const TCHAR* IKRigPath = TEXT("/Game/Verse/Characters/Rig/IKRig_Verse_Human.IKRig_Verse_Human");

	/** (bone, parent) in hierarchy order; the root's parent is NAME_None. */
	VERSEMOVEMENT_API TConstArrayView<TPair<FName, FName>> Bones();

	/** Lean and aim offsets spread over three spine bones: (bone, share), shares sum to 1. */
	VERSEMOVEMENT_API TConstArrayView<TPair<FName, float>> SpineShares();

	/** Every clip the WP13 catalogue ships. */
	VERSEMOVEMENT_API TConstArrayView<const TCHAR*> ClipNames();

	/** /Game/Verse/Animations/<Group>/<Clip>.<Clip> for a catalogue clip name. */
	VERSEMOVEMENT_API FString ClipPath(const FString& Clip);

	/** Every character mesh: /Game/Verse/Characters/<Uniform>/<Mesh>.<Mesh>. */
	VERSEMOVEMENT_API TConstArrayView<const TCHAR*> MeshPaths();

	/** Finisher phase markers (combat-state.md 7.4): name and seconds. */
	VERSEMOVEMENT_API TConstArrayView<TPair<FName, float>> FinisherMarkers();

	/**
	 * Reference `SOCKET_Support` (off-hand IK target) in the weapon's root
	 * frame, cm, for the rifle and pistol clips (`fps/grip_reference.json`).
	 * The runtime prefers the attached weapon's real socket.
	 */
	VERSEMOVEMENT_API FVector ReferenceSupport(bool bPistol);
}

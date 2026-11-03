#pragma once

#include "CoreMinimal.h"

/**
 * Pose math of the WP13 animation runtime, free of engine pose types so the
 * automation tests drive it directly. Component space is the skeletal mesh
 * component's (Z up). `Parents[i] < i` for every bone (hierarchy order).
 */
namespace VerseAnim
{
	VERSEMOVEMENT_API void LocalToComponent(TConstArrayView<int32> Parents, TConstArrayView<FTransform> Local, TArray<FTransform>& OutCS);

	VERSEMOVEMENT_API void ComponentToLocal(TConstArrayView<int32> Parents, TConstArrayView<FTransform> CS, TArray<FTransform>& OutLocal);

	/**
	 * Analytic two-bone IK in component space: moves `End` to `Target` by
	 * rotating `Upper` and `Lower`, keeping the current bend plane. Lengths are
	 * kept; a target out of reach is clamped onto the reachable sphere.
	 * `End` keeps its component rotation when `bKeepEndRotation`.
	 * Returns the remaining distance from `End` to `Target` (cm).
	 */
	VERSEMOVEMENT_API float SolveTwoBone(FTransform& Upper, FTransform& Lower, FTransform& End, const FVector& Target, bool bKeepEndRotation = true);

	/**
	 * Rotate bone `Bone` by `Delta` (a component-space rotation about the
	 * bone's own position); updates `Local[Bone]` from the current `CS`.
	 * Call `LocalToComponent` again before reading descendants.
	 */
	VERSEMOVEMENT_API void RotateInComponent(TConstArrayView<int32> Parents, TArray<FTransform>& Local, TArray<FTransform>& CS, int32 Bone, const FQuat& Delta);

	/**
	 * Spread `AngleDeg` about the component axis `Axis` over spine bones with
	 * shares summing to 1 (lean, aim pitch). Rewrites `Local` and `CS`.
	 */
	VERSEMOVEMENT_API void SpreadRotation(TConstArrayView<int32> Parents, TArray<FTransform>& Local, TArray<FTransform>& CS,
		TConstArrayView<int32> SpineBones, TConstArrayView<float> Shares, const FVector& Axis, float AngleDeg);

	/** Foot placement on uneven floor (WP13.10, A13.4). */
	struct FFootInput
	{
		int32 Thigh = INDEX_NONE;
		int32 Calf = INDEX_NONE;
		int32 Foot = INDEX_NONE;
		/** Floor height under the foot relative to the animated floor (Z = 0), cm. */
		float FloorOffset = 0.f;
		/** Floor normal under the foot, component space. */
		FVector FloorNormal = FVector::UpVector;
	};

	/**
	 * Drop the pelvis by the lower foot's offset (never raise it), then IK each
	 * leg so its foot follows its floor and tilt the foot onto the floor normal.
	 * Returns the pelvis drop (cm, <= 0).
	 */
	/**
	 * Floor offset of one foot from two probes, under the ankle (offset and
	 * normal) and under the ball (`AnkleToBall` apart, component space). On one
	 * plane both agree and the ankle's offset stands; where the ball's floor
	 * rises above the ankle's plane (a step edge) the ankle is raised so the
	 * ball stays on it.
	 */
	VERSEMOVEMENT_API float FootFloorOffset(float AnkleOffset, const FVector& AnkleNormal, float BallOffset, const FVector& AnkleToBall);

	VERSEMOVEMENT_API float SolveFeet(TConstArrayView<int32> Parents, TArray<FTransform>& Local, TArray<FTransform>& CS, int32 Pelvis,
		TArrayView<FFootInput> Feet, float MaxDrop = 60.f);
}

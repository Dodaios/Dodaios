#pragma once

#include "Anim/VerseAnimTypes.h"
#include "Animation/AnimCurveTypes.h"
#include "Animation/AttributesRuntime.h"
#include "BoneContainer.h"
#include "BonePose.h"
#include "CoreMinimal.h"

/** Compact-pose indices of the bones the runtime touches, plus parents and the upper-body mask. */
struct VERSEMOVEMENT_API FVerseAnimBones
{
	TArray<int32> Parents;
	TArray<float> UpperMask; // 1 for arms, neck, head, camera and the hand IK bones
	int32 Root = INDEX_NONE;
	int32 Hips = INDEX_NONE;
	int32 Spine[3] = {INDEX_NONE, INDEX_NONE, INDEX_NONE};
	float SpineShare[3] = {0.25f, 0.35f, 0.40f};
	int32 Head = INDEX_NONE;
	int32 UpperArmL = INDEX_NONE;
	int32 LowerArmL = INDEX_NONE;
	int32 HandL = INDEX_NONE;
	int32 WeaponR = INDEX_NONE;
	int32 Thigh[2] = {INDEX_NONE, INDEX_NONE};
	int32 Calf[2] = {INDEX_NONE, INDEX_NONE};
	int32 Foot[2] = {INDEX_NONE, INDEX_NONE};

	void Build(const FBoneContainer& Bones);
	bool IsValid() const { return Hips != INDEX_NONE && HandL != INDEX_NONE && WeaponR != INDEX_NONE; }
};

/** Diagnostics of one evaluation (tests, cost report). */
struct VERSEMOVEMENT_API FVerseAnimEvalInfo
{
	int32 Samples = 0;
	float OffHandError = 0.f; // cm, after IK
	float OffHandCurve = 1.f;
	float PelvisDrop = 0.f;
};

/**
 * Game-thread state machine: turns inputs into the frame the evaluator
 * samples (locomotion blend, stance crossfades, jump/fall/land, slide,
 * mantle, prone transitions, the weapon layer and actions).
 */
class VERSEMOVEMENT_API FVerseAnimStateMachine
{
public:
	/** Lean that a full input (|Lean| = 1) puts on the three spine bones, degrees. */
	static constexpr float LeanMaxDeg = 30.f;
	static constexpr float StanceBlendRate = 6.f; // 1/s
	static constexpr float SprintBlendRate = 6.f; // 1/s
	static constexpr float LandSeconds = 0.4f;

	void Step(const FVerseAnimInputs& In, float DeltaSeconds, const FVerseAnimClipSet& Clips, FVerseAnimFrame& Out);
	EVerseLocoState GetState() const { return State; }
	float GetStateTime() const { return StateTime; }
	void Reset() { *this = FVerseAnimStateMachine(); }

private:
	void Enter(EVerseLocoState NewState);

	EVerseLocoState State = EVerseLocoState::Ground;
	float StateTime = 0.f;
	float StanceWeight[FVerseAnimClipSet::NumStances] = {1.f, 0.f, 0.f};
	float Phase = 0.f;
	float SprintPhase = 0.f;
	float SprintAlpha = 0.f;
	float MoveAlpha = 0.f;
	float Heading = 0.f;
	float IdleTime = 0.f;
	EVerseStance LastStance = EVerseStance::Stand;
	bool bWasAirborne = false;
	bool bStarted = false;

public:
	/** Time base of the idle and weapon idle loops (seconds since start). */
	float GetIdleTime() const { return IdleTime; }
};

namespace VerseAnim
{
	/**
	 * Evaluate one frame into `Pose` (local space, compact bones of `Bones`).
	 * `IdleTime` is the loop clock of idle and weapon-idle clips.
	 */
	VERSEMOVEMENT_API void EvaluateFrame(const FVerseAnimFrame& Frame, float IdleTime, const FVerseAnimBones& Bones,
		FCompactPose& Pose, FBlendedCurve& Curve, UE::Anim::FStackAttributeContainer& Attributes,
		FVerseAnimEvalInfo* Info = nullptr);

	/** Sample one clip at `Time` into `Pose` (reference pose when `Clip` is null). */
	VERSEMOVEMENT_API void SampleClip(const UAnimSequence* Clip, double Time, bool bLoop, FCompactPose& Pose,
		FBlendedCurve& Curve, UE::Anim::FStackAttributeContainer& Attributes);

	/** Sign so that a positive rotation about `Axis` turns `From` towards `To` (component handedness). */
	VERSEMOVEMENT_API float TurnSign(const FVector& Axis, const FVector& From, const FVector& To);

	/** Component-space frame of `SKEL_Verse_Human` meshes: forward +Y, up +Z, right -X. */
	inline const FVector MeshForward(0.0, 1.0, 0.0);
	inline const FVector MeshRight(-1.0, 0.0, 0.0);
}

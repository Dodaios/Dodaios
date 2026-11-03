#include "Anim/VerseAnimRuntime.h"

#include "Anim/VerseAnimMath.h"
#include "Anim/VerseHumanSkeleton.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationPoseData.h"
#include "Animation/AttributesRuntime.h"
#include "AnimationRuntime.h"
#include "BoneContainer.h"
#include "BonePose.h"

namespace
{
	const UAnimSequence* LoadClip(const TCHAR* Name, TArray<FString>* Missing = nullptr)
	{
		const FString Path = VerseHuman::ClipPath(Name);
		const UAnimSequence* Clip = LoadObject<UAnimSequence>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
		if (!Clip && Missing)
		{
			Missing->Add(Path);
		}
		return Clip;
	}

	const TCHAR* StanceName(int32 Stance)
	{
		static const TCHAR* Names[] = {TEXT("Stand"), TEXT("Crouch"), TEXT("Prone")};
		return Names[Stance];
	}

	const TCHAR* HeadingName(int32 Heading)
	{
		static const TCHAR* Names[] = {TEXT("F"), TEXT("FL"), TEXT("L"), TEXT("BL"), TEXT("B"), TEXT("BR"), TEXT("R"), TEXT("FR")};
		return Names[Heading];
	}

	float ClipLength(const UAnimSequence* Clip)
	{
		return Clip ? FMath::Max(Clip->GetPlayLength(), 1e-3f) : 1.f;
	}

	int32 StanceIndex(EVerseStance Stance)
	{
		switch (Stance)
		{
		case EVerseStance::Crouch:
		case EVerseStance::Slide:
			return 1;
		case EVerseStance::Prone:
			return 2;
		default:
			return 0;
		}
	}

	float Approach(float Value, float Target, float Step)
	{
		return Value < Target ? FMath::Min(Value + Step, Target) : FMath::Max(Value - Step, Target);
	}
}

// ------------------------------------------------------------------- clip set

void FVerseAnimClipSet::Load()
{
	for (int32 S = 0; S < NumStances; ++S)
	{
		Idle[S] = LoadClip(*FString::Printf(TEXT("A_%s_Idle"), StanceName(S)));
		for (int32 H = 0; H < NumHeadings; ++H)
		{
			Move[S][H] = LoadClip(*FString::Printf(TEXT("A_%s_Move_%s"), StanceName(S), HeadingName(H)));
		}
	}
	Sprint = LoadClip(TEXT("A_Sprint_F"));
	JumpStart = LoadClip(TEXT("A_Jump_Start"));
	Fall = LoadClip(TEXT("A_Fall_Loop"));
	Land = LoadClip(TEXT("A_Land"));
	Slide = LoadClip(TEXT("A_Slide"));
	MantleLow = LoadClip(TEXT("A_Mantle_Low"));
	MantleHigh = LoadClip(TEXT("A_Mantle_High"));
	ProneEnter = LoadClip(TEXT("A_Prone_Enter"));
	ProneExit = LoadClip(TEXT("A_Prone_Exit"));
	const TCHAR* Classes[] = {nullptr, TEXT("Rifle"), TEXT("Pistol"), TEXT("Knife")};
	for (int32 W = 1; W < 4; ++W)
	{
		FWeapon& Set = Weapons[W];
		const FString C = Classes[W];
		Set.Idle = LoadClip(*FString::Printf(TEXT("A_%s_Idle"), *C));
		if (W == 3)
		{
			Set.Strike = LoadClip(TEXT("A_Knife_Strike"));
			Set.Equip = LoadClip(TEXT("A_Knife_Equip"));
			Set.Holster = LoadClip(TEXT("A_Knife_Holster"));
			continue;
		}
		Set.Ads = LoadClip(*FString::Printf(TEXT("A_%s_ADS"), *C));
		Set.Fire = LoadClip(*FString::Printf(TEXT("A_%s_Fire"), *C));
		Set.ReloadTactical = LoadClip(*FString::Printf(TEXT("A_%s_Reload_Tactical"), *C));
		Set.ReloadEmpty = LoadClip(*FString::Printf(TEXT("A_%s_Reload_Empty"), *C));
		Set.Equip = LoadClip(*FString::Printf(TEXT("A_%s_Equip"), *C));
		Set.Holster = LoadClip(*FString::Printf(TEXT("A_%s_Holster"), *C));
	}
}

bool FVerseAnimClipSet::IsComplete(TArray<FString>* OutMissing) const
{
	bool bOk = true;
	auto Check = [&](const UAnimSequence* Clip, const TCHAR* What)
	{
		if (!Clip)
		{
			bOk = false;
			if (OutMissing)
			{
				OutMissing->Add(What);
			}
		}
	};
	for (int32 S = 0; S < NumStances; ++S)
	{
		Check(Idle[S], StanceName(S));
		for (int32 H = 0; H < NumHeadings; ++H)
		{
			Check(Move[S][H], *FString::Printf(TEXT("%s move %s"), StanceName(S), HeadingName(H)));
		}
	}
	Check(Sprint, TEXT("sprint"));
	Check(JumpStart, TEXT("jump"));
	Check(Fall, TEXT("fall"));
	Check(Land, TEXT("land"));
	Check(Slide, TEXT("slide"));
	Check(MantleLow, TEXT("mantle low"));
	Check(MantleHigh, TEXT("mantle high"));
	Check(ProneEnter, TEXT("prone enter"));
	Check(ProneExit, TEXT("prone exit"));
	for (int32 W = 1; W < 4; ++W)
	{
		Check(Weapons[W].Idle, TEXT("weapon idle"));
	}
	return bOk;
}

const UAnimSequence* FVerseAnimClipSet::ActionClip(EVerseAnimWeapon Weapon, EVerseAnimAction Action) const
{
	const FWeapon& W = Weapons[static_cast<int32>(Weapon)];
	switch (Action)
	{
	case EVerseAnimAction::Fire:
		return W.Fire;
	case EVerseAnimAction::ReloadTactical:
		return W.ReloadTactical;
	case EVerseAnimAction::ReloadEmpty:
		return W.ReloadEmpty;
	case EVerseAnimAction::Equip:
		return W.Equip;
	case EVerseAnimAction::Holster:
		return W.Holster;
	case EVerseAnimAction::Strike:
		return W.Strike;
	default:
		return nullptr;
	}
}

// ---------------------------------------------------------------------- bones

void FVerseAnimBones::Build(const FBoneContainer& Container)
{
	const int32 Num = Container.GetCompactPoseNumBones();
	Parents.SetNum(Num);
	UpperMask.Init(0.f, Num);
	for (int32 i = 0; i < Num; ++i)
	{
		Parents[i] = Container.GetParentBoneIndex(FCompactPoseBoneIndex(i)).GetInt();
	}
	auto Find = [&Container](const TCHAR* Name) -> int32
	{
		const int32 MeshIndex = Container.GetPoseBoneIndexForBoneName(FName(Name));
		if (MeshIndex == INDEX_NONE)
		{
			return INDEX_NONE;
		}
		return Container.MakeCompactPoseIndex(FMeshPoseBoneIndex(MeshIndex)).GetInt();
	};
	Root = Find(TEXT("Root"));
	Hips = Find(TEXT("Hips"));
	const TConstArrayView<TPair<FName, float>> Shares = VerseHuman::SpineShares();
	for (int32 k = 0; k < 3 && k < Shares.Num(); ++k)
	{
		Spine[k] = Find(*Shares[k].Key.ToString());
		SpineShare[k] = Shares[k].Value;
	}
	Head = Find(TEXT("Head"));
	UpperArmL = Find(TEXT("UpperArm_L"));
	LowerArmL = Find(TEXT("LowerArm_L"));
	HandL = Find(TEXT("Hand_L"));
	WeaponR = Find(TEXT("Weapon_R"));
	const TCHAR* Sides[] = {TEXT("L"), TEXT("R")};
	for (int32 s = 0; s < 2; ++s)
	{
		Thigh[s] = Find(*FString::Printf(TEXT("Thigh_%s"), Sides[s]));
		Calf[s] = Find(*FString::Printf(TEXT("Calf_%s"), Sides[s]));
		Foot[s] = Find(*FString::Printf(TEXT("Foot_%s"), Sides[s]));
	}
	const int32 LayerRoots[] = {Find(TEXT("Clavicle_L")), Find(TEXT("Clavicle_R")), Find(TEXT("Neck")), Find(TEXT("IK_Hand_Root"))};
	for (int32 i = 0; i < Num; ++i)
	{
		for (int32 B = i; B != INDEX_NONE; B = Parents[B])
		{
			bool bHit = false;
			for (int32 R : LayerRoots)
			{
				bHit |= (B == R && R != INDEX_NONE);
			}
			if (bHit)
			{
				UpperMask[i] = 1.f;
				break;
			}
		}
	}
}

// -------------------------------------------------------------- state machine

void FVerseAnimStateMachine::Enter(EVerseLocoState NewState)
{
	State = NewState;
	StateTime = 0.f;
}

void FVerseAnimStateMachine::Step(const FVerseAnimInputs& In, float Dt, const FVerseAnimClipSet& Clips, FVerseAnimFrame& Out)
{
	Dt = FMath::Max(Dt, 0.f);
	if (!bStarted)
	{
		LastStance = In.Stance;
		const int32 S0 = StanceIndex(In.Stance);
		for (int32 S = 0; S < FVerseAnimClipSet::NumStances; ++S)
		{
			StanceWeight[S] = S == S0 ? 1.f : 0.f;
		}
		bStarted = true;
	}
	IdleTime += Dt;
	StateTime += Dt;
	const int32 Target = StanceIndex(In.Stance);

	// Transitions, highest priority first.
	if (In.bMantling)
	{
		if (State != EVerseLocoState::Mantle)
		{
			Enter(EVerseLocoState::Mantle);
		}
	}
	else if (In.Stance == EVerseStance::Slide)
	{
		if (State != EVerseLocoState::Slide)
		{
			Enter(EVerseLocoState::Slide);
		}
	}
	else if (In.bAirborne)
	{
		if (!bWasAirborne || (State != EVerseLocoState::JumpStart && State != EVerseLocoState::Fall))
		{
			Enter(EVerseLocoState::JumpStart);
		}
		if (State == EVerseLocoState::JumpStart && StateTime >= ClipLength(Clips.JumpStart))
		{
			Enter(EVerseLocoState::Fall);
		}
	}
	else if (bWasAirborne)
	{
		Enter(EVerseLocoState::Land);
	}
	else if (LastStance != EVerseStance::Prone && In.Stance == EVerseStance::Prone)
	{
		Enter(EVerseLocoState::ProneEnter);
	}
	else if (LastStance == EVerseStance::Prone && In.Stance != EVerseStance::Prone)
	{
		Enter(EVerseLocoState::ProneExit);
	}
	else if (State == EVerseLocoState::Mantle || State == EVerseLocoState::Slide)
	{
		Enter(EVerseLocoState::Ground);
	}
	if ((State == EVerseLocoState::Land && StateTime >= LandSeconds)
		|| (State == EVerseLocoState::ProneEnter && StateTime >= ClipLength(Clips.ProneEnter))
		|| (State == EVerseLocoState::ProneExit && StateTime >= ClipLength(Clips.ProneExit)))
	{
		Enter(EVerseLocoState::Ground);
	}
	bWasAirborne = In.bAirborne && !In.bMantling;
	LastStance = In.Stance;

	// Stance weights: snap through the prone transition clips, crossfade otherwise.
	const bool bProneClip = State == EVerseLocoState::ProneEnter || State == EVerseLocoState::ProneExit;
	float Sum = 0.f;
	for (int32 S = 0; S < FVerseAnimClipSet::NumStances; ++S)
	{
		const float Goal = S == Target ? 1.f : 0.f;
		StanceWeight[S] = bProneClip ? Goal : Approach(StanceWeight[S], Goal, StanceBlendRate * Dt);
		Sum += StanceWeight[S];
	}
	for (int32 S = 0; S < FVerseAnimClipSet::NumStances; ++S)
	{
		Out.StanceWeight[S] = Sum > 0.f ? StanceWeight[S] / Sum : (S == Target ? 1.f : 0.f);
	}

	// Ground locomotion: heading, idle -> move alpha, phase at ground speed / clip speed.
	const FVector2D Planar(In.LocalVelocity.X, In.LocalVelocity.Y);
	const float Speed = Planar.Size();
	if (Speed > 5.f)
	{
		Heading = FMath::RadiansToDegrees(FMath::Atan2(-In.LocalVelocity.Y, In.LocalVelocity.X));
	}
	float ClipSpeed = 0.f;
	float Cycle = 0.f;
	for (int32 S = 0; S < FVerseAnimClipSet::NumStances; ++S)
	{
		ClipSpeed += Out.StanceWeight[S] * Clips.MoveSpeed[S];
		Cycle += Out.StanceWeight[S] * ClipLength(Clips.Move[S][0]);
	}
	MoveAlpha = Approach(MoveAlpha, FMath::SmoothStep(0.f, 0.5f * ClipSpeed, Speed), 8.f * Dt);
	Phase = FMath::Fmod(Phase + Dt * (Speed / FMath::Max(ClipSpeed, 1.f)) / FMath::Max(Cycle, 0.05f), 1.f);
	const bool bSprint = In.bSprinting && Target == 0 && State == EVerseLocoState::Ground;
	SprintAlpha = Approach(SprintAlpha, bSprint ? 1.f : 0.f, SprintBlendRate * Dt);
	SprintPhase = FMath::Fmod(SprintPhase + Dt * (Speed / Clips.SprintSpeed) / ClipLength(Clips.Sprint), 1.f);
	for (int32 S = 0; S < FVerseAnimClipSet::NumStances; ++S)
	{
		Out.StanceClips[S].Idle = Clips.Idle[S];
		for (int32 H = 0; H < FVerseAnimClipSet::NumHeadings; ++H)
		{
			Out.StanceClips[S].Move[H] = Clips.Move[S][H];
			Out.StanceClips[S].MoveLength[H] = ClipLength(Clips.Move[S][H]);
		}
	}
	Out.SprintClip = Clips.Sprint;
	Out.SprintLength = ClipLength(Clips.Sprint);
	Out.MovePhase = Phase;
	Out.MoveAlpha = MoveAlpha;
	Out.HeadingDeg = Heading;
	Out.SprintAlpha = SprintAlpha;
	Out.SprintPhase = SprintPhase;

	// State clip over locomotion.
	Out.Special = nullptr;
	Out.SpecialWeight = 0.f;
	Out.SpecialTime = StateTime;
	Out.bSpecialLoop = false;
	switch (State)
	{
	case EVerseLocoState::JumpStart:
		Out.Special = Clips.JumpStart;
		Out.SpecialWeight = 1.f;
		break;
	case EVerseLocoState::Fall:
		Out.Special = Clips.Fall;
		Out.SpecialWeight = 1.f;
		Out.bSpecialLoop = true;
		break;
	case EVerseLocoState::Land:
		Out.Special = Clips.Land;
		Out.SpecialWeight = 1.f - FMath::SmoothStep(0.5f * LandSeconds, LandSeconds, StateTime);
		break;
	case EVerseLocoState::Slide:
		Out.Special = Clips.Slide;
		Out.SpecialWeight = 1.f;
		break;
	case EVerseLocoState::Mantle:
		Out.Special = In.bMantleHigh ? Clips.MantleHigh : Clips.MantleLow;
		Out.SpecialWeight = 1.f;
		break;
	case EVerseLocoState::ProneEnter:
		Out.Special = Clips.ProneEnter;
		Out.SpecialWeight = 1.f;
		break;
	case EVerseLocoState::ProneExit:
		Out.Special = Clips.ProneExit;
		Out.SpecialWeight = 1.f;
		break;
	default:
		break;
	}

	// Upper-body weapon layer.
	Out.Weapon = In.Weapon;
	Out.WeaponIdle = Clips.Weapons[static_cast<int32>(In.Weapon)].Idle;
	Out.WeaponAds = Clips.Weapons[static_cast<int32>(In.Weapon)].Ads;
	Out.Ads = FMath::Clamp(In.Ads, 0.f, 1.f);
	const bool bOwnArms = State == EVerseLocoState::Mantle || bProneClip;
	Out.UpperAlpha = In.Weapon == EVerseAnimWeapon::None || bOwnArms ? 0.f : 1.f - SprintAlpha;
	Out.Action = In.Action == EVerseAnimAction::None ? nullptr : Clips.ActionClip(In.Weapon, In.Action);
	Out.ActionTime = In.ActionTime;
	const float ActionLength = ClipLength(Out.Action);
	Out.ActionWeight = Out.Action && In.ActionTime < ActionLength
		? FMath::Min(1.f, (ActionLength - In.ActionTime) / 0.08f) * FMath::Min(1.f, In.ActionTime / 0.04f + 0.25f)
		: 0.f;

	// Procedural layers.
	Out.Lean = FMath::Clamp(In.Lean, -1.f, 1.f);
	Out.AimPitch = FMath::Clamp(In.AimPitch, -70.f, 70.f);
	Out.bHasSupport = In.Weapon == EVerseAnimWeapon::Rifle || In.Weapon == EVerseAnimWeapon::Pistol;
	Out.OffHandAlpha = Out.bHasSupport && !bOwnArms ? 1.f : 0.f;
	// Foot IK on the ground while standing or crouching, idle or moving (the probes follow the
	// stride); off at a sprint and while prone, whose body lies along the floor rather than on its feet.
	Out.bFootIK = State == EVerseLocoState::Ground && Target != 2 && SprintAlpha < 0.5f;
	Out.Override = nullptr;
}

// ------------------------------------------------------------------ evaluator

namespace VerseAnim
{
float TurnSign(const FVector& Axis, const FVector& From, const FVector& To)
{
	const FVector Turned = FQuat(Axis.GetSafeNormal(), 0.1).RotateVector(From);
	return FVector::DotProduct(Turned - From, To) >= 0.0 ? 1.f : -1.f;
}

void SampleClip(const UAnimSequence* Clip, double Time, bool bLoop, FCompactPose& Pose, FBlendedCurve& Curve,
	UE::Anim::FStackAttributeContainer& Attributes)
{
	if (!Clip)
	{
		Pose.ResetToRefPose();
		return;
	}
	const double Length = FMath::Max<double>(Clip->GetPlayLength(), 1e-3);
	Time = bLoop ? FMath::Fmod(FMath::Max(Time, 0.0), Length) : FMath::Clamp(Time, 0.0, Length);
	FAnimationPoseData Data(Pose, Curve, Attributes);
	const FAnimExtractContext Context(Time, false, FDeltaTimeRecord(), bLoop);
	Clip->GetAnimationPose(Data, Context);
}

namespace
{
	struct FScratch
	{
		FCompactPose Pose;
		FBlendedCurve Curve;
		UE::Anim::FStackAttributeContainer Attributes;

		explicit FScratch(const FBoneContainer& Bones)
		{
			Pose.SetBoneContainer(&Bones);
			Curve.InitFrom(Bones);
		}

		FAnimationPoseData Data() { return FAnimationPoseData(Pose, Curve, Attributes); }
	};

	void Blend(FScratch& Into, FScratch& Other, float WeightOfOther)
	{
		if (WeightOfOther <= 0.f)
		{
			return;
		}
		if (WeightOfOther >= 1.f)
		{
			Into.Pose.CopyBonesFrom(Other.Pose);
			Into.Curve.CopyFrom(Other.Curve);
			return;
		}
		FAnimationPoseData A = Into.Data();
		FAnimationPoseData B = Other.Data();
		FScratch Out(Into.Pose.GetBoneContainer());
		FAnimationPoseData O = Out.Data();
		FAnimationRuntime::BlendTwoPosesTogether(A, B, 1.f - WeightOfOther, O);
		Into.Pose.CopyBonesFrom(Out.Pose);
		Into.Curve.CopyFrom(Out.Curve);
	}

	void Sample(FScratch& Into, const UAnimSequence* Clip, double Time, bool bLoop, int32& Samples)
	{
		SampleClip(Clip, Time, bLoop, Into.Pose, Into.Curve, Into.Attributes);
		Samples += Clip ? 1 : 0;
	}
}

void EvaluateFrame(const FVerseAnimFrame& F, float IdleTime, const FVerseAnimBones& B, FCompactPose& Pose,
	FBlendedCurve& Curve, UE::Anim::FStackAttributeContainer& Attributes, FVerseAnimEvalInfo* Info)
{
	FMemMark Mark(FMemStack::Get());
	const FBoneContainer& Bones = Pose.GetBoneContainer();
	FVerseAnimEvalInfo Local;
	FVerseAnimEvalInfo& Out = Info ? *Info : Local;
	Out = FVerseAnimEvalInfo();
	FScratch Acc(Bones);

	if (F.Override)
	{
		Sample(Acc, F.Override, F.OverrideTime, F.bOverrideLoop, Out.Samples);
		Pose.CopyBonesFrom(Acc.Pose);
		Curve.CopyFrom(Acc.Curve);
		return;
	}

	// 1. Ground locomotion per stance: idle -> two neighbouring headings.
	float Accumulated = 0.f;
	FScratch StancePose(Bones);
	FScratch Tmp(Bones);
	for (int32 S = 0; S < FVerseAnimClipSet::NumStances; ++S)
	{
		const float W = F.StanceWeight[S];
		if (W <= 1e-3f || !F.StanceClips[S].Idle)
		{
			continue;
		}
		const FVerseAnimFrame::FStanceClips& C = F.StanceClips[S];
		Sample(StancePose, C.Idle, IdleTime, true, Out.Samples);
		if (F.MoveAlpha > 1e-3f)
		{
			const float H = FMath::Fmod(F.HeadingDeg + 360.f, 360.f) / 45.f;
			const int32 H0 = FMath::FloorToInt(H) % 8;
			const int32 H1 = (H0 + 1) % 8;
			const float Frac = H - FMath::FloorToFloat(H);
			FScratch Move(Bones);
			Sample(Move, C.Move[H0], F.MovePhase * C.MoveLength[H0], true, Out.Samples);
			if (Frac > 1e-3f)
			{
				Sample(Tmp, C.Move[H1], F.MovePhase * C.MoveLength[H1], true, Out.Samples);
				Blend(Move, Tmp, Frac);
			}
			Blend(StancePose, Move, F.MoveAlpha);
		}
		Accumulated += W;
		Blend(Acc, StancePose, Accumulated > 0.f ? W / Accumulated : 1.f);
	}
	if (Accumulated <= 0.f)
	{
		Acc.Pose.ResetToRefPose();
	}
	if (F.SprintAlpha > 1e-3f && F.SprintClip)
	{
		Sample(Tmp, F.SprintClip, F.SprintPhase * F.SprintLength, true, Out.Samples);
		Blend(Acc, Tmp, F.SprintAlpha);
	}
	if (F.Special && F.SpecialWeight > 1e-3f)
	{
		Sample(Tmp, F.Special, F.SpecialTime, F.bSpecialLoop, Out.Samples);
		Blend(Acc, Tmp, F.SpecialWeight);
	}

	// 2. Upper-body weapon layer (arms, neck, head, camera, hand IK bones), local space.
	float OffHandCurve = 1.f;
	if (F.UpperAlpha > 1e-3f && F.WeaponIdle)
	{
		FScratch Upper(Bones);
		Sample(Upper, F.WeaponIdle, IdleTime, true, Out.Samples);
		if (F.Ads > 1e-3f && F.WeaponAds)
		{
			Sample(Tmp, F.WeaponAds, IdleTime, true, Out.Samples);
			Blend(Upper, Tmp, F.Ads);
		}
		if (F.Action && F.ActionWeight > 1e-3f)
		{
			Sample(Tmp, F.Action, F.ActionTime, false, Out.Samples);
			bool bHasCurve = false;
			const float Value = Tmp.Curve.Get(FName(TEXT("OffHandIK")), bHasCurve, 1.f);
			OffHandCurve = bHasCurve ? FMath::Lerp(1.f, Value, F.ActionWeight) : 1.f;
			Blend(Upper, Tmp, F.ActionWeight);
		}
		for (const FCompactPoseBoneIndex Index : Acc.Pose.ForEachBoneIndex())
		{
			const float M = B.UpperMask.IsValidIndex(Index.GetInt()) ? B.UpperMask[Index.GetInt()] * F.UpperAlpha : 0.f;
			if (M > 0.f)
			{
				FTransform Result;
				Result.Blend(Acc.Pose[Index], Upper.Pose[Index], M);
				Acc.Pose[Index] = Result;
			}
		}
	}
	Out.OffHandCurve = OffHandCurve;

	// 3. Procedural layers in component space.
	const int32 Num = Acc.Pose.GetNumBones();
	TArray<FTransform> LocalT;
	TArray<FTransform> CS;
	LocalT.SetNum(Num);
	for (int32 i = 0; i < Num; ++i)
	{
		LocalT[i] = Acc.Pose[FCompactPoseBoneIndex(i)];
	}
	if (B.Root != INDEX_NONE)
	{
		LocalT[B.Root] = Bones.GetRefPoseTransform(FCompactPoseBoneIndex(B.Root));
	}
	LocalToComponent(B.Parents, LocalT, CS);
	const int32 Spine[3] = {B.Spine[0], B.Spine[1], B.Spine[2]};
	const float Shares[3] = {B.SpineShare[0], B.SpineShare[1], B.SpineShare[2]};
	if (!FMath::IsNearlyZero(F.Lean))
	{
		const float Sign = TurnSign(MeshForward, FVector::UpVector, MeshRight);
		SpreadRotation(B.Parents, LocalT, CS, MakeArrayView(Spine), MakeArrayView(Shares), MeshForward, Sign * F.Lean * FVerseAnimStateMachine::LeanMaxDeg);
	}
	if (!FMath::IsNearlyZero(F.AimPitch))
	{
		const float Sign = TurnSign(MeshRight, MeshForward, FVector::UpVector);
		SpreadRotation(B.Parents, LocalT, CS, MakeArrayView(Spine), MakeArrayView(Shares), MeshRight, Sign * F.AimPitch);
	}
	const float OffHand = F.OffHandAlpha * OffHandCurve;
	if (F.bHasSupport && OffHand > 1e-3f && B.IsValid() && B.UpperArmL != INDEX_NONE && B.LowerArmL != INDEX_NONE)
	{
		const FVector Target = (F.SupportInWeapon * CS[B.WeaponR]).GetLocation();
		const FVector Goal = FMath::Lerp(CS[B.HandL].GetLocation(), Target, OffHand);
		FTransform Upper = CS[B.UpperArmL];
		FTransform Lower = CS[B.LowerArmL];
		FTransform Hand = CS[B.HandL];
		SolveTwoBone(Upper, Lower, Hand, Goal, true);
		LocalT[B.UpperArmL] = Upper.GetRelativeTransform(CS[B.Parents[B.UpperArmL]]);
		LocalT[B.LowerArmL] = Lower.GetRelativeTransform(Upper);
		LocalT[B.HandL] = Hand.GetRelativeTransform(Lower);
		LocalToComponent(B.Parents, LocalT, CS);
		Out.OffHandError = OffHand >= 1.f ? FVector::Dist(CS[B.HandL].GetLocation(), Target) : 0.f;
	}
	if (F.bFootIK && B.Hips != INDEX_NONE)
	{
		VerseAnim::FFootInput Feet[2];
		for (int32 s = 0; s < 2; ++s)
		{
			Feet[s].Thigh = B.Thigh[s];
			Feet[s].Calf = B.Calf[s];
			Feet[s].Foot = B.Foot[s];
			Feet[s].FloorOffset = F.FloorOffset[s];
			Feet[s].FloorNormal = F.FloorNormal[s];
		}
		Out.PelvisDrop = SolveFeet(B.Parents, LocalT, CS, B.Hips, MakeArrayView(Feet));
	}
	if (F.bHideHead && B.Head != INDEX_NONE)
	{
		// Last, after every solver: nothing inverts this transform afterwards.
		LocalT[B.Head].SetScale3D(FVector::ZeroVector);
	}
	for (int32 i = 0; i < Num; ++i)
	{
		Acc.Pose[FCompactPoseBoneIndex(i)] = LocalT[i];
	}
	Pose.CopyBonesFrom(Acc.Pose);
	Curve.CopyFrom(Acc.Curve);
}
} // namespace VerseAnim

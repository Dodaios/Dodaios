#include "Anim/VerseAnimInstance.h"
#include "Anim/VerseFirstPerson.h"

#include "Anim/VerseAnimMath.h"
#include "Anim/VerseHumanSkeleton.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationPoseData.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "CollisionQueryParams.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "Movement/VerseMovementQuery.h"

const FName FVerseAnimInstanceProxy::FullBodySlot(TEXT("FullBody"));

namespace
{
	const FName SupportSocket(TEXT("SOCKET_Support"));

	/** A ledge higher than this over the feet plays `A_Mantle_High` (WP01: low 0.5-1.2 m, high 1.2-2.0 m). */
	constexpr double MantleHighAboveCm = 120.0;
	/** Top of the ledge probe over the feet; above WP01's 2.0 m maximum. */
	constexpr double MantleProbeTopCm = 210.0;
	/** How far past the capsule's front the ledge probe looks, cm. */
	constexpr double MantleProbeAheadCm = 35.0;

	const FName FootBones[] = {FName(TEXT("Foot_L")), FName(TEXT("Foot_R"))};
	const FName BallBones[] = {FName(TEXT("Ball_L")), FName(TEXT("Ball_R"))};

	const IVerseMovementQuery* FindQuery(const AActor* Owner)
	{
		if (!Owner)
		{
			return nullptr;
		}
		if (const IVerseMovementQuery* Direct = Cast<IVerseMovementQuery>(Owner))
		{
			return Direct;
		}
		if (UActorComponent* Comp = Owner->FindComponentByInterface(UVerseMovementQuery::StaticClass()))
		{
			return Cast<IVerseMovementQuery>(Comp);
		}
		return nullptr;
	}
}

// ---------------------------------------------------------------------- proxy

void FVerseAnimInstanceProxy::Initialize(UAnimInstance* InAnimInstance)
{
	FAnimInstanceProxy::Initialize(InAnimInstance);
	RegisterSlotNodeWithAnimInstance(FullBodySlot);
}

void FVerseAnimInstanceProxy::PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds)
{
	FAnimInstanceProxy::PreUpdate(InAnimInstance, DeltaSeconds);
	if (const UVerseAnimInstance* Instance = Cast<UVerseAnimInstance>(InAnimInstance))
	{
		Frame = Instance->Frame;
		IdleTime = Instance->GetIdleTime();
	}
}

void FVerseAnimInstanceProxy::Update(float DeltaSeconds)
{
	GetSlotWeight(FullBodySlot, SlotWeight, SourceWeight, TotalWeight);
	UpdateSlotNodeWeight(FullBodySlot, SlotWeight, 1.f);
}

void FVerseAnimInstanceProxy::CacheBones()
{
	FAnimInstanceProxy::CacheBones();
	Bones.Build(GetRequiredBones());
	bBonesValid = Bones.IsValid();
}

bool FVerseAnimInstanceProxy::Evaluate(FPoseContext& Output)
{
	if (!bBonesValid || Bones.Parents.Num() != Output.Pose.GetNumBones())
	{
		Bones.Build(Output.Pose.GetBoneContainer());
		bBonesValid = Bones.IsValid();
	}
	if (!bBonesValid)
	{
		Output.ResetToRefPose();
		return true;
	}
	VerseAnim::EvaluateFrame(Frame, IdleTime, Bones, Output.Pose, Output.Curve, Output.CustomAttributes, &LastInfo);
	if (SlotWeight > ZERO_ANIMWEIGHT_THRESH)
	{
		FPoseContext Source(Output);
		FAnimationPoseData SourceData(Source);
		FAnimationPoseData OutData(Output);
		SlotEvaluatePose(FullBodySlot, SourceData, SourceWeight, OutData, SlotWeight, TotalWeight);
	}
	return true;
}

// ------------------------------------------------------------------- instance

void UVerseAnimInstance::NativeInitializeAnimation()
{
	Super::NativeInitializeAnimation();
	if (!bClipsLoaded)
	{
		Clips.Load();
		bClipsLoaded = true;
		Loaded.Reset();
		auto Keep = [this](const UAnimSequence* Clip)
		{
			if (Clip)
			{
				Loaded.AddUnique(const_cast<UAnimSequence*>(Clip));
			}
		};
		for (int32 S = 0; S < FVerseAnimClipSet::NumStances; ++S)
		{
			Keep(Clips.Idle[S]);
			for (int32 H = 0; H < FVerseAnimClipSet::NumHeadings; ++H)
			{
				Keep(Clips.Move[S][H]);
			}
		}
		for (const UAnimSequence* Clip : {Clips.Sprint, Clips.JumpStart, Clips.Fall, Clips.Land, Clips.Slide,
				 Clips.MantleLow, Clips.MantleHigh, Clips.ProneEnter, Clips.ProneExit})
		{
			Keep(Clip);
		}
		for (const FVerseAnimClipSet::FWeapon& W : Clips.Weapons)
		{
			for (const UAnimSequence* Clip : {W.Idle, W.Ads, W.Fire, W.ReloadTactical, W.ReloadEmpty, W.Equip, W.Holster, W.Strike})
			{
				Keep(Clip);
			}
		}
	}
	Machine.Reset();
	HeelLocal[0] = HeelLocal[1] = FVector::ZeroVector;
	const USkeletalMeshComponent* Body = GetSkelMeshComponent();
	if (const USkeletalMesh* Asset = Body ? Body->GetSkeletalMeshAsset() : nullptr)
	{
		const FReferenceSkeleton& Ref = Asset->GetRefSkeleton();
		const TArray<FTransform>& RefPose = Ref.GetRefBonePose();
		for (int32 s = 0; s < 2; ++s)
		{
			FTransform FootCS = FTransform::Identity;
			const int32 Foot = Ref.FindBoneIndex(FootBones[s]);
			for (int32 b = Foot; b != INDEX_NONE; b = Ref.GetParentIndex(b))
			{
				FootCS = FootCS * RefPose[b];
			}
			if (Foot != INDEX_NONE)
			{
				const FVector Ankle = FootCS.GetLocation();
				HeelLocal[s] = FootCS.InverseTransformPosition(FVector(Ankle.X, Ankle.Y, 0.0));
			}
		}
	}
}

void UVerseAnimInstance::SetExternalInputs(const FVerseAnimInputs& InInputs)
{
	if (UVerseAnimInstance* Source = GetStateSource())
	{
		Source->SetExternalInputs(InInputs);
		return;
	}
	Inputs = InInputs;
	bExternal = true;
}

void UVerseAnimInstance::ClearExternalInputs()
{
	if (UVerseAnimInstance* Source = GetStateSource())
	{
		Source->ClearExternalInputs();
		return;
	}
	bExternal = false;
}

void UVerseAnimInstance::SetWeaponState(EVerseAnimWeapon InWeapon, float InAds)
{
	if (UVerseAnimInstance* Source = GetStateSource())
	{
		Source->SetWeaponState(InWeapon, InAds);
		return;
	}
	Weapon = InWeapon;
	Ads = FMath::Clamp(InAds, 0.f, 1.f);
}

void UVerseAnimInstance::PlayAction(EVerseAnimAction InAction)
{
	if (UVerseAnimInstance* Source = GetStateSource())
	{
		Source->PlayAction(InAction);
		return;
	}
	Action = InAction;
	ActionStart = Machine.GetIdleTime();
}

void UVerseAnimInstance::SetWeaponComponent(USceneComponent* InWeapon)
{
	if (UVerseAnimInstance* Source = GetStateSource())
	{
		Source->SetWeaponComponent(InWeapon);
		return;
	}
	WeaponComponent = InWeapon;
}

void UVerseAnimInstance::SetStateSource(USkeletalMeshComponent* SourceBody)
{
	USkeletalMeshComponent* Body = GetSkelMeshComponent();
	if (SourceBody == Body)
	{
		SourceBody = nullptr;
	}
	if (Body)
	{
		if (USkeletalMeshComponent* Old = StateSourceBody.Get())
		{
			Body->PrimaryComponentTick.RemovePrerequisite(Old, Old->PrimaryComponentTick);
		}
		if (SourceBody)
		{
			// The source steps first, so the mirror copies this frame's state, not the last one.
			Body->PrimaryComponentTick.AddPrerequisite(SourceBody, SourceBody->PrimaryComponentTick);
		}
	}
	StateSourceBody = SourceBody;
	bSourceSearched = true;
}

UVerseAnimInstance* UVerseAnimInstance::GetStateSource() const
{
	const USkeletalMeshComponent* SourceBody = StateSourceBody.Get();
	UVerseAnimInstance* Source = SourceBody ? Cast<UVerseAnimInstance>(SourceBody->GetAnimInstance()) : nullptr;
	// One level only: a source never mirrors another instance.
	return Source && Source != this && !Source->StateSourceBody.IsValid() ? Source : nullptr;
}

EVerseLocoState UVerseAnimInstance::GetLocoState() const
{
	const UVerseAnimInstance* Source = GetStateSource();
	return Source ? Source->Machine.GetState() : Machine.GetState();
}

float UVerseAnimInstance::GetIdleTime() const
{
	const UVerseAnimInstance* Source = GetStateSource();
	return Source ? Source->Machine.GetIdleTime() : Machine.GetIdleTime();
}

bool UVerseAnimInstance::MirrorSource()
{
	USkeletalMeshComponent* Body = GetSkelMeshComponent();
	if (!StateSourceBody.IsValid() && !bSourceSearched && Body && Body->ComponentHasTag(UVerseFirstPersonLibrary::OwnerViewTag))
	{
		// The owner-view body was set up before this instance existed: find the pawn's world body once.
		bSourceSearched = true;
		if (const AActor* Owner = Body->GetOwner())
		{
			TInlineComponentArray<USkeletalMeshComponent*> Bodies(Owner);
			for (USkeletalMeshComponent* Candidate : Bodies)
			{
				if (Candidate != Body && !Candidate->ComponentHasTag(UVerseFirstPersonLibrary::OwnerViewTag)
					&& Cast<UVerseAnimInstance>(Candidate->GetAnimInstance()))
				{
					SetStateSource(Candidate);
					break;
				}
			}
		}
	}
	const UVerseAnimInstance* Source = GetStateSource();
	if (!Source)
	{
		return false;
	}
	Inputs = Source->Inputs;
	Frame = Source->Frame;
	Weapon = Source->Weapon;
	Ads = Source->Ads;
	Action = Source->Action;
	WeaponComponent = Source->WeaponComponent;
	return true;
}

bool UVerseAnimInstance::IsMantleHigh(const AActor* Owner)
{
	UWorld* World = Owner ? Owner->GetWorld() : nullptr;
	if (!World)
	{
		return false;
	}
	float Radius = 0.f;
	float HalfHeight = 0.f;
	Owner->GetSimpleCollisionCylinder(Radius, HalfHeight);
	const FVector Feet = Owner->GetActorLocation() - FVector(0.0, 0.0, HalfHeight);
	const FVector Ahead = Feet + Owner->GetActorForwardVector() * (Radius + MantleProbeAheadCm);
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseMantleHeight), false, Owner);
	FHitResult Hit;
	if (!World->LineTraceSingleByChannel(Hit, Ahead + FVector(0.0, 0.0, MantleProbeTopCm), Ahead, ECC_Visibility, Params))
	{
		return false;
	}
	return Hit.ImpactPoint.Z - Feet.Z > MantleHighAboveCm;
}

FTransform UVerseAnimInstance::GetSupportInWeapon() const
{
	if (const USceneComponent* W = WeaponComponent.Get())
	{
		if (W->DoesSocketExist(SupportSocket))
		{
			return W->GetSocketTransform(SupportSocket, RTS_Component);
		}
	}
	const bool bPistol = Inputs.Weapon == EVerseAnimWeapon::Pistol;
	return FTransform(VerseHuman::ReferenceSupport(bPistol));
}

void UVerseAnimInstance::GatherInputs(float DeltaSeconds)
{
	const AActor* Owner = GetOwningActor();
	FVerseAnimInputs In;
	if (const IVerseMovementQuery* Query = FindQuery(Owner))
	{
		In.Stance = Query->GetStance();
		In.bSprinting = Query->IsSprinting();
		In.bAirborne = Query->IsAirborne();
		In.bMantling = Query->IsMantling();
		In.Lean = IVerseMovementQuery::LeanFromQuantized(Query->GetLeanQuantized());
	}
	// IVerseMovementQuery has no mantle height yet (contract change request #1173): probe the ledge once per mantle.
	if (In.bMantling && !bWasMantling)
	{
		bMantleHigh = IsMantleHigh(Owner);
	}
	bWasMantling = In.bMantling;
	In.bMantleHigh = In.bMantling && bMantleHigh;
	if (Owner)
	{
		In.LocalVelocity = Owner->GetActorTransform().InverseTransformVectorNoScale(Owner->GetVelocity());
		if (const APawn* Pawn = Cast<APawn>(Owner))
		{
			In.AimPitch = FRotator::NormalizeAxis(Pawn->GetBaseAimRotation().Pitch - Owner->GetActorRotation().Pitch);
		}
	}
	In.Weapon = Weapon;
	In.Ads = Ads;
	In.Action = Action;
	In.ActionTime = Machine.GetIdleTime() - ActionStart;
	Inputs = In;
}

void UVerseAnimInstance::TraceFeet()
{
	Frame.FloorOffset[0] = Frame.FloorOffset[1] = 0.f;
	Frame.FloorNormal[0] = Frame.FloorNormal[1] = FVector::UpVector;
	USkeletalMeshComponent* Mesh = GetSkelMeshComponent();
	UWorld* World = Mesh ? Mesh->GetWorld() : nullptr;
	if (!Frame.bFootIK || !World || !bFootIK)
	{
		Frame.bFootIK = false;
		return;
	}
	const FTransform& ToWorld = Mesh->GetComponentTransform();
	const double BaseZ = ToWorld.GetLocation().Z;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseFootIK), false, GetOwningActor());
	auto Probe = [&](const FVector& At, float& OutOffset, FVector& OutNormal)
	{
		FHitResult Hit;
		if (World->LineTraceSingleByChannel(Hit, FVector(At.X, At.Y, BaseZ + 50.0), FVector(At.X, At.Y, BaseZ - 60.0), ECC_Visibility, Params))
		{
			OutOffset = static_cast<float>(Hit.ImpactPoint.Z - BaseZ);
			OutNormal = ToWorld.InverseTransformVectorNoScale(Hit.ImpactNormal);
		}
	};
	for (int32 s = 0; s < 2; ++s)
	{
		// Ankle, heel and ball probes: across a step edge the higher floor under the heel or the
		// ball keeps that end of the foot out of the step (a heel overhangs it in toe-off).
		const int32 FootIndex = Mesh->GetBoneIndex(FootBones[s]);
		if (FootIndex == INDEX_NONE)
		{
			continue;
		}
		const FTransform FootWorld = Mesh->GetBoneTransform(FootIndex);
		const FVector AnkleWorld = FootWorld.GetLocation();
		const FVector HeelWorld = FootWorld.TransformPosition(HeelLocal[s]);
		const FVector BallWorld = Mesh->GetBoneLocation(BallBones[s]);
		float AnkleOffset = 0.f;
		float HeelOffset = 0.f;
		float BallOffset = 0.f;
		FVector AnkleNormal = FVector::UpVector;
		FVector Unused = FVector::UpVector;
		Probe(AnkleWorld, AnkleOffset, AnkleNormal);
		Probe(HeelWorld, HeelOffset, Unused);
		Probe(BallWorld, BallOffset, Unused);
		const float FromHeel = VerseAnim::FootFloorOffset(AnkleOffset, AnkleNormal, HeelOffset,
			ToWorld.InverseTransformVectorNoScale(HeelWorld - AnkleWorld));
		const float FromBall = VerseAnim::FootFloorOffset(AnkleOffset, AnkleNormal, BallOffset,
			ToWorld.InverseTransformVectorNoScale(BallWorld - AnkleWorld));
		Frame.FloorOffset[s] = FMath::Max(FromHeel, FromBall);
		Frame.FloorNormal[s] = AnkleNormal;
	}
}

void UVerseAnimInstance::NativeUpdateAnimation(float DeltaSeconds)
{
	Super::NativeUpdateAnimation(DeltaSeconds);
	const USkeletalMeshComponent* Body = GetSkelMeshComponent();
	const bool bOwnerView = Body && Body->ComponentHasTag(UVerseFirstPersonLibrary::OwnerViewTag);
	if (MirrorSource())
	{
		// The world body's pose (its traces, its clips, its weapon); only the head differs.
		Frame.bHideHead = bOwnerView;
		return;
	}
	if (!bExternal)
	{
		GatherInputs(DeltaSeconds);
	}
	Machine.Step(Inputs, DeltaSeconds, Clips, Frame);
	Frame.SupportInWeapon = GetSupportInWeapon();
	Frame.bHideHead = bOwnerView;
	if (!Inputs.OverrideClip.IsNone())
	{
		if (Inputs.OverrideClip != OverrideName)
		{
			// Crew duty clips: resolved once per name, not every frame.
			OverrideName = Inputs.OverrideClip;
			const FString Path = VerseHuman::ClipPath(OverrideName.ToString());
			OverrideClip = LoadObject<UAnimSequence>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
		}
		Frame.Override = OverrideClip;
		Frame.OverrideTime = Inputs.OverrideTime;
		Frame.bOverrideLoop = Inputs.bOverrideLoop;
		// The override replaces the whole pose, foot IK included: no traces for it.
		Frame.bFootIK = false;
	}
	else if (!OverrideName.IsNone())
	{
		OverrideName = NAME_None;
		OverrideClip = nullptr;
	}
	TraceFeet();
	if (Action != EVerseAnimAction::None && Frame.ActionWeight <= 0.f && Inputs.ActionTime > 0.1f)
	{
		Action = EVerseAnimAction::None;
	}
}

FAnimInstanceProxy* UVerseAnimInstance::CreateAnimInstanceProxy()
{
	return new FVerseAnimInstanceProxy(this);
}

void UVerseAnimInstance::DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy)
{
	delete InProxy;
}

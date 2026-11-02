#include "Anim/VerseAnimInstance.h"
#include "Anim/VerseFirstPerson.h"

#include "Anim/VerseHumanSkeleton.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationPoseData.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "CollisionQueryParams.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "Movement/VerseMovementQuery.h"

const FName FVerseAnimInstanceProxy::FullBodySlot(TEXT("FullBody"));

namespace
{
	const FName SupportSocket(TEXT("SOCKET_Support"));

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
		IdleTime = Instance->Machine.GetIdleTime();
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
}

void UVerseAnimInstance::SetExternalInputs(const FVerseAnimInputs& InInputs)
{
	Inputs = InInputs;
	bExternal = true;
}

void UVerseAnimInstance::ClearExternalInputs()
{
	bExternal = false;
}

void UVerseAnimInstance::SetWeaponState(EVerseAnimWeapon InWeapon, float InAds)
{
	Weapon = InWeapon;
	Ads = FMath::Clamp(InAds, 0.f, 1.f);
}

void UVerseAnimInstance::PlayAction(EVerseAnimAction InAction)
{
	Action = InAction;
	ActionStart = Machine.GetIdleTime();
}

void UVerseAnimInstance::SetWeaponComponent(USceneComponent* InWeapon)
{
	WeaponComponent = InWeapon;
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
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseFootIK), false, GetOwningActor());
	const FName Feet[] = {FName(TEXT("Foot_L")), FName(TEXT("Foot_R"))};
	for (int32 s = 0; s < 2; ++s)
	{
		const FVector FootWorld = Mesh->GetBoneLocation(Feet[s]);
		const FVector Start(FootWorld.X, FootWorld.Y, ToWorld.GetLocation().Z + 50.0);
		const FVector End(FootWorld.X, FootWorld.Y, ToWorld.GetLocation().Z - 60.0);
		FHitResult Hit;
		if (World->LineTraceSingleByChannel(Hit, Start, End, ECC_Visibility, Params))
		{
			Frame.FloorOffset[s] = static_cast<float>(Hit.ImpactPoint.Z - ToWorld.GetLocation().Z);
			Frame.FloorNormal[s] = ToWorld.InverseTransformVectorNoScale(Hit.ImpactNormal);
		}
	}
}

void UVerseAnimInstance::NativeUpdateAnimation(float DeltaSeconds)
{
	Super::NativeUpdateAnimation(DeltaSeconds);
	if (!bExternal)
	{
		GatherInputs(DeltaSeconds);
	}
	Machine.Step(Inputs, DeltaSeconds, Clips, Frame);
	Frame.SupportInWeapon = GetSupportInWeapon();
	const USkeletalMeshComponent* Body = GetSkelMeshComponent();
	Frame.bHideHead = Body && Body->ComponentHasTag(UVerseFirstPersonLibrary::OwnerViewTag);
	if (!Inputs.OverrideClip.IsNone())
	{
		const FString Path = VerseHuman::ClipPath(Inputs.OverrideClip.ToString());
		UAnimSequence* Clip = LoadObject<UAnimSequence>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
		if (Clip)
		{
			Loaded.AddUnique(Clip);
		}
		Frame.Override = Clip;
		Frame.OverrideTime = Inputs.OverrideTime;
		Frame.bOverrideLoop = Inputs.bOverrideLoop;
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

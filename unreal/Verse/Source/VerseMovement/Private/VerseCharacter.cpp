#include "VerseCharacter.h"

#include "AnimationRuntime.h"
#include "Camera/CameraComponent.h"
#include "Components/BoxComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/InputComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformTime.h"
#include "Misc/ScopeExit.h"
#include "Net/UnrealNetwork.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "UObject/ConstructorHelpers.h"
#include "VerseCharacterMovement.h"
#include "VerseCollision.h"

namespace
{
	const TCHAR* TestHumanMesh = TEXT("/Game/Verse/Test/G0/SK_Test_Human.SK_Test_Human");
	const TCHAR* TestHumanPhysics = TEXT("/Game/Verse/Test/G0/PHYS_Test_Human.PHYS_Test_Human");
	/** The mesh faces +Y in its own space (coordinates.md 3.3: mesh yaw = heading - 90). */
	const FRotator MeshBaseRotation(0.f, -90.f, 0.f);
	/** Placeholder prone pose: the feet rest this high, the body rises toward the head. */
	constexpr float ProneFeetLift = 12.f;
	/** Share of the prone body length from the feet to the hips (the leg hit box). */
	constexpr float ProneLegShare = 0.53f;
}

const FName AVerseCharacter::CameraBoneName(TEXT("Camera"));

AVerseCharacter::AVerseCharacter(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer.SetDefaultSubobjectClass<UVerseCharacterMovement>(ACharacter::CharacterMovementComponentName))
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PrePhysics;
	bUseControllerRotationYaw = true;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;
	// The input frame (Tick) runs before the movement simulates it; see BeginPlay.
	GetCharacterMovement()->bTickBeforeOwner = false;

	const FVerseMovementTuningValues Defaults;
	GetCapsuleComponent()->InitCapsuleSize(Defaults.CapsuleRadius * 100.f, Defaults.StandHalfHeightCm());

	FirstPersonCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FirstPersonCamera"));
	FirstPersonCamera->SetupAttachment(GetCapsuleComponent());
	FirstPersonCamera->SetRelativeLocation(FVector(0.f, 0.f, Defaults.StandEyeHeight * 100.f - Defaults.StandHalfHeightCm()));
	FirstPersonCamera->bUsePawnControlRotation = false;
	FirstPersonCamera->SetFieldOfView(100.f);

	ProneBody = CreateDefaultSubobject<UBoxComponent>(TEXT("ProneBody"));
	ProneBody->SetupAttachment(GetCapsuleComponent());
	ProneBody->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	ProneBody->SetCollisionObjectType(ECC_Pawn);
	ProneBody->SetCollisionResponseToAllChannels(ECR_Ignore);
	ProneBody->SetCollisionResponseToChannel(VerseCollision::HitBody, ECR_Block);
	ProneBody->SetCanEverAffectNavigation(false);
	ProneBody->SetGenerateOverlapEvents(false);

	if (USkeletalMeshComponent* Body = GetMesh())
	{
		static ConstructorHelpers::FObjectFinderOptional<USkeletalMesh> MeshFinder(TestHumanMesh);
		if (MeshFinder.Succeeded())
		{
			Body->SetSkeletalMeshAsset(MeshFinder.Get());
		}
		Body->SetRelativeLocationAndRotation(FVector(0.f, 0.f, -Defaults.StandHalfHeightCm()), MeshBaseRotation);
		Body->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
		Body->bOwnerNoSee = false;
	}
}

UVerseCharacterMovement* AVerseCharacter::GetVerseMovement() const
{
	return Cast<UVerseCharacterMovement>(GetCharacterMovement());
}

void AVerseCharacter::BeginPlay()
{
	Super::BeginPlay();
	// Input before movement: the frame applied in Tick (look, turn, move, buttons) is the one the
	// movement simulates in the same frame, and the turn cap and prone body constraint see it.
	if (UCharacterMovementComponent* Movement = GetCharacterMovement())
	{
		Movement->PrimaryComponentTick.AddPrerequisite(this, PrimaryActorTick);
	}
	if (USkeletalMeshComponent* Body = GetMesh())
	{
		if (Body->GetSkeletalMeshAsset() && !Body->GetPhysicsAsset())
		{
			if (UPhysicsAsset* Physics = LoadObject<UPhysicsAsset>(nullptr, TestHumanPhysics, nullptr, LOAD_NoWarn | LOAD_Quiet))
			{
				Body->SetPhysicsAsset(Physics, true);
			}
		}
	}
	CacheCameraBone();
	// The leg box covers the lying legs only: from the feet end of the prone body to the hips.
	const FVerseMovementTuningValues& Tuning = GetVerseMovement()->Tuning();
	const float Length = Tuning.ProneBodyLength * 100.f;
	const float HeadForward = Tuning.ProneRadius * 200.f;
	const float Legs = Length * ProneLegShare;
	ProneBody->SetBoxExtent(FVector(Legs * 0.5f, Tuning.ProneBodyWidth * 50.f, Tuning.ProneMinClearance * 50.f - 2.f), false);
	ProneBody->SetRelativeLocation(FVector(HeadForward - Length + Legs * 0.5f, 0.f, 0.f));
	UpdateBodyPose(0.f);
}

void AVerseCharacter::CacheCameraBone()
{
	bHasCameraBone = false;
	const USkeletalMeshComponent* Body = GetMesh();
	const USkeletalMesh* Asset = Body ? Body->GetSkeletalMeshAsset() : nullptr;
	if (!Asset)
	{
		return;
	}
	const FReferenceSkeleton& Skeleton = Asset->GetRefSkeleton();
	const int32 Index = Skeleton.FindBoneIndex(CameraBoneName);
	if (Index == INDEX_NONE)
	{
		return;
	}
	CameraBoneLocal = FAnimationRuntime::GetComponentSpaceTransformRefPose(Skeleton, Index).GetLocation();
	bHasCameraBone = CameraBoneLocal.Z > 1.f;
}

void AVerseCharacter::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	FDoRepLifetimeParams Params;
	Params.Condition = COND_SkipOwner;
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseCharacter, ReplicatedStance, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseCharacter, ReplicatedLean, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseCharacter, bReplicatedSprinting, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseCharacter, bReplicatedMantling, Params);
}

void AVerseCharacter::SetReplicatedMovementState(EVerseStance Stance, int8 Lean, bool bSprinting, bool bMantling)
{
	ReplicatedStance = uint8(Stance);
	ReplicatedLean = Lean;
	bReplicatedSprinting = bSprinting;
	bReplicatedMantling = bMantling;
}

void AVerseCharacter::OnRep_MovementState()
{
	if (UVerseCharacterMovement* Movement = GetVerseMovement())
	{
		Movement->ApplyReplicatedStance(EVerseStance(ReplicatedStance));
	}
}

// ---------------------------------------------------------------------------------------------
// Input

void AVerseCharacter::ApplyInputFrame(const FVerseInputFrame& Frame, float DeltaSeconds)
{
	UVerseCharacterMovement* Movement = GetVerseMovement();
	if (!Movement)
	{
		return;
	}
	LastAppliedFrame = Frame;
	if (Controller)
	{
		FRotator Rotation = Controller->GetControlRotation();
		float Yaw = Frame.LookDeltaDeg.Y;
		if (Movement->IsProne() || Movement->GetProneTransitionAlpha() != 0.f)
		{
			const float Cap = Movement->Tuning().ProneTurnCapDegPerSec * DeltaSeconds;
			Yaw = FMath::Clamp(Yaw, -Cap, Cap);
		}
		Rotation.Yaw = FRotator::NormalizeAxis(Rotation.Yaw + Yaw);
		Rotation.Pitch = FMath::Clamp(FRotator::NormalizeAxis(Rotation.Pitch + Frame.LookDeltaDeg.X), -85.f, 85.f);
		Rotation.Roll = 0.f;
		Controller->SetControlRotation(Rotation);
		// Plain controllers (bots, harness) never rotate their pawn; turn the body here for all.
		FaceRotation(Rotation, DeltaSeconds);
	}
	FVector2f Move = Frame.Move;
	if (Move.SizeSquared() > 1.f)
	{
		Move.Normalize();
	}
	const FRotator YawOnly(0.f, Controller ? Controller->GetControlRotation().Yaw : GetActorRotation().Yaw, 0.f);
	const FRotationMatrix Basis(YawOnly);
	AddMovementInput(Basis.GetUnitAxis(EAxis::X), Move.X);
	AddMovementInput(Basis.GetUnitAxis(EAxis::Y), Move.Y);

	Movement->SetWantsSprint(Frame.IsHeld(EVerseInputButton::Sprint));
	Movement->bWantsToCrouch = Frame.IsHeld(EVerseInputButton::Crouch);
	Movement->SetWantsProne(Frame.IsHeld(EVerseInputButton::Prone));
	Movement->SetWantsMantle(Frame.IsHeld(EVerseInputButton::Jump));
	const int32 Lean = (Frame.IsHeld(EVerseInputButton::LeanRight) ? 1 : 0) - (Frame.IsHeld(EVerseInputButton::LeanLeft) ? 1 : 0);
	Movement->SetLeanTarget(int8(Lean * 127));
	if (Frame.WasPressed(EVerseInputButton::Jump))
	{
		Jump();
	}
	else if (!Frame.IsHeld(EVerseInputButton::Jump))
	{
		StopJumping();
	}
}

void AVerseCharacter::SubmitInputFrame(const FVerseInputFrame& Frame)
{
	SubmittedFrame = Frame;
	bHasSubmittedFrame = true;
	bSubmittedFrameFresh = true;
}

void AVerseCharacter::SetInputScript(FVerseInputScript Script)
{
	InputScript = MoveTemp(Script);
	InputScriptTime = 0.f;
}

void AVerseCharacter::Tick(float DeltaSeconds)
{
	const uint64 StartCycles = FPlatformTime::Cycles64();
	ON_SCOPE_EXIT
	{
		if (UVerseCharacterMovement* Movement = GetVerseMovement())
		{
			Movement->AddMovementCycles(FPlatformTime::Cycles64() - StartCycles);
		}
	};
	Super::Tick(DeltaSeconds);
	if (!IsLocallyControlled() && !HasAuthority())
	{
		return;
	}
	const uint32 TimeMs = GetWorld() ? uint32(GetWorld()->GetTimeSeconds() * 1000.0) : 0;
	if (InputScript)
	{
		FVerseInputFrame Frame;
		Frame.ServerTimeMs = TimeMs;
		const bool bContinue = InputScript(InputScriptTime, DeltaSeconds, Frame);
		InputScriptTime += DeltaSeconds;
		ApplyInputFrame(Frame, DeltaSeconds);
		if (!bContinue)
		{
			InputScript = nullptr;
		}
		return;
	}
	if (bHasSubmittedFrame)
	{
		// A frame holds until the next one; its one-shot parts (presses, look) apply once.
		FVerseInputFrame Frame = SubmittedFrame;
		if (!bSubmittedFrameFresh)
		{
			Frame.Pressed = 0;
			Frame.LookDeltaDeg = FVector2f::ZeroVector;
		}
		bSubmittedFrameFresh = false;
		ApplyInputFrame(Frame, DeltaSeconds);
		return;
	}
	if (IsLocallyControlled() && Cast<APlayerController>(Controller))
	{
		ApplyInputFrame(PersonInput.Consume(TimeMs), DeltaSeconds);
	}
}

void AVerseCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);
	if (!PlayerInputComponent)
	{
		return;
	}
	TWeakObjectPtr<AVerseCharacter> Self(this);
	VersePersonInput::BindDefaults(*PlayerInputComponent, PersonInput, [Self]()
	{
		const UWorld* World = Self.IsValid() ? Self->GetWorld() : nullptr;
		return World ? World->GetDeltaSeconds() : 0.f;
	});
}

void AVerseCharacter::PawnClientRestart()
{
	Super::PawnClientRestart();
	PersonInput.Reset();
}

// ---------------------------------------------------------------------------------------------
// Camera and placeholder body

void AVerseCharacter::UpdateBodyPose(float DeltaSeconds)
{
	const UVerseCharacterMovement* Movement = GetVerseMovement();
	if (!Movement || !GetCapsuleComponent())
	{
		return;
	}
	const FVerseMovementTuningValues& Tuning = Movement->Tuning();
	const float HalfHeight = GetCapsuleComponent()->GetUnscaledCapsuleHalfHeight();
	const EVerseStance Stance = Movement->GetStance();
	const bool bProne = Stance == EVerseStance::Prone;

	// Prone alpha: 1 lying, 0 upright; transitions blend over the enter and exit times.
	float ProneAlpha = bProne ? 1.f : 0.f;
	const float Transition = Movement->GetProneTransitionAlpha();
	if (Transition > 0.f)
	{
		ProneAlpha = Transition;
	}
	else if (Transition < 0.f)
	{
		ProneAlpha = 1.f + Transition;
	}
	SmoothedProneAlpha = ProneAlpha;
	// The upright eye height settles over EyeBlendTime; lying blends in through the prone alpha.
	const float UprightEye = bProne ? Tuning.CrouchEyeHeight * 100.f : Movement->GetTargetEyeHeight();
	if (SmoothedEyeHeight < 0.f || DeltaSeconds <= 0.f)
	{
		SmoothedEyeHeight = UprightEye;
	}
	else
	{
		const float Blend = FMath::Clamp(DeltaSeconds / FMath::Max(Tuning.EyeBlendTime, KINDA_SMALL_NUMBER), 0.f, 1.f);
		SmoothedEyeHeight = FMath::Lerp(SmoothedEyeHeight, UprightEye, Blend);
	}
	const float Lean = Movement->GetLean();
	// The eye in the capsule's frame: one formula for the camera, the bone and the bot's eye.
	const FVector Eye = Movement->GetEyeOffset(SmoothedEyeHeight, Lean, SmoothedProneAlpha) - FVector(0.f, 0.f, HalfHeight);

	ProneBody->SetCollisionEnabled(bProne ? ECollisionEnabled::QueryOnly : ECollisionEnabled::NoCollision);

	USkeletalMeshComponent* Body = GetMesh();
	const bool bAnimated = Body && Body->GetAnimInstance();
	if (bPlaceholderPose && Body && !bAnimated)
	{
		const FQuat Upright = MeshBaseRotation.Quaternion();
		// Lying face down, head forward: mesh up (+Z) along the facing, mesh front (+Y) down, the
		// body raised toward the head so the feet rest on the floor and the eye sits at its height.
		FQuat Lying = FRotationMatrix::MakeFromYZ(FVector(0.f, 0.f, -1.f), FVector(1.f, 0.f, 0.f)).ToQuat();
		if (bHasCameraBone)
		{
			const float Rise = FMath::Clamp((Tuning.ProneEyeHeight * 100.f - ProneFeetLift + CameraBoneLocal.Y) / CameraBoneLocal.Z, -0.5f, 0.5f);
			Lying = FRotator(FMath::RadiansToDegrees(FMath::Asin(Rise)), 0.f, 0.f).Quaternion() * Lying; // head end up
		}
		const FQuat Pose = FQuat::Slerp(Upright, Lying, SmoothedProneAlpha);
		// Lean rolls the whole placeholder; > 0 moves the head to the right.
		const float Roll = FMath::DegreesToRadians(Lean * Tuning.LeanRollDeg) * (1.f - SmoothedProneAlpha);
		const FQuat LeanQuat(FVector::ForwardVector, -Roll);
		const float SlideTilt = Stance == EVerseStance::Slide ? FMath::DegreesToRadians(-30.f) : 0.f;
		const FQuat SlideQuat(FVector::RightVector, SlideTilt);
		const FQuat Rotation = SlideQuat * LeanQuat * Pose;
		FVector Scale(1.f);
		FVector Location;
		if (bHasCameraBone)
		{
			// Upright the placeholder shrinks to the eye height; lying keeps its length. The mesh
			// then goes where its Camera bone lands exactly on the eye.
			Scale.Z = FMath::Lerp(SmoothedEyeHeight / CameraBoneLocal.Z, 1.f, SmoothedProneAlpha);
			Location = Eye - Rotation.RotateVector(Scale * CameraBoneLocal);
		}
		else
		{
			const bool bLow = Stance == EVerseStance::Crouch || Stance == EVerseStance::Slide;
			Scale.Z = bLow ? Tuning.CrouchHeight / Tuning.StandHeight : 1.f;
			const FVector UprightLocation(0.f, 0.f, -HalfHeight);
			const FVector LyingLocation(Tuning.ProneRadius * 200.f - Tuning.ProneBodyLength * 100.f, 0.f, -HalfHeight + 15.f);
			Location = FMath::Lerp(UprightLocation, LyingLocation, SmoothedProneAlpha);
		}
		const FRotator Rotator = Rotation.Rotator();
		if (!Body->GetRelativeScale3D().Equals(Scale, 0.0001))
		{
			Body->SetRelativeScale3D(Scale);
		}
		if (!Body->GetRelativeLocation().Equals(Location, 0.001) || !Body->GetRelativeRotation().Equals(Rotator, 0.001))
		{
			CacheInitialMeshOffset(Location, Rotator);
			Body->SetRelativeLocationAndRotation(Location, Rotator, false, nullptr, ETeleportType::TeleportPhysics);
		}
	}

	// The camera sits on the Camera bone: an animated mesh (WP13) moves the bone, the placeholder
	// pose puts it on the eye above.
	if (bAnimated && bHasCameraBone)
	{
		FirstPersonCamera->SetWorldLocation(Body->GetSocketLocation(CameraBoneName));
	}
	else
	{
		FirstPersonCamera->SetRelativeLocation(Eye);
	}
	const FRotator Aim = GetAimRotation();
	FirstPersonCamera->SetWorldRotation(FRotator(Aim.Pitch, Aim.Yaw, Lean * Tuning.LeanRollDeg));
}

FVector AVerseCharacter::GetCameraBoneLocation() const
{
	const USkeletalMeshComponent* Body = GetMesh();
	if (Body && bHasCameraBone && Body->GetBoneIndex(CameraBoneName) != INDEX_NONE)
	{
		return Body->GetSocketLocation(CameraBoneName);
	}
	return FirstPersonCamera->GetComponentLocation();
}

FVector AVerseCharacter::GetEyeLocation() const
{
	return FirstPersonCamera->GetComponentLocation();
}

FRotator AVerseCharacter::GetEyeRotation() const
{
	return FirstPersonCamera->GetComponentRotation();
}

void AVerseCharacter::GetActorEyesViewPoint(FVector& OutLocation, FRotator& OutRotation) const
{
	OutLocation = GetEyeLocation();
	OutRotation = GetAimRotation();
}

FRotator AVerseCharacter::GetAimRotation() const
{
	// Not GetBaseAimRotation: that asks GetActorEyesViewPoint, which asks back here.
	if (Controller)
	{
		return Controller->GetControlRotation();
	}
	FRotator Aim = GetActorRotation();
	Aim.Pitch = FRotator::NormalizeAxis(float(GetRemoteViewPitch()) * 360.f / 65536.f);
	return Aim;
}

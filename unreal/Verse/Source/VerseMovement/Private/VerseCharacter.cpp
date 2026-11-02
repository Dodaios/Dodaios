#include "VerseCharacter.h"

#include "Camera/CameraComponent.h"
#include "Components/BoxComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "Engine/LocalPlayer.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "InputActionValue.h"
#include "Net/Core/PushModel/PushModel.h"
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
}

AVerseCharacter::AVerseCharacter(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer.SetDefaultSubobjectClass<UVerseCharacterMovement>(ACharacter::CharacterMovementComponentName))
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PrePhysics;
	bUseControllerRotationYaw = true;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;

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
	const FVerseMovementTuningValues& Tuning = GetVerseMovement()->Tuning();
	const float Length = Tuning.ProneBodyLength * 100.f;
	const float HeadForward = Tuning.ProneRadius * 200.f;
	ProneBody->SetBoxExtent(FVector(Length * 0.5f, Tuning.ProneBodyWidth * 50.f, Tuning.ProneMinClearance * 50.f - 2.f), false);
	ProneBody->SetRelativeLocation(FVector(HeadForward - Length * 0.5f, 0.f, 0.f));
	UpdateBodyPose(0.f);
}

void AVerseCharacter::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	FDoRepLifetimeParams Params;
	Params.bIsPushBased = true;
	Params.Condition = COND_SkipOwner;
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseCharacter, ReplicatedStance, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseCharacter, ReplicatedLean, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseCharacter, bReplicatedSprinting, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVerseCharacter, bReplicatedMantling, Params);
}

void AVerseCharacter::SetReplicatedMovementState(EVerseStance Stance, int8 Lean, bool bSprinting, bool bMantling)
{
	if (ReplicatedStance != uint8(Stance))
	{
		ReplicatedStance = uint8(Stance);
		MARK_PROPERTY_DIRTY_FROM_NAME(AVerseCharacter, ReplicatedStance, this);
	}
	if (ReplicatedLean != Lean)
	{
		ReplicatedLean = Lean;
		MARK_PROPERTY_DIRTY_FROM_NAME(AVerseCharacter, ReplicatedLean, this);
	}
	if (bReplicatedSprinting != bSprinting)
	{
		bReplicatedSprinting = bSprinting;
		MARK_PROPERTY_DIRTY_FROM_NAME(AVerseCharacter, bReplicatedSprinting, this);
	}
	if (bReplicatedMantling != bMantling)
	{
		bReplicatedMantling = bMantling;
		MARK_PROPERTY_DIRTY_FROM_NAME(AVerseCharacter, bReplicatedMantling, this);
	}
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
	UEnhancedInputComponent* Input = Cast<UEnhancedInputComponent>(PlayerInputComponent);
	if (!Input)
	{
		return;
	}
	if (!PersonInputConfig)
	{
		PersonInputConfig = NewObject<UVersePersonInputConfig>(this);
		PersonInputConfig->Build();
	}
	UVersePersonInputConfig* Config = PersonInputConfig;
	Input->BindAction(Config->Move, ETriggerEvent::Triggered, this, &AVerseCharacter::OnMoveAction);
	Input->BindAction(Config->Move, ETriggerEvent::Completed, this, &AVerseCharacter::OnMoveActionStopped);
	Input->BindAction(Config->Look, ETriggerEvent::Triggered, this, &AVerseCharacter::OnLookAction);
	Input->BindAction(Config->LookRate, ETriggerEvent::Triggered, this, &AVerseCharacter::OnLookRateAction);

	auto BindHold = [this, Input](UInputAction* Action, EVerseInputButton Button)
	{
		Input->BindActionValueLambda(Action, ETriggerEvent::Started, [this, Button](const FInputActionValue&) { PersonInput.SetButton(Button, true); });
		Input->BindActionValueLambda(Action, ETriggerEvent::Completed, [this, Button](const FInputActionValue&) { PersonInput.SetButton(Button, false); });
	};
	auto BindToggle = [this, Input](UInputAction* Action, EVerseInputButton Button)
	{
		Input->BindActionValueLambda(Action, ETriggerEvent::Started, [this, Button](const FInputActionValue&) { PersonInput.ToggleButton(Button); });
	};
	BindHold(Config->Jump, EVerseInputButton::Jump);
	BindHold(Config->Sprint, EVerseInputButton::Sprint);
	BindHold(Config->LeanLeft, EVerseInputButton::LeanLeft);
	BindHold(Config->LeanRight, EVerseInputButton::LeanRight);
	BindToggle(Config->Crouch, EVerseInputButton::Crouch);
	BindToggle(Config->Prone, EVerseInputButton::Prone);
	Input->BindActionValueLambda(Config->Walk, ETriggerEvent::Started, [this](const FInputActionValue&) { PersonInput.SetWalkModifier(true); });
	Input->BindActionValueLambda(Config->Walk, ETriggerEvent::Completed, [this](const FInputActionValue&) { PersonInput.SetWalkModifier(false); });
}

void AVerseCharacter::PawnClientRestart()
{
	Super::PawnClientRestart();
	PersonInput.Reset();
	const APlayerController* PlayerController = Cast<APlayerController>(Controller);
	const ULocalPlayer* LocalPlayer = PlayerController ? PlayerController->GetLocalPlayer() : nullptr;
	if (!LocalPlayer)
	{
		return;
	}
	if (!PersonInputConfig)
	{
		PersonInputConfig = NewObject<UVersePersonInputConfig>(this);
		PersonInputConfig->Build();
	}
	if (UEnhancedInputLocalPlayerSubsystem* Subsystem = LocalPlayer->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>())
	{
		Subsystem->AddMappingContext(PersonInputConfig->Mapping, 0);
	}
}

void AVerseCharacter::OnMoveAction(const FInputActionValue& Value)
{
	const FVector2D Axis = Value.Get<FVector2D>();
	PersonInput.SetMove(FVector2f(float(Axis.X), float(Axis.Y)));
}

void AVerseCharacter::OnMoveActionStopped(const FInputActionValue& Value)
{
	PersonInput.SetMove(FVector2f::ZeroVector);
}

void AVerseCharacter::OnLookAction(const FInputActionValue& Value)
{
	const FVector2D Axis = Value.Get<FVector2D>();
	const float Scale = PersonInputConfig ? PersonInputConfig->MouseDegPerCount : 0.07f;
	PersonInput.AddLook(FVector2f(float(Axis.Y) * Scale, float(Axis.X) * Scale));
}

void AVerseCharacter::OnLookRateAction(const FInputActionValue& Value)
{
	const FVector2D Axis = Value.Get<FVector2D>();
	const float Rate = (PersonInputConfig ? PersonInputConfig->StickDegPerSecond : 180.f) * (GetWorld() ? GetWorld()->GetDeltaSeconds() : 0.f);
	PersonInput.AddLook(FVector2f(float(Axis.Y) * Rate, float(Axis.X) * Rate));
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
	const float TargetEye = Movement->GetTargetEyeHeight();
	if (SmoothedEyeHeight < 0.f || DeltaSeconds <= 0.f)
	{
		SmoothedEyeHeight = TargetEye;
	}
	else
	{
		const float Blend = FMath::Clamp(DeltaSeconds / FMath::Max(Tuning.EyeBlendTime, KINDA_SMALL_NUMBER), 0.f, 1.f);
		SmoothedEyeHeight = FMath::Lerp(SmoothedEyeHeight, TargetEye, Blend);
	}
	const float Lean = Movement->GetLean();
	const float LeanOffset = Lean * Tuning.LeanCameraOffset * 100.f;
	FirstPersonCamera->SetRelativeLocation(FVector(0.f, LeanOffset, SmoothedEyeHeight - HalfHeight));
	const FRotator Aim = GetBaseAimRotation();
	FirstPersonCamera->SetWorldRotation(FRotator(Aim.Pitch, Aim.Yaw, Lean * Tuning.LeanRollDeg));

	const bool bProne = Movement->GetStance() == EVerseStance::Prone;
	ProneBody->SetCollisionEnabled(bProne ? ECollisionEnabled::QueryOnly : ECollisionEnabled::NoCollision);
	ProneBody->SetRelativeLocation(FVector(Tuning.ProneRadius * 200.f - Tuning.ProneBodyLength * 50.f, 0.f, 0.f));

	USkeletalMeshComponent* Body = GetMesh();
	if (!bPlaceholderPose || !Body || Body->GetAnimInstance())
	{
		return;
	}
	// Prone alpha: 1 lying, 0 upright; transitions blend over the enter and exit times.
	float TargetProne = bProne ? 1.f : 0.f;
	const float Transition = Movement->GetProneTransitionAlpha();
	if (Transition > 0.f)
	{
		TargetProne = Transition;
	}
	else if (Transition < 0.f)
	{
		TargetProne = 1.f + Transition;
	}
	SmoothedProneAlpha = TargetProne;
	const FQuat Upright = MeshBaseRotation.Quaternion();
	// Lying face down, head forward: mesh up (+Z) along the facing, mesh front (+Y) down.
	const FQuat Lying = FRotationMatrix::MakeFromYZ(FVector(0.f, 0.f, -1.f), FVector(1.f, 0.f, 0.f)).ToQuat();
	const FQuat Pose = FQuat::Slerp(Upright, Lying, SmoothedProneAlpha);
	// Lean rolls the whole placeholder about the feet; > 0 moves the head to the right.
	const float Roll = FMath::DegreesToRadians(Lean * Tuning.LeanRollDeg) * (1.f - SmoothedProneAlpha);
	const FQuat LeanQuat(FVector::ForwardVector, -Roll);
	const FVector UprightLocation(0.f, 0.f, -HalfHeight);
	const FVector LyingLocation(Tuning.ProneRadius * 200.f - Tuning.ProneBodyLength * 100.f, 0.f, -HalfHeight + 15.f);
	const FVector Location = FMath::Lerp(UprightLocation, LyingLocation, SmoothedProneAlpha);
	const FRotator Rotation = (LeanQuat * Pose).Rotator();
	if (Body->GetRelativeLocation().Equals(Location, 0.01) && Body->GetRelativeRotation().Equals(Rotation, 0.01))
	{
		return;
	}
	CacheInitialMeshOffset(Location, Rotation);
	Body->SetRelativeLocationAndRotation(Location, Rotation, false, nullptr, ETeleportType::TeleportPhysics);
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
	OutRotation = GetBaseAimRotation();
}

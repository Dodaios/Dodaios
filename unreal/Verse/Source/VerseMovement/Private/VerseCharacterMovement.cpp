#include "VerseCharacterMovement.h"

#include "Components/CapsuleComponent.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/PlayerState.h"
#include "GameFramework/RootMotionSource.h"
#include "HAL/PlatformTime.h"
#include "PhysicalMaterials/PhysicalMaterial.h"
#include "VerseCharacter.h"
#include "VerseGameplayTags.h"
#include "VerseLog.h"
#include "VerseMovementNetworking.h"

namespace
{
	const FName MantleRiseSource(TEXT("VerseMantleRise"));
	const FName MantleMoveSource(TEXT("VerseMantleMove"));
	constexpr int16 NoClientLean = -128;
	/** Lean steps (of 127) within which the server adopts the client's lean. */
	constexpr int32 LeanAdoptTolerance = 8;
	/** Sphere radius of the mantle top probes. */
	constexpr float ProbeRadius = 4.f;
	constexpr float WallProbeRadius = 10.f;
}

// ---------------------------------------------------------------------------------------------
// Net stats

int32 FVerseMovementNetStats::Total() const
{
	int32 Sum = 0;
	for (int32 Count : Corrections)
	{
		Sum += Count;
	}
	return Sum;
}

FString FVerseMovementNetStats::ToJson() const
{
	FString Kinds;
	const UEnum* Enum = StaticEnum<EVerseMoveKind>();
	for (int32 Index = 0; Index < int32(EVerseMoveKind::Count); ++Index)
	{
		Kinds += FString::Printf(TEXT("%s\"%s\": %d"), Index ? TEXT(", ") : TEXT(""),
			*Enum->GetNameStringByValue(Index).ToLower(), Corrections[Index]);
	}
	return FString::Printf(TEXT("{\"corrections_total\": %d, \"corrections\": {%s}, \"server_moves\": %d, \"lean_mismatches\": %d}"),
		Total(), *Kinds, ServerMoves, LeanMismatches);
}

// ---------------------------------------------------------------------------------------------
// Construction and tuning

UVerseCharacterMovement::UVerseCharacterMovement(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	TuningValues = FVerseMovementTuningValues();
	// Stance and capsule heights are ours; the stock crouch path stays off (see SetBodyShape).
	GetNavAgentPropertiesRef().bCanCrouch = false;
	GetNavAgentPropertiesRef().bCanJump = true;
	bOrientRotationToMovement = false;
	bUseControllerDesiredRotation = false;
	SetCrouchedHalfHeight(TuningValues.CrouchHalfHeightCm());
	MaxStepHeight = 45.f;
	SetWalkableFloorAngle(44.765f);
	AirControl = 0.25f;
	bCanWalkOffLedgesWhenCrouching = true;
	MoveDataContainer = MakeUnique<FVerseCharacterNetworkMoveDataContainer>();
	SetNetworkMoveDataContainer(*MoveDataContainer);
	ApplyTuningToMovement();
}

void UVerseCharacterMovement::InitializeComponent()
{
	Super::InitializeComponent();
	if (!TuningAsset)
	{
		TuningAsset = LoadObject<UVerseMovementTuning>(nullptr, TEXT("/Game/Verse/Movement/DA_MovementTuning.DA_MovementTuning"),
			nullptr, LOAD_NoWarn | LOAD_Quiet);
	}
	SetTuning(TuningAsset ? TuningAsset->Values : UVerseMovementTuning::GetDefaultTuning()->Values);
}

void UVerseCharacterMovement::SetTuning(const FVerseMovementTuningValues& Values)
{
	TuningValues = Values;
	ApplyTuningToMovement();
	if (UpdatedComponent)
	{
		SetBodyShape(BodyShape, false);
	}
}

void UVerseCharacterMovement::ApplyTuningToMovement()
{
	MaxWalkSpeed = TuningValues.WalkSpeedCm();
	MaxWalkSpeedCrouched = TuningValues.CrouchSpeedCm();
	SetCrouchedHalfHeight(TuningValues.CrouchHalfHeightCm());
	const float Gravity = GetWorld() ? GetGravityZ() : -980.f;
	JumpZVelocity = TuningValues.JumpZVelocityCm(Gravity);
}

AVerseCharacter* UVerseCharacterMovement::GetVerseCharacter() const
{
	return Cast<AVerseCharacter>(CharacterOwner);
}

// ---------------------------------------------------------------------------------------------
// IVerseMovementQuery

EVerseStance UVerseCharacterMovement::GetStance() const
{
	if (CharacterOwner && CharacterOwner->GetLocalRole() == ROLE_SimulatedProxy)
	{
		if (const AVerseCharacter* Character = GetVerseCharacter())
		{
			return EVerseStance(Character->ReplicatedStance);
		}
	}
	return Stance;
}

bool UVerseCharacterMovement::IsSprinting() const
{
	if (CharacterOwner && CharacterOwner->GetLocalRole() == ROLE_SimulatedProxy)
	{
		const AVerseCharacter* Character = GetVerseCharacter();
		return Character && Character->bReplicatedSprinting;
	}
	if (!bWantsSprint || Stance != EVerseStance::Stand || MovementMode != MOVE_Walking || ProneTransitionRemaining > 0.f || MantleElapsed >= 0.f)
	{
		return false;
	}
	const FVector Accel = Acceleration.GetSafeNormal2D();
	if (Accel.IsNearlyZero() || !UpdatedComponent)
	{
		return false;
	}
	const FVector Facing = UpdatedComponent->GetForwardVector().GetSafeNormal2D();
	return (Accel | Facing) >= FMath::Cos(FMath::DegreesToRadians(TuningValues.SprintMaxAngleDeg)) - KINDA_SMALL_NUMBER;
}

bool UVerseCharacterMovement::IsAirborne() const
{
	return IsFalling();
}

bool UVerseCharacterMovement::IsMantling() const
{
	if (CharacterOwner && CharacterOwner->GetLocalRole() == ROLE_SimulatedProxy)
	{
		const AVerseCharacter* Character = GetVerseCharacter();
		return Character && Character->bReplicatedMantling;
	}
	return MantleElapsed >= 0.f;
}

int8 UVerseCharacterMovement::GetLeanQuantized() const
{
	if (CharacterOwner && CharacterOwner->GetLocalRole() == ROLE_SimulatedProxy)
	{
		const AVerseCharacter* Character = GetVerseCharacter();
		return Character ? Character->ReplicatedLean : 0;
	}
	return LeanQuantized;
}

float UVerseCharacterMovement::GetProneTransitionAlpha() const
{
	if (ProneTransitionRemaining <= 0.f)
	{
		return 0.f;
	}
	const float Total = bProneExiting ? TuningValues.ProneExitTime : TuningValues.ProneEnterTime;
	const float Alpha = 1.f - ProneTransitionRemaining / FMath::Max(Total, KINDA_SMALL_NUMBER);
	return bProneExiting ? -Alpha : Alpha;
}

EVerseMoveKind UVerseCharacterMovement::GetMoveKind() const
{
	if (IsMantling()) return EVerseMoveKind::Mantle;
	if (IsSliding()) return EVerseMoveKind::Slide;
	if (Stance == EVerseStance::Prone || ProneTransitionRemaining > 0.f) return EVerseMoveKind::Prone;
	if (IsFalling()) return EVerseMoveKind::Airborne;
	if (Stance == EVerseStance::Crouch) return EVerseMoveKind::Crouch;
	if (IsSprinting()) return EVerseMoveKind::Sprint;
	if (LeanQuantized != 0) return EVerseMoveKind::Lean;
	return EVerseMoveKind::Walk;
}

float UVerseCharacterMovement::GetTargetEyeHeight() const
{
	switch (GetStance())
	{
	case EVerseStance::Crouch:
	case EVerseStance::Slide:
		return TuningValues.CrouchEyeHeight * 100.f;
	case EVerseStance::Prone:
		return TuningValues.ProneEyeHeight * 100.f;
	default:
		return TuningValues.StandEyeHeight * 100.f;
	}
}

// ---------------------------------------------------------------------------------------------
// Body shapes

float UVerseCharacterMovement::HalfHeightFor(EVerseBodyShape Shape) const
{
	switch (Shape)
	{
	case EVerseBodyShape::Crouch: return TuningValues.CrouchHalfHeightCm();
	case EVerseBodyShape::Prone: return TuningValues.ProneHalfHeightCm();
	default: return TuningValues.StandHalfHeightCm();
	}
}

float UVerseCharacterMovement::RadiusFor(EVerseBodyShape Shape) const
{
	return Shape == EVerseBodyShape::Prone ? TuningValues.ProneRadius * 100.f : TuningValues.CapsuleRadius * 100.f;
}

FVector UVerseCharacterMovement::GetFeetLocation() const
{
	if (!CharacterOwner || !CharacterOwner->GetCapsuleComponent())
	{
		return FVector::ZeroVector;
	}
	const UCapsuleComponent* Capsule = CharacterOwner->GetCapsuleComponent();
	return Capsule->GetComponentLocation() - FVector(0.f, 0.f, Capsule->GetScaledCapsuleHalfHeight());
}

bool UVerseCharacterMovement::BodyShapeFits(EVerseBodyShape Shape, const FVector& FeetLocation) const
{
	if (!CharacterOwner || !GetWorld())
	{
		return false;
	}
	const float HalfHeight = HalfHeightFor(Shape);
	const float Radius = RadiusFor(Shape);
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseBodyFit), false, CharacterOwner);
	FCollisionResponseParams Response;
	InitCollisionParams(Params, Response);
	const FCollisionShape Capsule = FCollisionShape::MakeCapsule(Radius - 1.f, HalfHeight - 1.f);
	const FVector Center = FeetLocation + FVector(0.f, 0.f, HalfHeight + 1.5f);
	return !GetWorld()->OverlapBlockingTestByChannel(Center, FQuat::Identity, UpdatedComponent->GetCollisionObjectType(), Capsule, Params, Response);
}

bool UVerseCharacterMovement::SetBodyShape(EVerseBodyShape Shape, bool bCheckFit)
{
	if (!CharacterOwner || !CharacterOwner->GetCapsuleComponent())
	{
		BodyShape = Shape;
		return true;
	}
	UCapsuleComponent* Capsule = CharacterOwner->GetCapsuleComponent();
	const float OldHalf = Capsule->GetUnscaledCapsuleHalfHeight();
	const float NewHalf = HalfHeightFor(Shape);
	const float NewRadius = RadiusFor(Shape);
	const bool bSame = FMath::IsNearlyEqual(OldHalf, NewHalf) && FMath::IsNearlyEqual(Capsule->GetUnscaledCapsuleRadius(), NewRadius);
	const FVector Feet = GetFeetLocation();
	if (!bSame && bCheckFit && NewHalf > OldHalf + KINDA_SMALL_NUMBER && !BodyShapeFits(Shape, Feet))
	{
		return false;
	}
	BodyShape = Shape;
	if (bSame)
	{
		return true;
	}
	Capsule->SetCapsuleSize(NewRadius, NewHalf, true);
	// Keep the feet planted. Simulated proxies get their location from the server.
	if (CharacterOwner->GetLocalRole() != ROLE_SimulatedProxy)
	{
		UpdatedComponent->SetWorldLocation(Feet + FVector(0.f, 0.f, NewHalf), false, nullptr, ETeleportType::TeleportPhysics);
		bForceNextFloorCheck = true;
	}
	if (AVerseCharacter* Character = GetVerseCharacter())
	{
		Character->UpdateBodyPose(0.f);
	}
	return true;
}

void UVerseCharacterMovement::ApplyReplicatedStance(EVerseStance NewStance)
{
	const EVerseBodyShape Shape = NewStance == EVerseStance::Prone ? EVerseBodyShape::Prone
		: (NewStance == EVerseStance::Stand ? EVerseBodyShape::Stand : EVerseBodyShape::Crouch);
	SetBodyShape(Shape, false);
}

bool UVerseCharacterMovement::CanEnterProne() const
{
	if (!CharacterOwner || !GetWorld() || !UpdatedComponent)
	{
		return false;
	}
	const FVector Feet = GetFeetLocation();
	const FVector Forward = UpdatedComponent->GetForwardVector().GetSafeNormal2D();
	const float Length = TuningValues.ProneBodyLength * 100.f;
	const float Clearance = TuningValues.ProneMinClearance * 100.f;
	const float HeadForward = TuningValues.ProneRadius * 100.f * 2.f;
	// The body lies from HeadForward in front of the feet point back over Length.
	const float CenterOffset = HeadForward - Length * 0.5f;
	const FVector Center = Feet + Forward * CenterOffset + FVector(0.f, 0.f, 2.f + Clearance * 0.5f);
	const FVector Extent(Length * 0.5f, TuningValues.ProneBodyWidth * 50.f, Clearance * 0.5f - 0.5f);
	const FQuat Rotation = Forward.ToOrientationQuat();
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseProneFit), false, CharacterOwner);
	FCollisionResponseParams Response;
	InitCollisionParams(Params, Response);
	const ECollisionChannel Channel = UpdatedComponent->GetCollisionObjectType();
	if (GetWorld()->OverlapBlockingTestByChannel(Center, Rotation, Channel, FCollisionShape::MakeBox(Extent), Params, Response))
	{
		return false;
	}
	// Floor under both ends: no prone body hanging over a ledge.
	for (const float Along : {HeadForward, HeadForward - Length + 10.f})
	{
		const FVector Top = Feet + Forward * Along + FVector(0.f, 0.f, 20.f);
		FHitResult Floor;
		if (!GetWorld()->LineTraceSingleByChannel(Floor, Top, Top - FVector(0.f, 0.f, 50.f), Channel, Params, Response))
		{
			return false;
		}
	}
	return true;
}

// ---------------------------------------------------------------------------------------------
// Speeds and jump

float UVerseCharacterMovement::GetMaxSpeed() const
{
	if (IsSliding())
	{
		return TuningValues.SlideBoostSpeed * 100.f;
	}
	if (MovementMode != MOVE_Walking && MovementMode != MOVE_NavWalking)
	{
		return Super::GetMaxSpeed();
	}
	if (ProneTransitionRemaining > 0.f)
	{
		return 0.f;
	}
	switch (Stance)
	{
	case EVerseStance::Prone: return TuningValues.ProneSpeedCm();
	case EVerseStance::Crouch: return TuningValues.CrouchSpeedCm();
	default: return IsSprinting() ? TuningValues.SprintSpeedCm() : TuningValues.WalkSpeedCm();
	}
}

float UVerseCharacterMovement::GetMaxBrakingDeceleration() const
{
	return IsSliding() ? 0.f : Super::GetMaxBrakingDeceleration();
}

bool UVerseCharacterMovement::CanAttemptJump() const
{
	if (Stance == EVerseStance::Prone || ProneTransitionRemaining > 0.f || MantleElapsed >= 0.f)
	{
		return false;
	}
	return IsJumpAllowed() && (IsMovingOnGround() || IsFalling() || IsSliding());
}

bool UVerseCharacterMovement::DoJump(bool bReplayingMoves, float DeltaTime)
{
	if (IsSliding())
	{
		EndSlide(false);
	}
	return Super::DoJump(bReplayingMoves, DeltaTime);
}

bool UVerseCharacterMovement::CanCrouchInCurrentState() const
{
	// The stock crouch path is unused: VerseMovement owns the capsule heights.
	return false;
}

// ---------------------------------------------------------------------------------------------
// Per-move state

void UVerseCharacterMovement::UpdateFromCompressedFlags(uint8 Flags)
{
	Super::UpdateFromCompressedFlags(Flags);
	bWantsSprint = (Flags & VerseMoveFlags::Sprint) != 0;
	bWantsProne = (Flags & VerseMoveFlags::Prone) != 0;
	bWantsMantle = (Flags & VerseMoveFlags::Mantle) != 0;
}

void UVerseCharacterMovement::UpdateCharacterStateBeforeMovement(float DeltaSeconds)
{
	Super::UpdateCharacterStateBeforeMovement(DeltaSeconds);
	if (!CharacterOwner || CharacterOwner->GetLocalRole() == ROLE_SimulatedProxy)
	{
		return;
	}
	if (!IsSliding() && SlideCooldownRemaining > 0.f)
	{
		SlideCooldownRemaining = FMath::Max(0.f, SlideCooldownRemaining - DeltaSeconds);
	}
	if (!bWantsMantle)
	{
		bMantleLatched = false;
	}
	if (MantleElapsed >= 0.f)
	{
		UpdateMantle(DeltaSeconds);
	}
	else
	{
		if (bWantsMantle && !bMantleLatched && Stance != EVerseStance::Prone && ProneTransitionRemaining <= 0.f
			&& (IsMovingOnGround() || IsFalling() || IsSliding()))
		{
			TryStartMantle();
		}
		if (MantleElapsed < 0.f)
		{
			if (bWantsToCrouch && !bPrevWantsCrouch && !IsSliding())
			{
				TryStartSlide();
			}
			UpdateStance(DeltaSeconds);
		}
	}
	bPrevWantsCrouch = bWantsToCrouch;
	UpdateLean(DeltaSeconds);
}

void UVerseCharacterMovement::UpdateCharacterStateAfterMovement(float DeltaSeconds)
{
	Super::UpdateCharacterStateAfterMovement(DeltaSeconds);
	if (!CharacterOwner || CharacterOwner->GetLocalRole() == ROLE_SimulatedProxy)
	{
		return;
	}
	if (MantleElapsed >= 0.f)
	{
		MantleElapsed += DeltaSeconds;
		if (MantleElapsed >= MantlePlanDuration - 1e-4f)
		{
			FinishMantle();
		}
	}
	if (CharacterOwner->HasAuthority())
	{
		if (AVerseCharacter* Character = GetVerseCharacter())
		{
			Character->SetReplicatedMovementState(Stance, LeanQuantized, IsSprinting(), MantleElapsed >= 0.f);
		}
	}
}

void UVerseCharacterMovement::UpdateStance(float DeltaSeconds)
{
	if (ProneTransitionRemaining > 0.f)
	{
		ProneTransitionRemaining = FMath::Max(0.f, ProneTransitionRemaining - DeltaSeconds);
		if (ProneTransitionRemaining > 0.f)
		{
			return;
		}
		bProneExiting = false;
	}
	if (IsSliding())
	{
		return;
	}
	const bool bOnGround = IsMovingOnGround();
	if (Stance == EVerseStance::Prone)
	{
		if (bWantsProne)
		{
			return;
		}
		// Leave prone: stand if it fits, else crouch, else stay down.
		const EVerseStance Target = bWantsToCrouch ? EVerseStance::Crouch : EVerseStance::Stand;
		if (Target == EVerseStance::Stand && SetBodyShape(EVerseBodyShape::Stand, true))
		{
			Stance = EVerseStance::Stand;
		}
		else if (SetBodyShape(EVerseBodyShape::Crouch, true))
		{
			Stance = EVerseStance::Crouch;
		}
		else
		{
			return;
		}
		ProneTransitionRemaining = TuningValues.ProneExitTime;
		bProneExiting = true;
		return;
	}
	if (bWantsProne)
	{
		if (bOnGround && CanEnterProne())
		{
			SetBodyShape(EVerseBodyShape::Prone, false);
			Stance = EVerseStance::Prone;
			ProneTransitionRemaining = TuningValues.ProneEnterTime;
			bProneExiting = false;
			Velocity = FVector::ZeroVector;
			return;
		}
	}
	const bool bWantsLow = bWantsToCrouch || bWantsProne;
	if (bWantsLow && Stance == EVerseStance::Stand)
	{
		SetBodyShape(EVerseBodyShape::Crouch, false);
		Stance = EVerseStance::Crouch;
	}
	else if (!bWantsLow && Stance == EVerseStance::Crouch)
	{
		if (SetBodyShape(EVerseBodyShape::Stand, true))
		{
			Stance = EVerseStance::Stand;
		}
	}
}

// ---------------------------------------------------------------------------------------------
// Lean

FVector UVerseCharacterMovement::GetUnleanedEyeLocation() const
{
	return GetFeetLocation() + FVector(0.f, 0.f, GetTargetEyeHeight());
}

FVector UVerseCharacterMovement::GetLeanedEyeLocation(float Lean) const
{
	const FVector Right = UpdatedComponent ? UpdatedComponent->GetRightVector().GetSafeNormal2D() : FVector::RightVector;
	return GetUnleanedEyeLocation() + Right * (Lean * TuningValues.LeanCameraOffset * 100.f);
}

float UVerseCharacterMovement::ComputeLeanAllowance(float Side) const
{
	if (!GetWorld() || !UpdatedComponent || FMath::IsNearlyZero(Side))
	{
		return 1.f;
	}
	const float Offset = TuningValues.LeanCameraOffset * 100.f;
	const float Radius = TuningValues.LeanCameraClearance * 100.f;
	const FVector From = GetUnleanedEyeLocation();
	const FVector To = GetLeanedEyeLocation(FMath::Sign(Side));
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseLeanWall), false, CharacterOwner);
	FHitResult Hit;
	if (!GetWorld()->SweepSingleByChannel(Hit, From, To, FQuat::Identity, ECC_Visibility, FCollisionShape::MakeSphere(Radius), Params))
	{
		return 1.f;
	}
	if (Hit.bStartPenetrating)
	{
		return 0.f;
	}
	return FMath::Clamp((Hit.Distance - 1.f) / Offset, 0.f, 1.f);
}

void UVerseCharacterMovement::UpdateLean(float DeltaSeconds)
{
	const bool bAllowed = (Stance == EVerseStance::Stand || Stance == EVerseStance::Crouch) && !IsSprinting()
		&& MantleElapsed < 0.f && ProneTransitionRemaining <= 0.f;
	const float Target = bAllowed ? IVerseMovementQuery::LeanFromQuantized(LeanTargetQuantized) : 0.f;
	const float Current = IVerseMovementQuery::LeanFromQuantized(LeanQuantized);
	const float Step = DeltaSeconds / FMath::Max(TuningValues.LeanEnterTime, KINDA_SMALL_NUMBER);
	float Next = FMath::Abs(Target - Current) <= Step ? Target : Current + FMath::Sign(Target - Current) * Step;
	if (!FMath::IsNearlyZero(Next))
	{
		const float Allowance = ComputeLeanAllowance(Next);
		Next = FMath::Sign(Next) * FMath::Min(FMath::Abs(Next), Allowance);
	}
	LeanQuantized = IVerseMovementQuery::QuantizeLean(Next);
	if (LeanQuantized != 0 && ComputeLeanAllowance(LeanQuantized) * 127.f < FMath::Abs(float(LeanQuantized)))
	{
		// Rounding moved the camera past the wall check: step back toward zero.
		LeanQuantized = int8(LeanQuantized > 0 ? LeanQuantized - 1 : LeanQuantized + 1);
	}
}

// ---------------------------------------------------------------------------------------------
// Slide (MOVE_Custom / CMOVE_Slide)

bool UVerseCharacterMovement::TryStartSlide()
{
	if (Stance != EVerseStance::Stand || !IsSprinting() || SlideCooldownRemaining > 0.f)
	{
		return false;
	}
	const float Speed = Velocity.Size2D();
	if (Speed < TuningValues.SlideMinEntrySpeed * 100.f - 0.5f)
	{
		return false;
	}
	SetBodyShape(EVerseBodyShape::Crouch, false);
	Stance = EVerseStance::Slide;
	SlideElapsed = 0.f;
	Velocity = Velocity.GetSafeNormal2D() * FMath::Max(Speed, TuningValues.SlideBoostSpeed * 100.f);
	SetMovementMode(MOVE_Custom, uint8(EVerseCustomMove::Slide));
	EmitNoise(VerseTags::Noise_Move_Slide, GetFeetLocation());
	return true;
}

void UVerseCharacterMovement::EndSlide(bool bToFalling)
{
	if (!IsSliding())
	{
		return;
	}
	SlideCooldownRemaining = TuningValues.SlideCooldown;
	Stance = EVerseStance::Crouch;
	SetMovementMode(bToFalling ? MOVE_Falling : MOVE_Walking);
}

void UVerseCharacterMovement::PhysCustom(float DeltaTime, int32 Iterations)
{
	if (CustomMovementMode == uint8(EVerseCustomMove::Slide))
	{
		PhysSlide(DeltaTime, Iterations);
		return;
	}
	Super::PhysCustom(DeltaTime, Iterations);
}

void UVerseCharacterMovement::PhysSlide(float DeltaTime, int32 Iterations)
{
	if (DeltaTime < MIN_TICK_TIME)
	{
		return;
	}
	SlideElapsed += DeltaTime;
	const float CrouchCm = TuningValues.CrouchSpeedCm();
	const float BoostCm = TuningValues.SlideBoostSpeed * 100.f;
	const float Alpha = FMath::Clamp(SlideElapsed / FMath::Max(TuningValues.SlideMaxDuration, KINDA_SMALL_NUMBER), 0.f, 1.f);
	const float Cap = CrouchCm + (BoostCm - CrouchCm) * FMath::Pow(1.f - Alpha, FMath::Max(TuningValues.SlideDecayExponent, 0.1f));
	FVector Direction = Velocity.GetSafeNormal2D();
	if (Direction.IsNearlyZero())
	{
		EndSlide(false);
		return;
	}
	const float Speed = FMath::Min(Velocity.Size2D(), Cap);
	Velocity = Direction * Speed;

	const FVector OldLocation = UpdatedComponent->GetComponentLocation();
	FVector Delta = Velocity * DeltaTime;
	if (CurrentFloor.IsWalkableFloor())
	{
		Delta = ComputeGroundMovementDelta(Delta, CurrentFloor.HitResult, CurrentFloor.bLineTrace);
	}
	FHitResult Hit(1.f);
	SafeMoveUpdatedComponent(Delta, UpdatedComponent->GetComponentQuat(), true, Hit);
	if (Hit.IsValidBlockingHit() && Hit.Time < 1.f)
	{
		const FVector Remaining = Delta * (1.f - Hit.Time);
		const bool bStepped = CanStepUp(Hit) && IsWalkable(Hit) == false && StepUp(-GetGravityDirection(), Remaining, Hit);
		if (!bStepped)
		{
			HandleImpact(Hit, DeltaTime, Delta);
			SlideAlongSurface(Remaining, 1.f, Hit.Normal, Hit, true);
		}
	}

	FindFloor(UpdatedComponent->GetComponentLocation(), CurrentFloor, false);
	if (!CurrentFloor.IsWalkableFloor())
	{
		EndSlide(true);
		return;
	}
	AdjustFloorHeight();
	SetBaseFromFloor(CurrentFloor);
	if (!bJustTeleported)
	{
		const FVector Moved = (UpdatedComponent->GetComponentLocation() - OldLocation) / DeltaTime;
		const float MovedSpeed = FMath::Min(Moved.Size2D(), Speed);
		Velocity = Moved.GetSafeNormal2D() * MovedSpeed;
	}
	if (Alpha >= 1.f || Velocity.Size2D() <= CrouchCm + 1.f || !bWantsToCrouch)
	{
		EndSlide(false);
	}
}

// ---------------------------------------------------------------------------------------------
// Mantle

bool UVerseCharacterMovement::FindMantle(FVerseMantlePlan& OutPlan) const
{
	if (!CharacterOwner || !GetWorld() || !UpdatedComponent)
	{
		return false;
	}
	const UWorld* World = GetWorld();
	const FVector Feet = GetFeetLocation();
	const FVector Forward = UpdatedComponent->GetForwardVector().GetSafeNormal2D();
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseMantle), false, CharacterOwner);
	FCollisionResponseParams Response;
	InitCollisionParams(Params, Response);
	const ECollisionChannel Channel = UpdatedComponent->GetCollisionObjectType();
	const float MinHeight = TuningValues.MantleMinHeight * 100.f;
	const float MaxHeight = TuningValues.MantleHighMaxHeight * 100.f;
	const float Radius = TuningValues.CapsuleRadius * 100.f;

	// Heights count from the floor the person stands (or jumped) on, so a jump never stretches the range.
	float FloorZ = Feet.Z;
	if (!IsMovingOnGround() && !IsSliding())
	{
		FHitResult Floor;
		if (World->LineTraceSingleByChannel(Floor, Feet, Feet - FVector(0.f, 0.f, 250.f), Channel, Params, Response))
		{
			FloorZ = Floor.ImpactPoint.Z;
		}
	}

	// 1. A ledge face ahead, low enough to be under the shortest ledge's top.
	const FVector ProbeStart(Feet.X, Feet.Y, FMath::Max(FloorZ + MinHeight - 12.f, Feet.Z + WallProbeRadius + 2.f));
	const FVector ProbeEnd = ProbeStart + Forward * (Radius + TuningValues.MantleReach * 100.f);
	FHitResult Wall;
	if (!World->SweepSingleByChannel(Wall, ProbeStart, ProbeEnd, FQuat::Identity, Channel, FCollisionShape::MakeSphere(WallProbeRadius), Params, Response)
		|| Wall.bStartPenetrating)
	{
		return false;
	}
	const FVector Normal = Wall.ImpactNormal.GetSafeNormal2D();
	if (Normal.IsNearlyZero() || Wall.ImpactNormal.Z > 0.7f
		|| (Normal | -Forward) < FMath::Cos(FMath::DegreesToRadians(TuningValues.MantleMaxFaceAngleDeg)))
	{
		return false;
	}
	const FVector Into = -Normal;
	const FVector Face = Wall.ImpactPoint;
	const FVector Inside = Face + Into * 15.f;

	// 2. The top: trace down from the highest free start above the face. A wall taller than the
	// mantle range has no free start, so it never mantles; a breach has one inside its opening.
	bool bFound = false;
	float LedgeZ = 0.f;
	for (float StartZ = FloorZ + MaxHeight + ProbeRadius + 1.f; StartZ >= FloorZ + MinHeight; StartZ -= 40.f)
	{
		const FVector Start(Inside.X, Inside.Y, StartZ);
		if (World->OverlapBlockingTestByChannel(Start, FQuat::Identity, Channel, FCollisionShape::MakeSphere(ProbeRadius), Params, Response))
		{
			continue;
		}
		FHitResult Top;
		const FVector End(Inside.X, Inside.Y, FloorZ + MinHeight - 15.f);
		if (World->SweepSingleByChannel(Top, Start, End, FQuat::Identity, Channel, FCollisionShape::MakeSphere(ProbeRadius), Params, Response)
			&& !Top.bStartPenetrating && Top.ImpactNormal.Z >= 0.7f)
		{
			LedgeZ = Top.ImpactPoint.Z;
			bFound = true;
		}
		break;
	}
	if (!bFound)
	{
		return false;
	}
	const float Height = LedgeZ - FloorZ;
	if (Height < MinHeight - 2.f || Height > MaxHeight + 0.5f)
	{
		return false;
	}

	// 3. Deep top or thin wall (vault through a breach or over a parapet).
	float Thickness = -1.f;
	{
		const FVector Back = Face + Into * 160.f + FVector(0.f, 0.f, LedgeZ - Face.Z - 8.f);
		const FVector BackEnd(Face.X, Face.Y, Back.Z);
		FHitResult FarFace;
		if (World->LineTraceSingleByChannel(FarFace, Back, BackEnd, Channel, Params, Response) && !FarFace.bStartPenetrating
			&& (FarFace.ImpactNormal | Into) > 0.5f)
		{
			Thickness = (FarFace.ImpactPoint - Face) | Into;
		}
	}
	const bool bVault = Thickness > 0.f && Thickness < Radius * 2.f;
	const float Along = bVault ? Thickness + Radius + 8.f : Radius + 8.f;
	const FVector TargetXY = Face + Into * Along;

	// 4. The body that fits: standing, else crouched.
	const FVector StartCenter = UpdatedComponent->GetComponentLocation();
	for (const EVerseBodyShape Shape : {EVerseBodyShape::Stand, EVerseBodyShape::Crouch})
	{
		const float Half = HalfHeightFor(Shape);
		const float ShapeRadius = RadiusFor(Shape);
		const FVector Target(TargetXY.X, TargetXY.Y, LedgeZ + Half + 2.f);
		if (!BodyShapeFits(Shape, Target - FVector(0.f, 0.f, Half + 1.5f)))
		{
			continue;
		}
		const FVector Start(StartCenter.X, StartCenter.Y, Feet.Z + Half);
		const FVector Rise(StartCenter.X, StartCenter.Y, FMath::Max(Target.Z, Start.Z));
		const FCollisionShape Body = FCollisionShape::MakeCapsule(ShapeRadius - 2.f, Half - 2.f);
		FHitResult Block;
		if (World->SweepSingleByChannel(Block, Start, Rise, FQuat::Identity, Channel, Body, Params, Response)
			|| World->SweepSingleByChannel(Block, Rise, Target, FQuat::Identity, Channel, Body, Params, Response))
		{
			continue;
		}
		OutPlan.Start = Start;
		OutPlan.Rise = Rise;
		OutPlan.Target = Target;
		OutPlan.LedgeHeight = Height;
		OutPlan.bHigh = Height > TuningValues.MantleLowMaxHeight * 100.f;
		OutPlan.Duration = OutPlan.bHigh ? TuningValues.MantleHighDuration : TuningValues.MantleLowDuration;
		OutPlan.bCrouched = Shape == EVerseBodyShape::Crouch;
		OutPlan.bVault = bVault;
		return true;
	}
	return false;
}

bool UVerseCharacterMovement::TryStartMantle()
{
	FVerseMantlePlan Plan;
	if (!FindMantle(Plan))
	{
		return false;
	}
	if (IsSliding())
	{
		EndSlide(false);
	}
	if (Plan.bCrouched)
	{
		SetBodyShape(EVerseBodyShape::Crouch, false);
		Stance = EVerseStance::Crouch;
	}
	bMantleLatched = true;
	MantleElapsed = 0.f;
	MantlePlanDuration = Plan.Duration;
	MantleRiseDuration = Plan.Duration * FMath::Clamp(TuningValues.MantleRiseFraction, 0.1f, 0.9f);
	MantleRise = Plan.Rise;
	MantleTarget = Plan.Target;
	bMantleVault = Plan.bVault;
	++MantleCount;
	Velocity = FVector::ZeroVector;
	SetMovementMode(MOVE_Flying);
	ApplyMantleSource(UpdatedComponent->GetComponentLocation(), MantleRise, MantleRiseDuration);
	EmitNoise(VerseTags::Noise_Move_Mantle, GetFeetLocation());
	return true;
}

void UVerseCharacterMovement::ApplyMantleSource(const FVector& From, const FVector& To, float Duration)
{
	const bool bRise = MantleElapsed < MantleRiseDuration - 1e-4f;
	TSharedPtr<FRootMotionSource_MoveToForce> Source = MakeShared<FRootMotionSource_MoveToForce>();
	Source->InstanceName = bRise ? MantleRiseSource : MantleMoveSource;
	Source->AccumulateMode = ERootMotionAccumulateMode::Override;
	Source->Priority = 500;
	Source->StartLocation = From;
	Source->TargetLocation = To;
	Source->Duration = FMath::Max(Duration, 1e-3f);
	Source->bRestrictSpeedToExpected = true;
	Source->FinishVelocityParams.Mode = ERootMotionFinishVelocityMode::SetVelocity;
	Source->FinishVelocityParams.SetVelocity = FVector::ZeroVector;
	ApplyRootMotionSource(Source);
}

void UVerseCharacterMovement::UpdateMantle(float DeltaSeconds)
{
	if (MantleElapsed >= MantleRiseDuration - 1e-4f && GetRootMotionSource(MantleRiseSource).IsValid())
	{
		RemoveRootMotionSource(MantleRiseSource);
		ApplyMantleSource(UpdatedComponent->GetComponentLocation(), MantleTarget, MantlePlanDuration - MantleElapsed);
	}
	else if (MantleElapsed >= MantleRiseDuration - 1e-4f && !GetRootMotionSource(MantleMoveSource).IsValid())
	{
		// Replayed or restored mid-mantle without the second source: re-apply it.
		ApplyMantleSource(UpdatedComponent->GetComponentLocation(), MantleTarget, MantlePlanDuration - MantleElapsed);
	}
}

void UVerseCharacterMovement::FinishMantle()
{
	RemoveRootMotionSource(MantleRiseSource);
	RemoveRootMotionSource(MantleMoveSource);
	MantleElapsed = -1.f;
	const FVector Forward = UpdatedComponent->GetForwardVector().GetSafeNormal2D();
	if (bMantleVault)
	{
		SetMovementMode(MOVE_Falling);
		Velocity = Forward * 150.f;
	}
	else
	{
		Velocity = FVector::ZeroVector;
		SetMovementMode(MOVE_Walking);
	}
	bMantleVault = false;
}

// ---------------------------------------------------------------------------------------------
// Noise

void UVerseCharacterMovement::EmitNoise(const FGameplayTag& Noise, const FVector& Location)
{
	if (!CharacterOwner || CharacterOwner->bClientUpdating)
	{
		return; // never twice for a replayed move
	}
	FVerseNoiseEvent Event;
	Event.Noise = Noise;
	Event.SourceId = CharacterOwner->GetPlayerState() ? CharacterOwner->GetPlayerState()->GetPlayerId() : 0;
	Event.Location = Location;
	Event.Loudness = 1.f;
	Event.ServerTime = GetWorld() ? float(GetWorld()->GetTimeSeconds()) : 0.f;
	OnFootstep.Broadcast(Event, CurrentFloor.HitResult.PhysMaterial.Get());
	if (CharacterOwner->HasAuthority())
	{
		if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
		{
			Hub->OnNoise.Broadcast(Event);
		}
	}
}

void UVerseCharacterMovement::UpdateFootsteps(float DeltaSeconds, const FVector& OldLocation)
{
	if (MovementMode != MOVE_Walking || Stance != EVerseStance::Stand || ProneTransitionRemaining > 0.f)
	{
		// Crouch walk and prone crawl are silent (bot.md 3.2); the stride restarts on standing.
		StrideRemaining = 0.f;
		return;
	}
	const float Moved = FVector::Dist2D(UpdatedComponent->GetComponentLocation(), OldLocation);
	if (Moved < KINDA_SMALL_NUMBER)
	{
		return;
	}
	StrideRemaining -= Moved;
	if (StrideRemaining > 0.f)
	{
		return;
	}
	const float Speed = DeltaSeconds > 0.f ? Moved / DeltaSeconds : 0.f;
	FGameplayTag Tag = VerseTags::Noise_Footstep_Walk;
	float Stride = TuningValues.WalkStride;
	if (IsSprinting())
	{
		Tag = VerseTags::Noise_Footstep_Sprint;
		Stride = TuningValues.SprintStride;
	}
	else if (Speed > TuningValues.QuietWalkMaxSpeed * 100.f)
	{
		Tag = VerseTags::Noise_Footstep_Run;
		Stride = TuningValues.RunStride;
	}
	StrideRemaining += Stride * 100.f;
	EmitNoise(Tag, GetFeetLocation());
}

void UVerseCharacterMovement::OnMovementUpdated(float DeltaSeconds, const FVector& OldLocation, const FVector& OldVelocity)
{
	Super::OnMovementUpdated(DeltaSeconds, OldLocation, OldVelocity);
	if (CharacterOwner && CharacterOwner->GetLocalRole() != ROLE_SimulatedProxy)
	{
		UpdateFootsteps(DeltaSeconds, OldLocation);
	}
}

void UVerseCharacterMovement::ProcessLanded(const FHitResult& Hit, float RemainingTime, int32 Iterations)
{
	if (-Velocity.Z >= TuningValues.LandNoiseMinFallSpeed * 100.f)
	{
		EmitNoise(VerseTags::Noise_Move_Land, GetFeetLocation());
	}
	Super::ProcessLanded(Hit, RemainingTime, Iterations);
}

void UVerseCharacterMovement::OnMovementModeChanged(EMovementMode PreviousMovementMode, uint8 PreviousCustomMode)
{
	Super::OnMovementModeChanged(PreviousMovementMode, PreviousCustomMode);
	const bool bWasSliding = PreviousMovementMode == MOVE_Custom && PreviousCustomMode == uint8(EVerseCustomMove::Slide);
	if (bWasSliding && !IsSliding() && Stance == EVerseStance::Slide)
	{
		Stance = EVerseStance::Crouch;
		SlideCooldownRemaining = TuningValues.SlideCooldown;
	}
}

// ---------------------------------------------------------------------------------------------
// Tick, networking

void UVerseCharacterMovement::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	const uint64 Start = FPlatformTime::Cycles64();
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	TickCycles += FPlatformTime::Cycles64() - Start;
	++TickCountTotal;
	if (AVerseCharacter* Character = GetVerseCharacter())
	{
		Character->UpdateBodyPose(DeltaTime);
	}
}

FNetworkPredictionData_Client* UVerseCharacterMovement::GetPredictionData_Client() const
{
	if (!ClientPredictionData)
	{
		UVerseCharacterMovement* MutableThis = const_cast<UVerseCharacterMovement*>(this);
		MutableThis->ClientPredictionData = new FVerseNetworkPredictionData_Client(*this);
	}
	return ClientPredictionData;
}

void UVerseCharacterMovement::MoveAutonomous(float ClientTimeStamp, float DeltaTime, uint8 CompressedFlags, const FVector& NewAccel)
{
	const bool bServerOfRemote = CharacterOwner && CharacterOwner->GetLocalRole() == ROLE_Authority
		&& CharacterOwner->GetRemoteRole() == ROLE_AutonomousProxy;
	if (bServerOfRemote)
	{
		if (const FVerseCharacterNetworkMoveData* Data = static_cast<const FVerseCharacterNetworkMoveData*>(GetCurrentNetworkMoveData()))
		{
			LeanTargetQuantized = Data->LeanTarget;
			PendingClientLean = Data->LeanResult;
		}
	}
	Super::MoveAutonomous(ClientTimeStamp, DeltaTime, CompressedFlags, NewAccel);
	if (bServerOfRemote && PendingClientLean != NoClientLean)
	{
		++NetStats.ServerMoves;
		if (FMath::Abs(int32(PendingClientLean) - int32(LeanQuantized)) <= LeanAdoptTolerance)
		{
			LeanQuantized = int8(PendingClientLean);
		}
		else
		{
			++NetStats.LeanMismatches;
		}
		PendingClientLean = NoClientLean;
		if (AVerseCharacter* Character = GetVerseCharacter())
		{
			Character->SetReplicatedMovementState(Stance, LeanQuantized, IsSprinting(), MantleElapsed >= 0.f);
		}
	}
}

void UVerseCharacterMovement::OnClientCorrectionReceived(FNetworkPredictionData_Client_Character& ClientData, float TimeStamp, FVector NewLocation,
	FVector NewVelocity, UPrimitiveComponent* NewBase, FName NewBaseBoneName, bool bHasBase, bool bBaseRelativePosition, uint8 ServerMovementMode,
	FVector ServerGravityDirection)
{
	++NetStats.Corrections[int32(GetMoveKind())];
	UE_LOG(LogVerseMovement, Verbose, TEXT("correction during %s at %.3f"), *StaticEnum<EVerseMoveKind>()->GetNameStringByValue(int64(GetMoveKind())), TimeStamp);
	Super::OnClientCorrectionReceived(ClientData, TimeStamp, NewLocation, NewVelocity, NewBase, NewBaseBoneName, bHasBase, bBaseRelativePosition,
		ServerMovementMode, ServerGravityDirection);
}

// ---------------------------------------------------------------------------------------------
// Saved moves and move data

void FVerseMoveState::Capture(const UVerseCharacterMovement& M)
{
	Stance = M.Stance;
	BodyShape = M.BodyShape;
	LeanQuantized = M.LeanQuantized;
	ProneTransitionRemaining = M.ProneTransitionRemaining;
	bProneExiting = M.bProneExiting;
	SlideElapsed = M.SlideElapsed;
	SlideCooldownRemaining = M.SlideCooldownRemaining;
	bPrevWantsCrouch = M.bPrevWantsCrouch;
	bMantleLatched = M.bMantleLatched;
	MantleElapsed = M.MantleElapsed;
	MantlePlanDuration = M.MantlePlanDuration;
	MantleRiseDuration = M.MantleRiseDuration;
	MantleRise = M.MantleRise;
	MantleTarget = M.MantleTarget;
	bMantleVault = M.bMantleVault;
	StrideRemaining = M.StrideRemaining;
}

void FVerseMoveState::Restore(UVerseCharacterMovement& M) const
{
	M.Stance = Stance;
	if (M.BodyShape != BodyShape)
	{
		M.SetBodyShape(BodyShape, false);
	}
	M.LeanQuantized = LeanQuantized;
	M.ProneTransitionRemaining = ProneTransitionRemaining;
	M.bProneExiting = bProneExiting;
	M.SlideElapsed = SlideElapsed;
	M.SlideCooldownRemaining = SlideCooldownRemaining;
	M.bPrevWantsCrouch = bPrevWantsCrouch;
	M.bMantleLatched = bMantleLatched;
	M.MantleElapsed = MantleElapsed;
	M.MantlePlanDuration = MantlePlanDuration;
	M.MantleRiseDuration = MantleRiseDuration;
	M.MantleRise = MantleRise;
	M.MantleTarget = MantleTarget;
	M.bMantleVault = bMantleVault;
	M.StrideRemaining = StrideRemaining;
}

void FVerseSavedMove::Clear()
{
	Super::Clear();
	bSavedWantsSprint = false;
	bSavedWantsProne = false;
	bSavedWantsMantle = false;
	SavedLeanTarget = 0;
	SavedLeanResult = 0;
	StartState = FVerseMoveState();
}

uint8 FVerseSavedMove::GetCompressedFlags() const
{
	uint8 Flags = Super::GetCompressedFlags();
	if (bSavedWantsSprint) Flags |= VerseMoveFlags::Sprint;
	if (bSavedWantsProne) Flags |= VerseMoveFlags::Prone;
	if (bSavedWantsMantle) Flags |= VerseMoveFlags::Mantle;
	return Flags;
}

bool FVerseSavedMove::CanCombineWith(const FSavedMovePtr& NewMove, ACharacter* InCharacter, float MaxDelta) const
{
	const FVerseSavedMove* Other = static_cast<const FVerseSavedMove*>(NewMove.Get());
	if (bSavedWantsSprint != Other->bSavedWantsSprint || bSavedWantsProne != Other->bSavedWantsProne
		|| bSavedWantsMantle != Other->bSavedWantsMantle || SavedLeanTarget != Other->SavedLeanTarget
		|| StartState.Stance != Other->StartState.Stance || StartState.LeanQuantized != Other->StartState.LeanQuantized
		|| StartState.MantleElapsed >= 0.f || Other->StartState.MantleElapsed >= 0.f
		|| StartState.ProneTransitionRemaining > 0.f || StartState.Stance == EVerseStance::Slide)
	{
		return false;
	}
	return Super::CanCombineWith(NewMove, InCharacter, MaxDelta);
}

void FVerseSavedMove::SetMoveFor(ACharacter* C, float InDeltaTime, FVector const& NewAccel, FNetworkPredictionData_Client_Character& ClientData)
{
	if (const UVerseCharacterMovement* M = Cast<UVerseCharacterMovement>(C->GetCharacterMovement()))
	{
		bSavedWantsSprint = M->bWantsSprint;
		bSavedWantsProne = M->bWantsProne;
		bSavedWantsMantle = M->bWantsMantle;
		SavedLeanTarget = M->LeanTargetQuantized;
	}
	Super::SetMoveFor(C, InDeltaTime, NewAccel, ClientData);
}

void FVerseSavedMove::SetInitialPosition(ACharacter* C)
{
	Super::SetInitialPosition(C);
	if (const UVerseCharacterMovement* M = Cast<UVerseCharacterMovement>(C->GetCharacterMovement()))
	{
		StartState.Capture(*M);
	}
}

void FVerseSavedMove::PrepMoveFor(ACharacter* C)
{
	Super::PrepMoveFor(C);
	if (UVerseCharacterMovement* M = Cast<UVerseCharacterMovement>(C->GetCharacterMovement()))
	{
		StartState.Restore(*M);
		M->LeanTargetQuantized = SavedLeanTarget;
	}
}

void FVerseSavedMove::PostUpdate(ACharacter* C, EPostUpdateMode PostUpdateMode)
{
	Super::PostUpdate(C, PostUpdateMode);
	if (const UVerseCharacterMovement* M = Cast<UVerseCharacterMovement>(C->GetCharacterMovement()))
	{
		SavedLeanResult = M->LeanQuantized;
	}
}

bool FVerseSavedMove::IsImportantMove(const FSavedMovePtr& LastAckedMove) const
{
	const FVerseSavedMove* Acked = static_cast<const FVerseSavedMove*>(LastAckedMove.Get());
	if (Acked && (Acked->bSavedWantsProne != bSavedWantsProne || Acked->bSavedWantsMantle != bSavedWantsMantle))
	{
		return true;
	}
	return Super::IsImportantMove(LastAckedMove);
}

void FVerseCharacterNetworkMoveData::ClientFillNetworkMoveData(const FSavedMove_Character& ClientMove, ENetworkMoveType MoveType)
{
	FCharacterNetworkMoveData::ClientFillNetworkMoveData(ClientMove, MoveType);
	const FVerseSavedMove& Move = static_cast<const FVerseSavedMove&>(ClientMove);
	LeanTarget = Move.SavedLeanTarget;
	LeanResult = Move.SavedLeanResult;
}

bool FVerseCharacterNetworkMoveData::Serialize(UCharacterMovementComponent& CharacterMovement, FArchive& Ar, UPackageMap* PackageMap, ENetworkMoveType MoveType)
{
	FCharacterNetworkMoveData::Serialize(CharacterMovement, Ar, PackageMap, MoveType);
	Ar << LeanTarget;
	Ar << LeanResult;
	return !Ar.IsError();
}

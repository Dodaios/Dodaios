#pragma once

#include "CoreMinimal.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Movement/VerseMovementQuery.h"
#include "VerseMovementTuning.h"

#include "VerseCharacterMovement.generated.h"

class AVerseCharacter;
class UPhysicalMaterial;

/** Custom movement modes (MOVE_Custom sub-modes, architecture.md 3.3). */
UENUM(BlueprintType)
enum class EVerseCustomMove : uint8
{
	None = 0,
	Slide = 1 // CMOVE_Slide
};

/** Move kinds the correction counters are kept per (work-packages.md WP01.10). */
UENUM(BlueprintType)
enum class EVerseMoveKind : uint8
{
	Walk,
	Sprint,
	Crouch,
	Prone,
	Slide,
	Mantle,
	Airborne,
	Lean,
	Count UMETA(Hidden)
};

/** Capsule shapes of the three body heights. */
enum class EVerseBodyShape : uint8
{
	Stand,
	Crouch,
	Prone
};

/** A ledge the mantle trace found (computed identically on client and server). */
struct FVerseMantlePlan
{
	FVector Start = FVector::ZeroVector;
	FVector Rise = FVector::ZeroVector;
	FVector Target = FVector::ZeroVector;
	float LedgeHeight = 0.f;
	float Duration = 0.f;
	bool bHigh = false;
	bool bCrouched = false;
	/** Through a breach or over a thin wall: the target is beyond the wall, in the air. */
	bool bVault = false;
};

/** Per-move-kind client correction counts plus the server's lean comparison. */
USTRUCT(BlueprintType)
struct VERSEMOVEMENT_API FVerseMovementNetStats
{
	GENERATED_BODY()

	/** Client: corrections received, indexed by EVerseMoveKind. */
	int32 Corrections[int32(EVerseMoveKind::Count)] = {};
	/** Server: client moves received / moves whose lean the server could not adopt. */
	int32 ServerMoves = 0;
	int32 LeanMismatches = 0;
	/** Server: moves whose own lean simulation differed from the client's by more than the tolerance. */
	int32 LeanSimDiffs = 0;
	/** Server: moves whose yaw the prone turn cap clamped (a client turning faster than allowed). */
	int32 YawClamps = 0;

	int32 Total() const;
	FString ToJson() const;
};

DECLARE_MULTICAST_DELEGATE_TwoParams(FOnVerseFootstep, const FVerseNoiseEvent& /*Noise*/, const UPhysicalMaterial* /*Surface*/);

/**
 * The Verse character movement (architecture.md 3.3): stock CMC walk, sprint, crouch and jump
 * plus slide (MOVE_Custom / CMOVE_Slide), prone (a third capsule height plus a prone body box),
 * mantle (a predicted FRootMotionSource_MoveToForce after a ledge trace both sides run at the
 * same move time) and lean (a quantised value in the custom move data). It implements
 * IVerseMovementQuery; nothing outside VerseMovement touches this component.
 *
 * Inputs come only from AVerseCharacter::ApplyInputFrame (person and bot, bot.md B1); they set
 * the "wants" below, which travel as compressed flags and move data.
 */
UCLASS()
class VERSEMOVEMENT_API UVerseCharacterMovement : public UCharacterMovementComponent, public IVerseMovementQuery
{
	GENERATED_BODY()

	friend class FVerseSavedMove;
	friend struct FVerseCharacterNetworkMoveData;
	friend struct FVerseMoveState;
	friend struct FVerseMoveResponseDataContainer;

public:
	UVerseCharacterMovement(const FObjectInitializer& ObjectInitializer);

	// IVerseMovementQuery
	virtual EVerseStance GetStance() const override;
	virtual bool IsSprinting() const override;
	virtual bool IsAirborne() const override;
	virtual bool IsMantling() const override;
	virtual int8 GetLeanQuantized() const override;

	/** Tuning in use (DA_MovementTuning or the JSON default). */
	const FVerseMovementTuningValues& Tuning() const { return TuningValues; }
	void SetTuning(const FVerseMovementTuningValues& Values);

	// Wants, set by AVerseCharacter::ApplyInputFrame on the controlling machine.
	void SetWantsSprint(bool bWants) { bWantsSprint = bWants; }
	void SetWantsProne(bool bWants) { bWantsProne = bWants; }
	void SetWantsMantle(bool bWants) { bWantsMantle = bWants; }
	void SetLeanTarget(int8 Target) { LeanTargetQuantized = Target; }

	/** Lean -1..1 as the camera and hit bodies use it (the dequantised move value). */
	float GetLean() const;
	/** Feet-relative eye height of the current stance and transition. */
	float GetTargetEyeHeight() const;
	bool IsSliding() const { return MovementMode == MOVE_Custom && CustomMovementMode == uint8(EVerseCustomMove::Slide); }
	bool IsProne() const { return Stance == EVerseStance::Prone; }
	/** 0..1 progress of a prone enter (positive) or exit (negative); 0 when settled. */
	float GetProneTransitionAlpha() const;
	float GetSlideCooldownRemaining() const { return SlideCooldownRemaining; }
	float GetMantleElapsed() const { return MantleElapsed; }
	float GetMantleDuration() const { return MantlePlanDuration; }
	/** Mantles started (server and client count their own). */
	int32 GetMantleCount() const { return MantleCount; }
	EVerseMoveKind GetMoveKind() const;

	/** The mantle a jump press would start now, without starting it. */
	bool FindMantle(FVerseMantlePlan& OutPlan) const;
	/** True when the prone body fits at the current location and facing. */
	bool CanEnterProne() const;
	/** True when the prone body (feet to head, above the lowest step) overlaps geometry at a feet point and yaw. */
	bool ProneBodyBlocked(const FVector& FeetLocation, float Yaw) const;
	/** Largest lean (0..1) toward Side (-1 left, +1 right) the wall check allows now. */
	float ComputeLeanAllowance(float Side) const;
	/**
	 * The eye (the skeleton's Camera bone, bot.md 3.1) relative to the feet in the actor's yaw frame
	 * (X forward, Y right, Z up) for an eye height, a lean and a prone blend (0 upright, 1 lying).
	 * Lean rolls the body about a pivot below the eye so the eye moves LeanCameraOffset sideways at
	 * full lean. The placeholder pose puts the Camera bone exactly here; the camera reads the bone.
	 */
	FVector GetEyeOffset(float EyeHeight, float Lean, float ProneAlpha) const;
	/** Eye location without lean (world), for the settled current stance. */
	FVector GetUnleanedEyeLocation() const;
	/** Eye location with the lean applied (world), for the settled current stance. */
	FVector GetLeanedEyeLocation(float Lean) const;
	FVector GetFeetLocation() const;

	FVerseMovementNetStats& GetNetStats() { return NetStats; }
	const FVerseMovementNetStats& GetNetStats() const { return NetStats; }

	/**
	 * Game-thread cycles of this pawn's whole movement path (WP01 A1.9): the component tick with
	 * the body pose, the character's input tick and, on a server, the client move RPC handling.
	 */
	uint64 GetTickCycles() const { return TickCycles; }
	int32 GetTickCount() const { return TickCountTotal; }
	void AddMovementCycles(uint64 Cycles) { TickCycles += Cycles; }

	/** Footsteps and movement noise on every machine, with the surface (audio, WP19). */
	FOnVerseFootstep OnFootstep;

	/**
	 * Applies the capsule of a body shape, keeping the feet planted (bKeepFeet) or the centre
	 * (replays: the server's corrected location already belongs to that shape). False when it does not fit.
	 */
	bool SetBodyShape(EVerseBodyShape Shape, bool bCheckFit, bool bKeepFeet = true);
	EVerseBodyShape GetBodyShape() const { return BodyShape; }
	/** For simulated proxies: adopt the replicated stance without checks. */
	void ApplyReplicatedStance(EVerseStance NewStance);

	// UCharacterMovementComponent
	virtual void InitializeComponent() override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
	virtual float GetMaxSpeed() const override;
	virtual float GetMaxBrakingDeceleration() const override;
	virtual bool CanAttemptJump() const override;
	using UCharacterMovementComponent::DoJump;
	virtual bool DoJump(bool bReplayingMoves, float DeltaTime) override;
	virtual bool CanCrouchInCurrentState() const override;
	virtual void UpdateCharacterStateBeforeMovement(float DeltaSeconds) override;
	virtual void UpdateCharacterStateAfterMovement(float DeltaSeconds) override;
	virtual void OnMovementUpdated(float DeltaSeconds, const FVector& OldLocation, const FVector& OldVelocity) override;
	virtual void OnMovementModeChanged(EMovementMode PreviousMovementMode, uint8 PreviousCustomMode) override;
	virtual void PhysCustom(float DeltaTime, int32 Iterations) override;
	virtual void ProcessLanded(const FHitResult& Hit, float RemainingTime, int32 Iterations) override;
	virtual void UpdateFromCompressedFlags(uint8 Flags) override;
	virtual FNetworkPredictionData_Client* GetPredictionData_Client() const override;
	virtual void MoveAutonomous(float ClientTimeStamp, float DeltaTime, uint8 CompressedFlags, const FVector& NewAccel) override;
	virtual void OnClientCorrectionReceived(FNetworkPredictionData_Client_Character& ClientData, float TimeStamp, FVector NewLocation, FVector NewVelocity,
		UPrimitiveComponent* NewBase, FName NewBaseBoneName, bool bHasBase, bool bBaseRelativePosition, uint8 ServerMovementMode, FVector ServerGravityDirection) override;
	virtual void ClientHandleMoveResponse(const FCharacterMoveResponseDataContainer& MoveResponse) override;
	virtual bool ClientUpdatePositionAfterServerUpdate() override;
	virtual void ServerMove_PerformMovement(const FCharacterNetworkMoveData& MoveData) override;
	virtual void ServerMoveHandleClientError(float ClientTimeStamp, float DeltaTime, const FVector& Accel, const FVector& RelativeClientLocation,
		UPrimitiveComponent* ClientMovementBase, FName ClientBaseBoneName, uint8 ClientMovementMode) override;
	virtual bool ServerCheckClientError(float ClientTimeStamp, float DeltaTime, const FVector& Accel, const FVector& ClientWorldLocation, const FVector& RelativeClientLocation,
		UPrimitiveComponent* ClientMovementBase, FName ClientBaseBoneName, uint8 ClientMovementMode) override;

protected:
	AVerseCharacter* GetVerseCharacter() const;

	void UpdateStance(float DeltaSeconds);
	void UpdateLean(float DeltaSeconds);
	/** Lean may be held now (stand or crouch, not sprinting, mantling or in a prone transition). */
	bool CanLeanNow() const;
	/** Server-authoritative prone turn cap: clamps the yaw change since the last move. */
	void ApplyProneTurnCap(float DeltaSeconds);
	/** Keeps the prone body out of walls: undoes the turn, then the move, that pushed it in. */
	void ConstrainProneBody();
	void SetActorYaw(float Yaw, bool bAlsoControl);
	bool TryStartSlide();
	void EndSlide(bool bToFalling);
	void PhysSlide(float DeltaTime, int32 Iterations);
	bool TryStartMantle();
	void UpdateMantle(float DeltaSeconds);
	void FinishMantle();
	void ApplyMantleSource(const FVector& From, const FVector& To, float Duration);
	void EmitNoise(const FGameplayTag& Noise, const FVector& Location);
	void UpdateFootsteps(float DeltaSeconds, const FVector& OldLocation);
	bool BodyShapeFits(EVerseBodyShape Shape, const FVector& FeetLocation) const;
	float HalfHeightFor(EVerseBodyShape Shape) const;
	float RadiusFor(EVerseBodyShape Shape) const;
	void ApplyTuningToMovement();

	UPROPERTY(EditAnywhere, Category = "Verse|Movement")
	TObjectPtr<UVerseMovementTuning> TuningAsset;

	FVerseMovementTuningValues TuningValues;

	// Wants (inputs; flags and move data).
	bool bWantsSprint = false;
	bool bWantsProne = false;
	bool bWantsMantle = false;
	int8 LeanTargetQuantized = 0;

	// Simulated state; saved and restored per move (FVerseSavedMove).
	EVerseStance Stance = EVerseStance::Stand;
	EVerseBodyShape BodyShape = EVerseBodyShape::Stand;
	int8 LeanQuantized = 0;
	/** Lean as simulated; LeanQuantized is what travels and what other modules read. */
	float LeanValue = 0.f;
	float ProneTransitionRemaining = 0.f;
	bool bProneExiting = false;
	float SlideElapsed = 0.f;
	float SlideCooldownRemaining = 0.f;
	bool bPrevWantsCrouch = false;
	bool bMantleLatched = false;
	float MantleElapsed = -1.f;
	float MantlePlanDuration = 0.f;
	float MantleRiseDuration = 0.f;
	FVector MantleRise = FVector::ZeroVector;
	FVector MantleTarget = FVector::ZeroVector;
	bool bMantleVault = false;
	uint16 MantleSourceId = 0;
	float StrideRemaining = 0.f;
	float LastMoveYaw = 0.f;
	bool bHasLastMoveYaw = false;
	/** Location at the start of the running move (prone body constraint). */
	FVector MoveStartLocation = FVector::ZeroVector;
	/** Client: the last correction was accepted (its move was still saved). */
	bool bCorrectionAccepted = false;

	// Server: the lean value the client sent with the current move (-128 = none).
	int16 PendingClientLean = -128;

	int32 MantleCount = 0;
	FVerseMovementNetStats NetStats;
	TUniquePtr<FCharacterNetworkMoveDataContainer> MoveDataContainer;
	TUniquePtr<FCharacterMoveResponseDataContainer> MoveResponseContainer;
	uint64 TickCycles = 0;
	int32 TickCountTotal = 0;
};

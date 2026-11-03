#pragma once

#include "CoreMinimal.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/CharacterMovementReplication.h"
#include "VerseCharacterMovement.h"

// Saved moves, move data and move responses of UVerseCharacterMovement (architecture.md 3.3):
// sprint, prone and mantle intent ride as compressed flags; lean (target and the client's result)
// rides in the custom move data. A server correction carries the server's simulated state
// (stance, body shape, slide, prone and mantle timers, yaw), so a corrected client replays its
// unacknowledged moves from the server's state; a replayed move restores only its inputs and facing.

namespace VerseMoveFlags
{
	inline constexpr uint8 Sprint = FSavedMove_Character::FLAG_Custom_0;
	inline constexpr uint8 Prone = FSavedMove_Character::FLAG_Custom_1;
	inline constexpr uint8 Mantle = FSavedMove_Character::FLAG_Custom_2;
}

/** The simulated state of one move start (see UVerseCharacterMovement). */
struct FVerseMoveState
{
	EVerseStance Stance = EVerseStance::Stand;
	EVerseBodyShape BodyShape = EVerseBodyShape::Stand;
	int8 LeanQuantized = 0;
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
	float StrideRemaining = 0.f;
	/** Actor yaw at the end of the move (prone turn cap and prone body constraint). */
	float LastMoveYaw = 0.f;
	bool bHasLastMoveYaw = false;
	/** Server corrections only: the prone turn cap clamped the client's yaw since the last correction. */
	bool bYawClamped = false;

	void Capture(const UVerseCharacterMovement& Movement);
	/** Writes the state back; the capsule keeps its centre (the location already belongs to the shape). */
	void Restore(UVerseCharacterMovement& Movement) const;
	/** Network form of the state (server corrections). */
	void Serialize(FArchive& Ar);
};

class FVerseSavedMove : public FSavedMove_Character
{
	using Super = FSavedMove_Character;

public:
	bool bSavedWantsSprint = false;
	bool bSavedWantsProne = false;
	bool bSavedWantsMantle = false;
	int8 SavedLeanTarget = 0;
	/** Lean after the move ran; the client sends it so the server can adopt it. */
	int8 SavedLeanResult = 0;
	FVerseMoveState StartState;
	/** Move kind at the start and at the end of the move (correction counters, WP01.10). */
	EVerseMoveKind StartKind = EVerseMoveKind::Walk;
	EVerseMoveKind EndKind = EVerseMoveKind::Walk;

	/** The kind a correction of this move is booked as: mantle, then prone, then slide win. */
	EVerseMoveKind GetCorrectionKind() const;

	virtual void Clear() override;
	virtual uint8 GetCompressedFlags() const override;
	virtual bool CanCombineWith(const FSavedMovePtr& NewMove, ACharacter* InCharacter, float MaxDelta) const override;
	virtual void SetMoveFor(ACharacter* C, float InDeltaTime, FVector const& NewAccel, FNetworkPredictionData_Client_Character& ClientData) override;
	virtual void SetInitialPosition(ACharacter* C) override;
	virtual void PrepMoveFor(ACharacter* C) override;
	virtual void CombineWith(const FSavedMove_Character* OldMove, ACharacter* InCharacter, APlayerController* PC, const FVector& OldStartLocation) override;
	virtual void PostUpdate(ACharacter* C, EPostUpdateMode PostUpdateMode) override;
	virtual bool IsImportantMove(const FSavedMovePtr& LastAckedMove) const override;
};

class FVerseNetworkPredictionData_Client : public FNetworkPredictionData_Client_Character
{
public:
	explicit FVerseNetworkPredictionData_Client(const UCharacterMovementComponent& Movement)
		: FNetworkPredictionData_Client_Character(Movement)
	{
	}

	virtual FSavedMovePtr AllocateNewMove() override { return FSavedMovePtr(new FVerseSavedMove()); }
};

struct FVerseCharacterNetworkMoveData : public FCharacterNetworkMoveData
{
	int8 LeanTarget = 0;
	int8 LeanResult = 0;

	virtual void ClientFillNetworkMoveData(const FSavedMove_Character& ClientMove, ENetworkMoveType MoveType) override;
	virtual bool Serialize(UCharacterMovementComponent& CharacterMovement, FArchive& Ar, UPackageMap* PackageMap, ENetworkMoveType MoveType) override;
};

struct FVerseCharacterNetworkMoveDataContainer : public FCharacterNetworkMoveDataContainer
{
	FVerseCharacterNetworkMoveDataContainer()
	{
		NewMoveData = &Storage[0];
		PendingMoveData = &Storage[1];
		OldMoveData = &Storage[2];
	}

	FVerseCharacterNetworkMoveData Storage[3];
};

/** Server move responses: a correction also carries the server's FVerseMoveState. */
struct FVerseMoveResponseDataContainer : public FCharacterMoveResponseDataContainer
{
	/** Sent with a correction (filled from PendingState). */
	FVerseMoveState State;
	/** Server: the state at the end of the move the pending correction is for. */
	FVerseMoveState PendingState;
	/** Server: a yaw clamp happened since the last correction was captured. */
	bool bYawClampedPending = false;

	virtual void ServerFillResponseData(const UCharacterMovementComponent& CharacterMovement, const FClientAdjustment& PendingAdjustment) override;
	virtual bool Serialize(UCharacterMovementComponent& CharacterMovement, FArchive& Ar, UPackageMap* PackageMap) override;
};

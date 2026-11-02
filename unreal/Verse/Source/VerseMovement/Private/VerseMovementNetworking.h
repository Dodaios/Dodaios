#pragma once

#include "CoreMinimal.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/CharacterMovementReplication.h"
#include "VerseCharacterMovement.h"

// Saved moves and move data of UVerseCharacterMovement (architecture.md 3.3): sprint, prone and
// mantle intent ride as compressed flags; lean (target and the client's result) rides in the
// custom move data. Everything the move simulates is saved at the start of each move and
// restored before a replay, so a corrected client re-simulates from the same state.

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

	void Capture(const UVerseCharacterMovement& Movement);
	void Restore(UVerseCharacterMovement& Movement) const;
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

	virtual void Clear() override;
	virtual uint8 GetCompressedFlags() const override;
	virtual bool CanCombineWith(const FSavedMovePtr& NewMove, ACharacter* InCharacter, float MaxDelta) const override;
	virtual void SetMoveFor(ACharacter* C, float InDeltaTime, FVector const& NewAccel, FNetworkPredictionData_Client_Character& ClientData) override;
	virtual void SetInitialPosition(ACharacter* C) override;
	virtual void PrepMoveFor(ACharacter* C) override;
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

#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "VerseInputFrameBuilder.h"

#include "VerseCharacter.generated.h"

class UBoxComponent;
class UCameraComponent;
class UInputMappingContext;
class UVerseCharacterMovement;
class UVersePersonInputConfig;

/** A scripted input source: returns false when it is done (QA drivers, the netcode soak). */
using FVerseInputScript = TFunction<bool(float ScriptTime, float DeltaSeconds, FVerseInputFrame& OutFrame)>;

/**
 * The Verse first-person character (work-packages.md WP01, architecture.md 3.3). Every move
 * comes from one FVerseInputFrame per tick, whoever produces it: the person's Enhanced Input
 * (through FVerseInputFrameBuilder), a bot or harness controller (SubmitInputFrame on the
 * server, bot.md B1, 8.3) or a QA script. ApplyInputFrame is the single consumer.
 *
 * Combat state is not here (decision C8): UVerseCombatStateComponent lives on the primary
 * module's pawn, which derives from this class.
 */
UCLASS()
class VERSEMOVEMENT_API AVerseCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	AVerseCharacter(const FObjectInitializer& ObjectInitializer);

	UVerseCharacterMovement* GetVerseMovement() const;
	UCameraComponent* GetFirstPersonCamera() const { return FirstPersonCamera; }
	UBoxComponent* GetProneBody() const { return ProneBody; }

	/** The one input consumer: look, move and every movement button of one tick. */
	void ApplyInputFrame(const FVerseInputFrame& Frame, float DeltaSeconds);

	/** Bot and harness controllers (server): the frame applied on this pawn's next tick. */
	void SubmitInputFrame(const FVerseInputFrame& Frame);

	/** Replaces the input source until the script returns false (nullptr clears it). */
	void SetInputScript(FVerseInputScript Script);
	bool HasInputScript() const { return bool(InputScript); }

	/** The person's input state; other packages bind their own actions into it (fire, reload). */
	FVerseInputFrameBuilder& GetPersonInput() { return PersonInput; }

	/** World camera position and rotation (eye, stance and lean applied). */
	FVector GetEyeLocation() const;
	FRotator GetEyeRotation() const;
	/** Aim: the control rotation, or the actor yaw plus the replicated view pitch on proxies. */
	FRotator GetAimRotation() const;

	/** Last frame ApplyInputFrame consumed. */
	const FVerseInputFrame& GetLastAppliedFrame() const { return LastAppliedFrame; }

	/** Re-poses camera and placeholder body after a stance or lean change (called by the movement). */
	void UpdateBodyPose(float DeltaSeconds);

	/** Placeholder pose until WP13's animation layer: lean rolls and prone lays the mesh down. */
	UPROPERTY(EditAnywhere, Category = "Verse|Movement")
	bool bPlaceholderPose = true;

	// Replicated to simulated proxies (push model; the owner predicts its own).
	UPROPERTY(ReplicatedUsing = OnRep_MovementState)
	uint8 ReplicatedStance = 0;
	UPROPERTY(Replicated)
	int8 ReplicatedLean = 0;
	UPROPERTY(Replicated)
	bool bReplicatedSprinting = false;
	UPROPERTY(Replicated)
	bool bReplicatedMantling = false;

	/** Server: publish the movement state for simulated proxies. */
	void SetReplicatedMovementState(EVerseStance Stance, int8 Lean, bool bSprinting, bool bMantling);

	// AActor / APawn
	virtual void Tick(float DeltaSeconds) override;
	virtual void BeginPlay() override;
	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;
	virtual void SetupPlayerInputComponent(UInputComponent* PlayerInputComponent) override;
	virtual void PawnClientRestart() override;
	virtual void GetActorEyesViewPoint(FVector& OutLocation, FRotator& OutRotation) const override;

protected:
	UFUNCTION()
	void OnRep_MovementState();

	void OnMoveAction(const struct FInputActionValue& Value);
	void OnMoveActionStopped(const struct FInputActionValue& Value);
	void OnLookAction(const struct FInputActionValue& Value);
	void OnLookRateAction(const struct FInputActionValue& Value);

	UPROPERTY(VisibleAnywhere, Category = "Verse|Movement")
	TObjectPtr<UCameraComponent> FirstPersonCamera;

	/** Horizontal body box behind the capsule while prone: clearance checks and leg hits. */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Movement")
	TObjectPtr<UBoxComponent> ProneBody;

	UPROPERTY(Transient)
	TObjectPtr<UVersePersonInputConfig> PersonInputConfig;

	FVerseInputFrameBuilder PersonInput;
	FVerseInputFrame SubmittedFrame;
	bool bHasSubmittedFrame = false;
	bool bSubmittedFrameFresh = false;
	FVerseInputFrame LastAppliedFrame;
	FVerseInputScript InputScript;
	float InputScriptTime = 0.f;
	float SmoothedEyeHeight = -1.f;
	float SmoothedProneAlpha = 0.f;
};

#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "VerseInputFrameBuilder.h"

#include "VerseCharacter.generated.h"

class UBoxComponent;
class UCameraComponent;
class UVerseCharacterMovement;

/** A scripted input source: returns false when it is done (QA drivers, the netcode soak). */
using FVerseInputScript = TFunction<bool(float ScriptTime, float DeltaSeconds, FVerseInputFrame& OutFrame)>;

/**
 * The Verse first-person character (work-packages.md WP01, architecture.md 3.3). Every move
 * comes from one FVerseInputFrame per tick, whoever produces it: the person's keys
 * (VersePersonInput through FVerseInputFrameBuilder), a bot or harness controller (SubmitInputFrame on the
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

	/**
	 * World camera position and rotation (eye, stance and lean applied). The eye is the
	 * skeleton's Camera bone (bot.md 3.1): the camera sits on it, the bot's eye reads the same.
	 */
	FVector GetEyeLocation() const;
	FRotator GetEyeRotation() const;
	/** Aim: the control rotation, or the actor yaw plus the replicated view pitch on proxies. */
	FRotator GetAimRotation() const;

	/** Last frame ApplyInputFrame consumed. */
	const FVerseInputFrame& GetLastAppliedFrame() const { return LastAppliedFrame; }

	/** Re-poses camera and placeholder body after a stance or lean change (called by the movement). */
	void UpdateBodyPose(float DeltaSeconds);

	/** The Camera bone's world location (the eye), or the camera's when the mesh has no such bone. */
	FVector GetCameraBoneLocation() const;
	static const FName CameraBoneName;

	/** Placeholder pose until WP13's animation layer: lean rolls and prone lays the mesh down. */
	UPROPERTY(EditAnywhere, Category = "Verse|Movement")
	bool bPlaceholderPose = true;

	// Replicated to simulated proxies (the owner predicts its own).
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

	/** Caches the Camera bone's reference-pose location in mesh space (placeholder pose). */
	void CacheCameraBone();

	UPROPERTY(VisibleAnywhere, Category = "Verse|Movement")
	TObjectPtr<UCameraComponent> FirstPersonCamera;

	/**
	 * Hit box over the lying legs (feet to hips) while prone, scored as Leg. Head and torso hits
	 * come from the mesh's physics bodies.
	 */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Movement")
	TObjectPtr<UBoxComponent> ProneBody;

	FVerseInputFrameBuilder PersonInput;
	FVerseInputFrame SubmittedFrame;
	bool bHasSubmittedFrame = false;
	bool bSubmittedFrameFresh = false;
	FVerseInputFrame LastAppliedFrame;
	FVerseInputScript InputScript;
	float InputScriptTime = 0.f;
	float SmoothedEyeHeight = -1.f;
	float SmoothedProneAlpha = 0.f;
	/** Camera bone in mesh space (reference pose); valid when bHasCameraBone. */
	FVector CameraBoneLocal = FVector::ZeroVector;
	bool bHasCameraBone = false;
};

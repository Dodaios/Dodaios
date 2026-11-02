#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "VerseInputFrameBuilder.generated.h"

class UInputAction;
class UInputMappingContext;

/**
 * Collects the person's input between ticks and emits one FVerseInputFrame per tick, the same
 * struct a bot produces (bot.md B1). Buttons are "held" bits; Pressed is derived from the
 * previous frame, so a person and a bot that hold the same buttons produce the same frames.
 * Crouch and prone are toggles for the person (pressing toggles the held bit).
 */
struct VERSEMOVEMENT_API FVerseInputFrameBuilder
{
	/** Move stick, -1..1, X forward, Y right. Kept until changed. */
	void SetMove(const FVector2f& Move) { Move2D = Move; }
	/** Look added this tick, degrees (pitch, yaw). Accumulates until the frame is taken. */
	void AddLook(const FVector2f& PitchYawDeg) { LookAccum += PitchYawDeg; }
	void SetButton(EVerseInputButton Button, bool bHeld);
	void ToggleButton(EVerseInputButton Button);
	/** Walk modifier: scales the move stick for quiet footsteps. */
	void SetWalkModifier(bool bHeld) { bWalk = bHeld; }
	bool IsHeld(EVerseInputButton Button) const { return (Buttons & uint32(Button)) != 0; }
	uint32 GetButtons() const { return Buttons; }

	/** The frame for this tick; clears the accumulated look and derives Pressed. */
	FVerseInputFrame Consume(uint32 ServerTimeMs);

	/** Forget everything (possession change). */
	void Reset();

	/** Move scale while the walk modifier is held. */
	float WalkScale = 0.5f;

private:
	FVector2f Move2D = FVector2f::ZeroVector;
	FVector2f LookAccum = FVector2f::ZeroVector;
	uint32 Buttons = 0;
	uint32 PrevButtons = 0;
	bool bWalk = false;
};

/** The person's Enhanced Input actions and default key mapping, built in code (no assets). */
UCLASS(Transient)
class VERSEMOVEMENT_API UVersePersonInputConfig : public UObject
{
	GENERATED_BODY()

public:
	/** Creates the actions and the default mapping (keyboard, mouse, gamepad). */
	void Build();

	UPROPERTY() TObjectPtr<UInputMappingContext> Mapping;
	UPROPERTY() TObjectPtr<UInputAction> Move;
	UPROPERTY() TObjectPtr<UInputAction> Look;
	UPROPERTY() TObjectPtr<UInputAction> LookRate;
	UPROPERTY() TObjectPtr<UInputAction> Jump;
	UPROPERTY() TObjectPtr<UInputAction> Crouch;
	UPROPERTY() TObjectPtr<UInputAction> Prone;
	UPROPERTY() TObjectPtr<UInputAction> Sprint;
	UPROPERTY() TObjectPtr<UInputAction> LeanLeft;
	UPROPERTY() TObjectPtr<UInputAction> LeanRight;
	UPROPERTY() TObjectPtr<UInputAction> Walk;

	/** Mouse degrees per count and stick degrees per second at full deflection. */
	float MouseDegPerCount = 0.07f;
	float StickDegPerSecond = 180.f;
};

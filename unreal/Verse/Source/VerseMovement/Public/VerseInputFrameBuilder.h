#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "InputCoreTypes.h"

class UInputComponent;

/** A key by its engine name ("W", "SpaceBar", "MouseX"): no link to InputCore's EKeys table needed. */
inline FKey VerseKey(const TCHAR* Name)
{
	return FKey(Name);
}

/** Movement keys of the person's default mapping (W, S, D, A). */
enum class EVerseMoveKey : uint8
{
	Forward,
	Back,
	Right,
	Left
};

/** How a key drives its button (the options' aim, crouch, sprint and lean modes). */
enum class EVerseKeyMode : uint8
{
	/** Held while the key is down. */
	Hold,
	/** Each press flips the button. */
	Toggle,
	/** Sprint only: on while moving forward; the key holds it as well. */
	Auto
};

/** The person's input options from the in-game settings (they survive Reset). */
struct VERSEMOVEMENT_API FVerseInputOptions
{
	/** Mouse look multiplier (controls.sensitivity). */
	float MouseScale = 1.f;
	/** Extra mouse multiplier while aiming down the sights (controls.ads_multiplier). */
	float AdsScale = 1.f;
	bool bInvertMouseY = false;
	EVerseKeyMode Aim = EVerseKeyMode::Hold;
	EVerseKeyMode Crouch = EVerseKeyMode::Toggle;
	EVerseKeyMode Sprint = EVerseKeyMode::Hold;
	EVerseKeyMode Lean = EVerseKeyMode::Hold;

	/** "hold", "toggle", "auto" as the settings catalogue spells them; anything else is Hold. */
	static EVerseKeyMode ParseMode(const FString& Text);
};

/**
 * Collects the person's input between ticks and emits one FVerseInputFrame per tick, the same
 * struct a bot produces (bot.md B1). Buttons are "held" bits; Pressed is derived from the
 * previous frame, so a person and a bot that hold the same buttons produce the same frames.
 * Crouch and prone are toggles for the person (pressing toggles the held bit).
 */
struct VERSEMOVEMENT_API FVerseInputFrameBuilder
{
	/** Move stick, -1..1, X forward, Y right. Kept until changed; keys and the gamepad stick win over it. */
	void SetMove(const FVector2f& Move) { Move2D = Move; }
	/** A movement key went down or up. */
	void SetMoveKey(EVerseMoveKey Key, bool bHeld);
	/** Gamepad left stick, per axis (0 forward, 1 right), after the input settings' dead zone. */
	void SetStickAxis(int32 Axis, float Value);
	/** Look added this tick, degrees (pitch, yaw). Accumulates until the frame is taken. */
	void AddLook(const FVector2f& PitchYawDeg) { LookAccum += PitchYawDeg; }
	/** Mouse look added this tick, degrees (pitch, yaw): the person's sensitivity, ADS multiplier and invert-Y apply. */
	void AddMouseLook(const FVector2f& PitchYawDeg);
	/** The options' look sensitivity (multiplier) and inverted mouse pitch. */
	void SetMouseLook(float Scale, bool bInvertY)
	{
		Options.MouseScale = FMath::Clamp(Scale, 0.05f, 10.f);
		Options.bInvertMouseY = bInvertY;
	}
	void SetOptions(const FVerseInputOptions& InOptions);
	const FVerseInputOptions& GetOptions() const { return Options; }
	/** A key for Button went down or up; its mode (hold, toggle, auto) decides what that does. */
	void KeyButton(EVerseInputButton Button, bool bDown);
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
	FVector2f Stick = FVector2f::ZeroVector;
	FVector2f LookAccum = FVector2f::ZeroVector;
	uint8 MoveKeys = 0;
	uint32 Buttons = 0;
	uint32 PrevButtons = 0;
	bool bWalk = false;
	FVerseInputOptions Options;
};

/**
 * The person's default key mapping (keyboard, mouse, gamepad), bound as plain key and axis
 * bindings on the pawn's input component. They work under the project's Enhanced Input player
 * input as well; moving them to Enhanced Input actions needs the module dependency (contract
 * change request for VerseMovement.Build.cs).
 */
namespace VersePersonInput
{
	/**
	 * Mouse degrees per count. The input settings' MouseX/MouseY axis config already scales a
	 * count by 0.07, so the bound axis value is in degrees.
	 */
	inline constexpr float MouseDegPerValue = 1.f;
	/** Gamepad right stick: degrees per second at full deflection. */
	inline constexpr float StickDegPerSecond = 180.f;

	/**
	 * Binds every movement key into Builder. Builder must outlive Input's bindings (the pawn owns
	 * both). DeltaSeconds gives the frame time the stick look rate scales with.
	 */
	VERSEMOVEMENT_API void BindDefaults(UInputComponent& Input, FVerseInputFrameBuilder& Builder, TFunction<float()> DeltaSeconds);
}

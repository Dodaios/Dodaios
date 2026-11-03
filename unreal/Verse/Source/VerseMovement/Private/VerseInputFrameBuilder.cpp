#include "VerseInputFrameBuilder.h"

#include "Components/InputComponent.h"

void FVerseInputFrameBuilder::SetButton(EVerseInputButton Button, bool bHeld)
{
	if (bHeld)
	{
		Buttons |= uint32(Button);
	}
	else
	{
		Buttons &= ~uint32(Button);
	}
}

void FVerseInputFrameBuilder::ToggleButton(EVerseInputButton Button)
{
	SetButton(Button, !IsHeld(Button));
	// Crouch and prone exclude each other: toggling one on releases the other.
	if (IsHeld(Button) && Button == EVerseInputButton::Crouch)
	{
		SetButton(EVerseInputButton::Prone, false);
	}
	else if (IsHeld(Button) && Button == EVerseInputButton::Prone)
	{
		SetButton(EVerseInputButton::Crouch, false);
	}
}

void FVerseInputFrameBuilder::SetMoveKey(EVerseMoveKey Key, bool bHeld)
{
	const uint8 Bit = uint8(1u << uint8(Key));
	MoveKeys = bHeld ? (MoveKeys | Bit) : (MoveKeys & ~Bit);
}

void FVerseInputFrameBuilder::SetStickAxis(int32 Axis, float Value)
{
	if (Axis == 0)
	{
		Stick.X = Value;
	}
	else
	{
		Stick.Y = Value;
	}
}

FVerseInputFrame FVerseInputFrameBuilder::Consume(uint32 ServerTimeMs)
{
	auto Held = [this](EVerseMoveKey Key) { return (MoveKeys & (1u << uint8(Key))) ? 1.f : 0.f; };
	FVector2f Move = Move2D;
	if (MoveKeys)
	{
		Move = FVector2f(Held(EVerseMoveKey::Forward) - Held(EVerseMoveKey::Back), Held(EVerseMoveKey::Right) - Held(EVerseMoveKey::Left));
	}
	else if (!Stick.IsNearlyZero())
	{
		Move = Stick;
	}
	FVerseInputFrame Frame;
	Frame.Move = Move * (bWalk ? WalkScale : 1.f);
	Frame.LookDeltaDeg = LookAccum;
	Frame.Buttons = Buttons;
	Frame.Pressed = Buttons & ~PrevButtons;
	Frame.ServerTimeMs = ServerTimeMs;
	PrevButtons = Buttons;
	LookAccum = FVector2f::ZeroVector;
	return Frame;
}

void FVerseInputFrameBuilder::Reset()
{
	*this = FVerseInputFrameBuilder();
}

namespace
{
	void BindKeyEvent(UInputComponent& Input, const FKey& Key, EInputEvent Event, TFunction<void()> Handler)
	{
		FInputKeyBinding Binding(FInputChord(Key, false, false, false, false), Event);
		Binding.bConsumeInput = false;
		Binding.KeyDelegate.GetDelegateForManualSet().BindLambda(MoveTemp(Handler));
		Input.KeyBindings.Emplace(MoveTemp(Binding));
	}

	void BindAxis(UInputComponent& Input, const FKey& Key, TFunction<void(float)> Handler)
	{
		FInputAxisKeyBinding Binding(Key);
		Binding.bConsumeInput = false;
		Binding.AxisDelegate.GetDelegateForManualSet().BindLambda(MoveTemp(Handler));
		Input.AxisKeyBindings.Emplace(MoveTemp(Binding));
	}
}

void VersePersonInput::BindDefaults(UInputComponent& Input, FVerseInputFrameBuilder& Builder, TFunction<float()> DeltaSeconds)
{
	FVerseInputFrameBuilder* B = &Builder;
	auto MoveKey = [&Input, B](const FKey& Key, EVerseMoveKey Move)
	{
		BindKeyEvent(Input, Key, IE_Pressed, [B, Move] { B->SetMoveKey(Move, true); });
		BindKeyEvent(Input, Key, IE_Released, [B, Move] { B->SetMoveKey(Move, false); });
	};
	auto Hold = [&Input, B](const FKey& Key, EVerseInputButton Button)
	{
		BindKeyEvent(Input, Key, IE_Pressed, [B, Button] { B->SetButton(Button, true); });
		BindKeyEvent(Input, Key, IE_Released, [B, Button] { B->SetButton(Button, false); });
	};
	auto Toggle = [&Input, B](const FKey& Key, EVerseInputButton Button)
	{
		BindKeyEvent(Input, Key, IE_Pressed, [B, Button] { B->ToggleButton(Button); });
	};

	MoveKey(VerseKey(TEXT("W")), EVerseMoveKey::Forward);
	MoveKey(VerseKey(TEXT("S")), EVerseMoveKey::Back);
	MoveKey(VerseKey(TEXT("D")), EVerseMoveKey::Right);
	MoveKey(VerseKey(TEXT("A")), EVerseMoveKey::Left);
	BindAxis(Input, VerseKey(TEXT("Gamepad_LeftY")), [B](float Value) { B->SetStickAxis(0, Value); });
	BindAxis(Input, VerseKey(TEXT("Gamepad_LeftX")), [B](float Value) { B->SetStickAxis(1, Value); });

	BindAxis(Input, VerseKey(TEXT("MouseX")), [B](float Value) { B->AddLook(FVector2f(0.f, Value * MouseDegPerValue)); });
	BindAxis(Input, VerseKey(TEXT("MouseY")), [B](float Value) { B->AddLook(FVector2f(Value * MouseDegPerValue, 0.f)); });
	BindAxis(Input, VerseKey(TEXT("Gamepad_RightX")), [B, DeltaSeconds](float Value) { B->AddLook(FVector2f(0.f, Value * StickDegPerSecond * DeltaSeconds())); });
	BindAxis(Input, VerseKey(TEXT("Gamepad_RightY")), [B, DeltaSeconds](float Value) { B->AddLook(FVector2f(Value * StickDegPerSecond * DeltaSeconds(), 0.f)); });

	Hold(VerseKey(TEXT("SpaceBar")), EVerseInputButton::Jump);
	Hold(VerseKey(TEXT("Gamepad_FaceButton_Bottom")), EVerseInputButton::Jump);
	Hold(VerseKey(TEXT("LeftShift")), EVerseInputButton::Sprint);
	Hold(VerseKey(TEXT("Gamepad_LeftThumbstick")), EVerseInputButton::Sprint);
	Hold(VerseKey(TEXT("Q")), EVerseInputButton::LeanLeft);
	Hold(VerseKey(TEXT("E")), EVerseInputButton::LeanRight);
	Toggle(VerseKey(TEXT("LeftControl")), EVerseInputButton::Crouch);
	Toggle(VerseKey(TEXT("C")), EVerseInputButton::Crouch);
	Toggle(VerseKey(TEXT("Gamepad_FaceButton_Right")), EVerseInputButton::Crouch);
	Toggle(VerseKey(TEXT("Z")), EVerseInputButton::Prone);
	BindKeyEvent(Input, VerseKey(TEXT("LeftAlt")), IE_Pressed, [B] { B->SetWalkModifier(true); });
	BindKeyEvent(Input, VerseKey(TEXT("LeftAlt")), IE_Released, [B] { B->SetWalkModifier(false); });
}

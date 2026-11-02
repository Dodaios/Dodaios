#include "VerseInputFrameBuilder.h"

#include "EnhancedActionKeyMapping.h"
#include "InputAction.h"
#include "InputCoreTypes.h"
#include "InputMappingContext.h"
#include "InputModifiers.h"

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

FVerseInputFrame FVerseInputFrameBuilder::Consume(uint32 ServerTimeMs)
{
	FVerseInputFrame Frame;
	Frame.Move = Move2D * (bWalk ? WalkScale : 1.f);
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
	UInputAction* MakeAction(UObject* Outer, const TCHAR* Name, EInputActionValueType Type)
	{
		UInputAction* Action = NewObject<UInputAction>(Outer, Name);
		Action->ValueType = Type;
		return Action;
	}

	template <typename TModifier>
	TModifier* AddModifier(UObject* Outer, FEnhancedActionKeyMapping& Mapping)
	{
		TModifier* Modifier = NewObject<TModifier>(Outer);
		Mapping.Modifiers.Add(Modifier);
		return Modifier;
	}
}

void UVersePersonInputConfig::Build()
{
	Mapping = NewObject<UInputMappingContext>(this, TEXT("IMC_VersePerson"));
	Move = MakeAction(this, TEXT("IA_Move"), EInputActionValueType::Axis2D);
	Look = MakeAction(this, TEXT("IA_Look"), EInputActionValueType::Axis2D);
	LookRate = MakeAction(this, TEXT("IA_LookRate"), EInputActionValueType::Axis2D);
	Jump = MakeAction(this, TEXT("IA_Jump"), EInputActionValueType::Boolean);
	Crouch = MakeAction(this, TEXT("IA_Crouch"), EInputActionValueType::Boolean);
	Prone = MakeAction(this, TEXT("IA_Prone"), EInputActionValueType::Boolean);
	Sprint = MakeAction(this, TEXT("IA_Sprint"), EInputActionValueType::Boolean);
	LeanLeft = MakeAction(this, TEXT("IA_LeanLeft"), EInputActionValueType::Boolean);
	LeanRight = MakeAction(this, TEXT("IA_LeanRight"), EInputActionValueType::Boolean);
	Walk = MakeAction(this, TEXT("IA_Walk"), EInputActionValueType::Boolean);

	// Move: W/S on X (forward), D/A on Y (right). A 1D key lands on X; swizzle puts it on Y.
	Mapping->MapKey(Move, EKeys::W);
	AddModifier<UInputModifierNegate>(this, Mapping->MapKey(Move, EKeys::S));
	AddModifier<UInputModifierSwizzleAxis>(this, Mapping->MapKey(Move, EKeys::D));
	{
		FEnhancedActionKeyMapping& Left = Mapping->MapKey(Move, EKeys::A);
		AddModifier<UInputModifierSwizzleAxis>(this, Left);
		AddModifier<UInputModifierNegate>(this, Left);
	}
	{
		// Gamepad stick: X = right, Y = up; the frame wants X forward, Y right.
		FEnhancedActionKeyMapping& Stick = Mapping->MapKey(Move, EKeys::Gamepad_Left2D);
		AddModifier<UInputModifierSwizzleAxis>(this, Stick);
		AddModifier<UInputModifierDeadZone>(this, Stick);
	}
	Mapping->MapKey(Look, EKeys::Mouse2D);
	AddModifier<UInputModifierDeadZone>(this, Mapping->MapKey(LookRate, EKeys::Gamepad_Right2D));

	Mapping->MapKey(Jump, EKeys::SpaceBar);
	Mapping->MapKey(Jump, EKeys::Gamepad_FaceButton_Bottom);
	Mapping->MapKey(Crouch, EKeys::LeftControl);
	Mapping->MapKey(Crouch, EKeys::C);
	Mapping->MapKey(Crouch, EKeys::Gamepad_FaceButton_Right);
	Mapping->MapKey(Prone, EKeys::Z);
	Mapping->MapKey(Sprint, EKeys::LeftShift);
	Mapping->MapKey(Sprint, EKeys::Gamepad_LeftThumbstick);
	Mapping->MapKey(LeanLeft, EKeys::Q);
	Mapping->MapKey(LeanRight, EKeys::E);
	Mapping->MapKey(Walk, EKeys::LeftAlt);
}

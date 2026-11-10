#include "Input/VerseDeckInput.h"

#include "InputAction.h"
#include "InputMappingContext.h"
#include "InputModifiers.h"

namespace Verse::DeckInput
{
	const TCHAR* ActionName(EAction Action)
	{
		switch (Action)
		{
		case EAction::Move: return TEXT("IA_Move");
		case EAction::Hurry: return TEXT("IA_Sprint");
		case EAction::CycleView: return TEXT("IA_DeckCycleView");
		case EAction::ViewOverview: return TEXT("IA_DeckViewOverview");
		case EAction::ViewThird: return TEXT("IA_DeckViewThird");
		case EAction::ViewFirst: return TEXT("IA_DeckViewFirst");
		case EAction::Use: return TEXT("IA_DeckUse");
		case EAction::MouseLook: return TEXT("IA_DeckMouseLook");
		case EAction::Power: return TEXT("IA_DeckPower");
		case EAction::Board: return TEXT("IA_DeckBoard");
		case EAction::ZoomIn: return TEXT("IA_DeckZoomIn");
		case EAction::ZoomOut: return TEXT("IA_DeckZoomOut");
		case EAction::Wheel: return TEXT("IA_DeckWheel");
		case EAction::Look: return TEXT("IA_DeckLook");
		case EAction::Click: return TEXT("IA_DeckClick");
		case EAction::Debug: return TEXT("IA_DeckDebug");
		default: return TEXT("IA_DeckUnknown");
		}
	}

	TConstArrayView<FBinding> DefaultBindings()
	{
		static const FBinding Bindings[] = {
			{ EAction::Move, EKeys::W, EKeyRole::MoveForward },
			{ EAction::Move, EKeys::Up, EKeyRole::MoveForward },
			{ EAction::Move, EKeys::S, EKeyRole::MoveBack },
			{ EAction::Move, EKeys::Down, EKeyRole::MoveBack },
			{ EAction::Move, EKeys::A, EKeyRole::MoveLeft },
			{ EAction::Move, EKeys::Left, EKeyRole::MoveLeft },
			{ EAction::Move, EKeys::D, EKeyRole::MoveRight },
			{ EAction::Move, EKeys::Right, EKeyRole::MoveRight },
			{ EAction::Hurry, EKeys::LeftShift },
			{ EAction::Hurry, EKeys::RightShift },
			{ EAction::CycleView, EKeys::V },
			{ EAction::ViewOverview, EKeys::One },
			{ EAction::ViewOverview, EKeys::NumPadOne },
			{ EAction::ViewThird, EKeys::Two },
			{ EAction::ViewThird, EKeys::NumPadTwo },
			{ EAction::ViewFirst, EKeys::Three },
			{ EAction::ViewFirst, EKeys::NumPadThree },
			{ EAction::Use, EKeys::E },
			{ EAction::MouseLook, EKeys::L },
			{ EAction::Power, EKeys::F },
			{ EAction::Board, EKeys::B },
			{ EAction::ZoomIn, EKeys::Equals },
			{ EAction::ZoomIn, EKeys::Add },
			{ EAction::ZoomOut, EKeys::Hyphen },
			{ EAction::ZoomOut, EKeys::Subtract },
			{ EAction::Wheel, EKeys::MouseWheelAxis },
			{ EAction::Look, EKeys::Mouse2D },
			{ EAction::Click, EKeys::LeftMouseButton },
			{ EAction::Debug, EKeys::F9 },
		};
		return Bindings;
	}

	FContext BuildContext(UObject* Outer)
	{
		FContext Out;
		Out.Context = NewObject<UInputMappingContext>(Outer, TEXT("IMC_VerseDeck"), RF_Transient);
		for (int32 Index = 0; Index < int32(EAction::Count); ++Index)
		{
			const EAction Action = EAction(Index);
			UInputAction* Input = NewObject<UInputAction>(Outer, ActionName(Action), RF_Transient);
			switch (Action)
			{
			case EAction::Move:
			case EAction::Look:
				Input->ValueType = EInputActionValueType::Axis2D;
				break;
			case EAction::Wheel:
				Input->ValueType = EInputActionValueType::Axis1D;
				break;
			default:
				Input->ValueType = EInputActionValueType::Boolean;
				break;
			}
			Out.Actions.Add(Input);
		}
		for (const FBinding& Binding : DefaultBindings())
		{
			FEnhancedActionKeyMapping& Mapping = Out.Context->MapKey(Out.Get(Binding.Action), Binding.Key);
			// The move keys build one stick: X right, Y forward.
			const bool bSwizzle = Binding.Role == EKeyRole::MoveForward || Binding.Role == EKeyRole::MoveBack;
			const bool bNegate = Binding.Role == EKeyRole::MoveBack || Binding.Role == EKeyRole::MoveLeft;
			if (bSwizzle)
			{
				UInputModifierSwizzleAxis* Swizzle = NewObject<UInputModifierSwizzleAxis>(Out.Context, NAME_None, RF_Transient);
				Swizzle->Order = EInputAxisSwizzle::YXZ;
				Mapping.Modifiers.Add(Swizzle);
			}
			if (bNegate)
			{
				Mapping.Modifiers.Add(NewObject<UInputModifierNegate>(Out.Context, NAME_None, RF_Transient));
			}
		}
		return Out;
	}

	bool IsChordModifier(const FKey& Key)
	{
		return Key == EKeys::LeftControl || Key == EKeys::RightControl || Key == EKeys::LeftAlt || Key == EKeys::RightAlt
			|| Key == EKeys::LeftCommand || Key == EKeys::RightCommand;
	}

	EEscape EscapeStep(bool bMouseLook, bool bCardOpen)
	{
		if (bMouseLook)
		{
			return EEscape::EndMouseLook;
		}
		return bCardOpen ? EEscape::CloseCard : EEscape::PassThrough;
	}

	bool TakesKeys(bool bWindowFocused, bool bTextFieldFocused, bool bChordHeld)
	{
		return bWindowFocused && !bTextFieldFocused && !bChordHeld;
	}
}

#include "Stream/VerseStreamInputPolicy.h"

namespace
{
	// Browser `KeyboardEvent.keyCode` values: W A S D, Left Up Right Down, Q E, V.
	constexpr uint8 AllowedKeys[] = { 87, 65, 83, 68, 37, 38, 39, 40, 81, 69, 86 };

	// Unreal keyboard key names (EKeys) the panel keeps; every other keyboard key is filtered.
	const TCHAR* const KeptKeyNames[] = { TEXT("W"), TEXT("A"), TEXT("S"), TEXT("D"), TEXT("Left"), TEXT("Up"), TEXT("Right"),
		TEXT("Down"), TEXT("Q"), TEXT("E"), TEXT("V") };

	// Every keyboard key name of EKeys (InputCoreTypes.h) the plugin could route.
	const TCHAR* const KeyboardKeyNames[] = { TEXT("BackSpace"), TEXT("Tab"), TEXT("Enter"), TEXT("Pause"), TEXT("CapsLock"),
		TEXT("Escape"), TEXT("SpaceBar"), TEXT("PageUp"), TEXT("PageDown"), TEXT("End"), TEXT("Home"), TEXT("Left"), TEXT("Up"),
		TEXT("Right"), TEXT("Down"), TEXT("Insert"), TEXT("Delete"), TEXT("Zero"), TEXT("One"), TEXT("Two"), TEXT("Three"),
		TEXT("Four"), TEXT("Five"), TEXT("Six"), TEXT("Seven"), TEXT("Eight"), TEXT("Nine"), TEXT("A"), TEXT("B"), TEXT("C"),
		TEXT("D"), TEXT("E"), TEXT("F"), TEXT("G"), TEXT("H"), TEXT("I"), TEXT("J"), TEXT("K"), TEXT("L"), TEXT("M"), TEXT("N"),
		TEXT("O"), TEXT("P"), TEXT("Q"), TEXT("R"), TEXT("S"), TEXT("T"), TEXT("U"), TEXT("V"), TEXT("W"), TEXT("X"), TEXT("Y"),
		TEXT("Z"), TEXT("NumPadZero"), TEXT("NumPadOne"), TEXT("NumPadTwo"), TEXT("NumPadThree"), TEXT("NumPadFour"),
		TEXT("NumPadFive"), TEXT("NumPadSix"), TEXT("NumPadSeven"), TEXT("NumPadEight"), TEXT("NumPadNine"), TEXT("Multiply"),
		TEXT("Add"), TEXT("Subtract"), TEXT("Decimal"), TEXT("Divide"), TEXT("F1"), TEXT("F2"), TEXT("F3"), TEXT("F4"), TEXT("F5"),
		TEXT("F6"), TEXT("F7"), TEXT("F8"), TEXT("F9"), TEXT("F10"), TEXT("F11"), TEXT("F12"), TEXT("NumLock"), TEXT("ScrollLock"),
		TEXT("LeftShift"), TEXT("RightShift"), TEXT("LeftControl"), TEXT("RightControl"), TEXT("LeftAlt"), TEXT("RightAlt"),
		TEXT("LeftCommand"), TEXT("RightCommand"), TEXT("Semicolon"), TEXT("Equals"), TEXT("Comma"), TEXT("Underscore"),
		TEXT("Hyphen"), TEXT("Period"), TEXT("Slash"), TEXT("Tilde"), TEXT("LeftBracket"), TEXT("Backslash"), TEXT("RightBracket"),
		TEXT("Apostrophe"), TEXT("Ampersand"), TEXT("Asterix"), TEXT("Caret"), TEXT("Colon"), TEXT("Dollar"), TEXT("Exclamation"),
		TEXT("LeftParantheses"), TEXT("RightParantheses"), TEXT("Quote"), TEXT("Section"), TEXT("A_AccentGrave"),
		TEXT("E_AccentGrave"), TEXT("E_AccentAigu"), TEXT("C_Cedille") };
}

int32 VerseStreamInput::PayloadSize(uint8 MessageId)
{
	switch (MessageId)
	{
	case IFrameRequest:
	case RequestInitialSettings:
	case MouseEnter:
	case MouseLeave:
		return 0;
	case KeyDown:
		return 2; // key code, repeat
	case KeyUp:
		return 1; // key code
	case MouseDown:
	case MouseUp:
	case MouseDouble:
		return 5; // button, x, y
	case MouseMove:
		return 8; // x, y, dx, dy
	case MouseWheel:
		return 6; // delta, x, y
	default:
		return -1;
	}
}

bool VerseStreamInput::IsAllowedKeyCode(uint8 KeyCode)
{
	for (const uint8 Allowed : AllowedKeys)
	{
		if (Allowed == KeyCode)
		{
			return true;
		}
	}
	return false;
}

TConstArrayView<uint8> VerseStreamInput::AllowedKeyCodes()
{
	return MakeArrayView(AllowedKeys, UE_ARRAY_COUNT(AllowedKeys));
}

bool VerseStreamInput::IsAllowedMessage(TConstArrayView<uint8> Message)
{
	if (Message.Num() == 0)
	{
		return false;
	}
	const uint8 Id = Message[0];
	const int32 Size = PayloadSize(Id);
	if (Size < 0 || Message.Num() != 1 + Size)
	{
		return false;
	}
	if (Id == KeyDown || Id == KeyUp)
	{
		return IsAllowedKeyCode(Message[1]);
	}
	if (Id == MouseDown || Id == MouseUp || Id == MouseDouble)
	{
		return Message[1] <= 2; // main, middle, secondary
	}
	return true;
}

FString VerseStreamInput::BuildKeyFilter()
{
	TArray<FString> Blocked;
	for (const TCHAR* Name : KeyboardKeyNames)
	{
		bool bKept = false;
		for (const TCHAR* Kept : KeptKeyNames)
		{
			bKept |= FCString::Strcmp(Name, Kept) == 0;
		}
		if (!bKept)
		{
			Blocked.Add(Name);
		}
	}
	Blocked.Sort();
	return FString::Join(Blocked, TEXT(","));
}

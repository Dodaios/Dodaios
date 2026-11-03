#include "VerseMovementTuning.h"

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "UObject/Package.h"
#include "UObject/StrongObjectPtr.h"
#include "UObject/UnrealType.h"
#include "VerseLog.h"

bool FVerseMovementTuningValues::Validate(FString& OutError) const
{
	for (TFieldIterator<FFloatProperty> It(StaticStruct()); It; ++It)
	{
		const float Value = It->GetPropertyValue_InContainer(this);
		if (!FMath::IsFinite(Value) || Value < 0.f || Value > 1000.f)
		{
			OutError = FString::Printf(TEXT("%s = %f is out of range"), *It->GetName(), Value);
			return false;
		}
	}
	auto Fail = [&OutError](const TCHAR* Why) { OutError = Why; return false; };
	if (!(CrouchSpeed < WalkSpeed && WalkSpeed < SprintSpeed && ProneSpeed < CrouchSpeed)) return Fail(TEXT("speeds must rise prone < crouch < walk < sprint"));
	if (!(SlideMinEntrySpeed <= SprintSpeed)) return Fail(TEXT("slide entry speed above sprint speed: the slide can never start"));
	if (!(SlideBoostSpeed > CrouchSpeed && SlideMaxDuration > 0.f)) return Fail(TEXT("slide boost must exceed crouch speed"));
	if (!(MantleMinHeight < MantleLowMaxHeight && MantleLowMaxHeight < MantleHighMaxHeight)) return Fail(TEXT("mantle heights must rise"));
	if (!(MantleRiseFraction > 0.1f && MantleRiseFraction < 0.9f)) return Fail(TEXT("mantle rise fraction outside 0.1..0.9"));
	if (!(CrouchHeight < StandHeight && ProneMinClearance < CrouchHeight)) return Fail(TEXT("body heights must rise prone < crouch < stand"));
	if (!(ProneRadius <= CapsuleRadius && CapsuleRadius * 2.f <= CrouchHeight)) return Fail(TEXT("capsule radius does not fit the crouch height"));
	if (!(StandEyeHeight < StandHeight && CrouchEyeHeight < CrouchHeight && ProneEyeHeight > 0.f)) return Fail(TEXT("eyes must sit inside the body"));
	if (!(LeanEnterTime > 0.f && ProneEnterTime > 0.f && ProneExitTime > 0.f)) return Fail(TEXT("transition times must be positive"));
	return true;
}

namespace
{
	/**
	 * Reader for the flat tuning file: one object of "name": number pairs plus string-valued
	 * "schema" and "_comment" keys. Own code, so VerseMovement needs no Json module link.
	 */
	struct FFlatJsonReader
	{
		const FString& Text;
		int32 Pos = 0;

		explicit FFlatJsonReader(const FString& InText) : Text(InText) {}

		void SkipSpace()
		{
			while (Pos < Text.Len() && FChar::IsWhitespace(Text[Pos]))
			{
				++Pos;
			}
		}
		bool Consume(TCHAR Char)
		{
			SkipSpace();
			if (Pos < Text.Len() && Text[Pos] == Char)
			{
				++Pos;
				return true;
			}
			return false;
		}
		bool Peek(TCHAR Char)
		{
			SkipSpace();
			return Pos < Text.Len() && Text[Pos] == Char;
		}
		bool ReadString(FString& Out)
		{
			Out.Reset();
			if (!Consume(TEXT('"')))
			{
				return false;
			}
			while (Pos < Text.Len() && Text[Pos] != TEXT('"'))
			{
				if (Text[Pos] == TEXT('\\') && Pos + 1 < Text.Len())
				{
					++Pos;
				}
				Out.AppendChar(Text[Pos++]);
			}
			return Consume(TEXT('"'));
		}
		/** A number, or false (and the value skipped) for anything else. */
		bool ReadNumber(double& Out, bool& bOutOk)
		{
			SkipSpace();
			bOutOk = false;
			if (Peek(TEXT('"')))
			{
				FString Ignored;
				return ReadString(Ignored);
			}
			const int32 Start = Pos;
			while (Pos < Text.Len() && (FChar::IsDigit(Text[Pos]) || FCString::Strchr(TEXT("+-.eE"), Text[Pos])))
			{
				++Pos;
			}
			if (Pos == Start)
			{
				while (Pos < Text.Len() && FChar::IsAlpha(Text[Pos]))
				{
					++Pos; // true, false, null
				}
				return Pos > Start;
			}
			const FString Number = Text.Mid(Start, Pos - Start);
			bOutOk = Number.IsNumeric() || FCString::Strchr(*Number, TEXT('e')) || FCString::Strchr(*Number, TEXT('E'));
			Out = FCString::Atod(*Number);
			return true;
		}
	};
}

bool UVerseMovementTuning::ParseJson(const FString& Json, FVerseMovementTuningValues& Out, FString& OutError)
{
	FFlatJsonReader Reader(Json);
	if (!Reader.Consume(TEXT('{')))
	{
		OutError = TEXT("not a JSON object");
		return false;
	}
	FVerseMovementTuningValues Parsed;
	while (!Reader.Consume(TEXT('}')))
	{
		FString Key;
		if (!Reader.ReadString(Key) || !Reader.Consume(TEXT(':')))
		{
			OutError = TEXT("not a JSON object");
			return false;
		}
		double Number = 0.0;
		bool bNumber = false;
		if (!Reader.ReadNumber(Number, bNumber))
		{
			OutError = FString::Printf(TEXT("field %s has no value"), *Key);
			return false;
		}
		if (!Reader.Consume(TEXT(',')) && !Reader.Peek(TEXT('}')))
		{
			OutError = TEXT("not a JSON object");
			return false;
		}
		if (Key == TEXT("schema") || Key.StartsWith(TEXT("_")))
		{
			continue;
		}
		FProperty* Property = FVerseMovementTuningValues::StaticStruct()->FindPropertyByName(FName(*Key));
		if (!Property || !Property->GetName().Equals(Key, ESearchCase::CaseSensitive))
		{
			OutError = FString::Printf(TEXT("unknown field %s"), *Key);
			return false;
		}
		if (!bNumber)
		{
			OutError = FString::Printf(TEXT("field %s is not a number"), *Key);
			return false;
		}
		CastFieldChecked<FFloatProperty>(Property)->SetPropertyValue_InContainer(&Parsed, float(Number));
	}
	if (!Parsed.Validate(OutError))
	{
		return false;
	}
	Out = Parsed;
	return true;
}

bool UVerseMovementTuning::LoadFromJsonFile(const FString& Path, FString& OutError)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		OutError = FString::Printf(TEXT("cannot read %s"), *Path);
		return false;
	}
	return ParseJson(Text, Values, OutError);
}

FString UVerseMovementTuning::ToJson(const FVerseMovementTuningValues& Values)
{
	FString Out = TEXT("{\n  \"schema\": \"verse.movement-tuning/1\"");
	for (TFieldIterator<FFloatProperty> It(FVerseMovementTuningValues::StaticStruct()); It; ++It)
	{
		Out += FString::Printf(TEXT(",\n  \"%s\": %s"), *It->GetName(), *FString::SanitizeFloat(It->GetPropertyValue_InContainer(&Values)));
	}
	Out += TEXT("\n}\n");
	return Out;
}

FString UVerseMovementTuning::DefaultJsonPath()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("movement"), TEXT("movement_tuning.json"));
}

const UVerseMovementTuning* UVerseMovementTuning::GetDefaultTuning()
{
	static TStrongObjectPtr<UVerseMovementTuning> Default;
	if (!Default.IsValid())
	{
		UVerseMovementTuning* Tuning = NewObject<UVerseMovementTuning>(GetTransientPackage(), TEXT("DA_MovementTuning_Default"));
		FString Error;
		if (FPaths::FileExists(DefaultJsonPath()) && !Tuning->LoadFromJsonFile(DefaultJsonPath(), Error))
		{
			UE_LOG(LogVerseMovement, Error, TEXT("movement tuning: %s; using the start values"), *Error);
		}
		Default.Reset(Tuning);
	}
	return Default.Get();
}

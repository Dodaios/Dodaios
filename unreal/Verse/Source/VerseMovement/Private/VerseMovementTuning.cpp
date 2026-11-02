#include "VerseMovementTuning.h"

#include "Dom/JsonObject.h"
#include "UObject/StrongObjectPtr.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Package.h"
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

bool UVerseMovementTuning::ParseJson(const FString& Json, FVerseMovementTuningValues& Out, FString& OutError)
{
	TSharedPtr<FJsonObject> Object;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	if (!FJsonSerializer::Deserialize(Reader, Object) || !Object.IsValid())
	{
		OutError = TEXT("not a JSON object");
		return false;
	}
	FVerseMovementTuningValues Parsed;
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Field : Object->Values)
	{
		if (Field.Key == TEXT("schema") || Field.Key.StartsWith(TEXT("_")))
		{
			continue;
		}
		FProperty* Property = FVerseMovementTuningValues::StaticStruct()->FindPropertyByName(FName(*Field.Key));
		if (!Property || !Property->GetName().Equals(Field.Key, ESearchCase::CaseSensitive))
		{
			OutError = FString::Printf(TEXT("unknown field %s"), *Field.Key);
			return false;
		}
		double Number = 0.0;
		if (!Field.Value.IsValid() || !Field.Value->TryGetNumber(Number))
		{
			OutError = FString::Printf(TEXT("field %s is not a number"), *Field.Key);
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

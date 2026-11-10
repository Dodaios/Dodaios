#include "Crew/VerseCrewSubsystem.h"
#include "Dom/JsonObject.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Qa/VerseQaRegistry.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

// Verse.QA.SetDuty <member id> <working|waiting|idle|paused|error|none> (parity C-24, Q-02).
// Registered while at least one crew subsystem lives; it applies to every live one.
namespace VerseCrewQa
{
	static const TCHAR* SetDutyCommand = TEXT("Verse.QA.SetDuty");

	static TArray<TWeakObjectPtr<UVerseCrewSubsystem>>& Live()
	{
		static TArray<TWeakObjectPtr<UVerseCrewSubsystem>> Subsystems;
		return Subsystems;
	}

	static FString ToJson(const TSharedRef<FJsonObject>& Object)
	{
		FString Out;
		const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Object, Writer);
		return Out;
	}

	static FString Error(const FString& Message)
	{
		const TSharedRef<FJsonObject> Object = MakeShared<FJsonObject>();
		Object->SetStringField(TEXT("error"), Message);
		return ToJson(Object);
	}

	FString SetDuty(const TArray<FString>& Args)
	{
		if (Args.Num() != 2)
		{
			return Error(TEXT("usage: Verse.QA.SetDuty <member id> <working|waiting|idle|paused|error|none>"));
		}
		TOptional<EVerseCrewDuty> Duty;
		if (Args[1] != TEXT("none"))
		{
			EVerseCrewDuty Parsed;
			if (!VerseCrew::TryParseDuty(Args[1], Parsed))
			{
				return Error(FString::Printf(TEXT("unknown duty '%s'"), *Args[1]));
			}
			Duty = Parsed;
		}
		int32 Applied = 0;
		for (const TWeakObjectPtr<UVerseCrewSubsystem>& Weak : Live())
		{
			if (UVerseCrewSubsystem* Subsystem = Weak.Get())
			{
				Subsystem->SetDutyOverride(Args[0], Duty);
				++Applied;
			}
		}
		const TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("id"), Args[0]);
		Result->SetStringField(TEXT("duty"), Duty.IsSet() ? VerseCrew::DutyName(Duty.GetValue()) : TEXT("none"));
		Result->SetNumberField(TEXT("worlds"), Applied);
		return ToJson(Result);
	}

	void AddSubsystem(UVerseCrewSubsystem* Subsystem)
	{
		Live().RemoveAll([](const TWeakObjectPtr<UVerseCrewSubsystem>& Weak) { return !Weak.IsValid(); });
		Live().AddUnique(Subsystem);
		if (UVerseQaRegistry* Registry = UVerseQaRegistry::Get())
		{
			if (!Registry->IsRegistered(SetDutyCommand))
			{
				Registry->Register(SetDutyCommand, TEXT("Force a crew member's duty status; 'none' releases it."), &SetDuty);
			}
		}
	}

	void RemoveSubsystem(UVerseCrewSubsystem* Subsystem)
	{
		Live().RemoveAll([Subsystem](const TWeakObjectPtr<UVerseCrewSubsystem>& Weak) { return !Weak.IsValid() || Weak.Get() == Subsystem; });
		if (Live().Num() == 0)
		{
			if (UVerseQaRegistry* Registry = UVerseQaRegistry::Get())
			{
				Registry->Unregister(SetDutyCommand);
			}
		}
	}
}

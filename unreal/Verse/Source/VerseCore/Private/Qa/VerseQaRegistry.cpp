#include "Qa/VerseQaRegistry.h"

#include "Engine/Engine.h"
#include "HAL/IConsoleManager.h"
#include "Misc/OutputDevice.h"
#include "Qa/VerseQaEngineCommands.h"
#include "VerseLog.h"

namespace
{
	FString ErrorJson(const FString& Message)
	{
		FString Escaped;
		for (const TCHAR Ch : Message)
		{
			if (Ch == TEXT('"') || Ch == TEXT('\\'))
			{
				Escaped.AppendChar(TEXT('\\'));
				Escaped.AppendChar(Ch);
			}
			else if (Ch >= 0x20)
			{
				Escaped.AppendChar(Ch);
			}
		}
		return FString::Printf(TEXT("{\"error\": \"%s\"}"), *Escaped);
	}
}

TConstArrayView<FString> UVerseQaRegistry::KnownCommands()
{
	static const TArray<FString> Names = {
		TEXT("Verse.QA.Stats"),
		TEXT("Verse.QA.Dump"),
		TEXT("Verse.QA.SetDuty"),
		TEXT("Verse.QA.Duel.Start"),
		TEXT("Verse.QA.Duel.Leave"),
		TEXT("Verse.QA.Duel.Place"),
		TEXT("Verse.QA.Duel.Look"),
		TEXT("Verse.QA.Duel.Hold"),
		TEXT("Verse.QA.Duel.Press"),
		TEXT("Verse.QA.Duel.State"),
		TEXT("Verse.QA.Duel.Bodies"),
		TEXT("Verse.QA.View.Set"),
		TEXT("Verse.QA.View.Look"),
		TEXT("Verse.QA.View.Zoom"),
		TEXT("Verse.QA.View.State"),
		TEXT("Verse.QA.Tune"),
		TEXT("Verse.QA.Materials"),
		TEXT("Verse.QA.Space.Set"),
		TEXT("Verse.QA.Space.State"),
		TEXT("Verse.QA.Viewmodel"),
	};
	return Names;
}

UVerseQaRegistry* UVerseQaRegistry::Get()
{
	return GEngine ? GEngine->GetEngineSubsystem<UVerseQaRegistry>() : nullptr;
}

bool UVerseQaRegistry::Register(const FString& Command, const FString& Help, FVerseQaHandler Handler)
{
	if (!Command.StartsWith(CommandPrefix(), ESearchCase::CaseSensitive) || Command.Len() <= FCString::Strlen(CommandPrefix()))
	{
		UE_LOG(LogVerseQa, Error, TEXT("QA command '%s' refused: names start with %s"), *Command, CommandPrefix());
		return false;
	}
	if (!Handler)
	{
		UE_LOG(LogVerseQa, Error, TEXT("QA command '%s' refused: no handler"), *Command);
		return false;
	}
	if (Commands.Contains(Command))
	{
		UE_LOG(LogVerseQa, Error, TEXT("QA command '%s' refused: already registered"), *Command);
		return false;
	}

	FEntry& Entry = Commands.Add(Command);
	Entry.Help = Help;
	Entry.Handler = MoveTemp(Handler);

#if !UE_BUILD_SHIPPING
	const FString Name = Command;
	Entry.ConsoleObject = IConsoleManager::Get().RegisterConsoleCommand(
		*Command, *Help,
		FConsoleCommandWithWorldArgsAndOutputDeviceDelegate::CreateWeakLambda(this,
			[this, Name](const TArray<FString>& Args, UWorld*, FOutputDevice& Ar)
			{
				FString Result;
				Execute(Name, Args, Result);
				Ar.Log(Result);
			}),
		ECVF_Default);
#endif
	return true;
}

bool UVerseQaRegistry::Unregister(const FString& Command)
{
	FEntry Entry;
	if (!Commands.RemoveAndCopyValue(Command, Entry))
	{
		return false;
	}
	if (Entry.ConsoleObject)
	{
		IConsoleManager::Get().UnregisterConsoleObject(Entry.ConsoleObject, false);
	}
	return true;
}

bool UVerseQaRegistry::IsRegistered(const FString& Command) const
{
	return Commands.Contains(Command);
}

TArray<FString> UVerseQaRegistry::GetRegisteredCommands() const
{
	TArray<FString> Names;
	Commands.GetKeys(Names);
	Names.Sort();
	return Names;
}

bool UVerseQaRegistry::Execute(const FString& Command, const TArray<FString>& Args, FString& OutResult) const
{
	const FEntry* Entry = Commands.Find(Command);
	if (!Entry)
	{
		OutResult = ErrorJson(FString::Printf(TEXT("unknown command %s"), *Command));
		return false;
	}
	OutResult = Entry->Handler(Args);
	return true;
}

bool UVerseQaRegistry::ExecuteLine(const FString& Line, FString& OutResult) const
{
	TArray<FString> Tokens;
	FString Current;
	bool bInQuotes = false;
	bool bHasToken = false;
	for (const TCHAR Ch : Line)
	{
		if (Ch == TEXT('"'))
		{
			bInQuotes = !bInQuotes;
			bHasToken = true;
		}
		else if (!bInQuotes && FChar::IsWhitespace(Ch))
		{
			if (bHasToken)
			{
				Tokens.Add(MoveTemp(Current));
				Current.Reset();
				bHasToken = false;
			}
		}
		else
		{
			Current.AppendChar(Ch);
			bHasToken = true;
		}
	}
	if (bHasToken)
	{
		Tokens.Add(MoveTemp(Current));
	}
	if (Tokens.IsEmpty())
	{
		OutResult = ErrorJson(TEXT("empty command"));
		return false;
	}
	const FString Command = Tokens[0];
	Tokens.RemoveAt(0);
	return Execute(Command, Tokens, OutResult);
}

void UVerseQaRegistry::RegisterDumpSection(const FString& Name, TFunction<FString()> Producer)
{
	if (Name.IsEmpty() || !Producer)
	{
		return;
	}
	DumpSections.Add(Name, MoveTemp(Producer));
}

void UVerseQaRegistry::UnregisterDumpSection(const FString& Name)
{
	DumpSections.Remove(Name);
}

void UVerseQaRegistry::SetViewmodelLayout(const FVerseViewmodelLayout& Layout)
{
	ViewmodelLayout = Layout;
	OnViewmodelLayoutChanged.Broadcast(ViewmodelLayout);
}

void UVerseQaRegistry::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	VerseQaEngine::RegisterCommands(*this);
}

void UVerseQaRegistry::Deinitialize()
{
	TArray<FString> Names;
	Commands.GetKeys(Names);
	for (const FString& Name : Names)
	{
		Unregister(Name);
	}
	Super::Deinitialize();
}

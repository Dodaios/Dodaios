#pragma once

#include "CoreMinimal.h"
#include "Subsystems/EngineSubsystem.h"

#include "VerseQaRegistry.generated.h"

class IConsoleObject;

/**
 * A Verse.QA.* command handler: arguments after the command name in, a JSON result string out.
 * Handlers return a JSON object; on bad input they return {"error": "..."}.
 */
using FVerseQaHandler = TFunction<FString(const TArray<FString>& Args)>;

/**
 * The registry of the Verse.QA.* commands of parity.md section 19 (work-packages.md 0.2). Each
 * package registers the commands of its own area from its own Private/QA/ folder; WP17 reaches
 * them in Shipping through the qa.exec bridge frame (bridge-protocol.md 14) via Execute.
 * In non-Shipping builds every registered command is also a console command of the same name.
 */
UCLASS()
class VERSECORE_API UVerseQaRegistry : public UEngineSubsystem
{
	GENERATED_BODY()

public:
	/** Every command name parity.md 19 freezes, in table order. */
	static TConstArrayView<FString> KnownCommands();

	/** Required prefix of every command name. */
	static const TCHAR* CommandPrefix() { return TEXT("Verse.QA."); }

	/** The registry of the running engine, or nullptr before the engine exists. */
	static UVerseQaRegistry* Get();

	/**
	 * Registers a handler. Fails (false, logged) when the name lacks the Verse.QA. prefix, is
	 * already registered, or the handler is unset.
	 */
	bool Register(const FString& Command, const FString& Help, FVerseQaHandler Handler);

	/** Removes a command; false when it was not registered. */
	bool Unregister(const FString& Command);

	bool IsRegistered(const FString& Command) const;

	/** Registered names, sorted. */
	TArray<FString> GetRegisteredCommands() const;

	/** Runs a command; false (OutResult = an error JSON) when it is not registered. */
	bool Execute(const FString& Command, const TArray<FString>& Args, FString& OutResult) const;

	/** Runs "Verse.QA.Name arg1 arg2" (whitespace separated, quotes keep spaces). */
	bool ExecuteLine(const FString& Line, FString& OutResult) const;

	virtual void Deinitialize() override;

private:
	struct FEntry
	{
		FString Help;
		FVerseQaHandler Handler;
		IConsoleObject* ConsoleObject = nullptr;
	};

	TMap<FString, FEntry> Commands;
};

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/EngineSubsystem.h"

#include "VerseQaRegistry.generated.h"

class IConsoleObject;

/**
 * Layout of the first-person viewmodel as Verse.QA.Viewmodel retunes it (parity Q-08). The viewmodel
 * component (WP14) reads it and listens to OnViewmodelLayoutChanged; with no consumer it is only state.
 * A zero FovDeg means "the weapon's own value".
 */
struct VERSECORE_API FVerseViewmodelLayout
{
	FVector OffsetCm = FVector::ZeroVector;
	float Scale = 1.0f;
	float FovDeg = 0.0f;
};

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseViewmodelLayoutChanged, const FVerseViewmodelLayout&);

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

	/**
	 * A section of Verse.QA.Dump (parity Q-02): the producer returns one JSON value (object or array text).
	 * The crew package registers "crew" (statuses of every member). Re-registering a name replaces it.
	 */
	void RegisterDumpSection(const FString& Name, TFunction<FString()> Producer);
	void UnregisterDumpSection(const FString& Name);
	const TMap<FString, TFunction<FString()>>& GetDumpSectionsForQa() const { return DumpSections; }

	/** The viewmodel layout of Verse.QA.Viewmodel (non-shipping command; state exists in every build). */
	const FVerseViewmodelLayout& GetViewmodelLayout() const { return ViewmodelLayout; }
	void SetViewmodelLayout(const FVerseViewmodelLayout& Layout);
	FOnVerseViewmodelLayoutChanged OnViewmodelLayoutChanged;

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

private:
	struct FEntry
	{
		FString Help;
		FVerseQaHandler Handler;
		IConsoleObject* ConsoleObject = nullptr;
	};

	TMap<FString, FEntry> Commands;
	TMap<FString, TFunction<FString()>> DumpSections;
	FVerseViewmodelLayout ViewmodelLayout;
};

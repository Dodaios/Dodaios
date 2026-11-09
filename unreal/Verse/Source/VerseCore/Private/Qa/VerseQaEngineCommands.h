#pragma once

#include "CoreMinimal.h"

class UVerseQaRegistry;
class UWorld;

/**
 * The Verse.QA commands that need nothing but the engine (parity section 19): Dump (Q-02), Tune and
 * Materials (Q-06), Viewmodel (Q-08). Registered by the registry when it initializes; the areas that own
 * state of their own (View, Space, Duel, SetDuty) register theirs from their own modules.
 */
namespace VerseQaEngine
{
	void RegisterCommands(UVerseQaRegistry& Registry);

	/** The world the commands act on: the first game or PIE world, nullptr when there is none. */
	UWorld* FindGameWorld();

	/** Tests only: a world that FindGameWorld returns instead of searching the engine's contexts. */
	void SetWorldForTests(UWorld* World);

	/** Parses "key=value" arguments; keys are lower-cased. A bare word becomes a key with an empty value. */
	TMap<FString, FString> ParseKeyValues(const TArray<FString>& Args);

	/** {"error": "..."} with the message escaped. */
	FString ErrorJson(const FString& Message);
}

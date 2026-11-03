#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

// duel.result codec (bridge-protocol.md 10): FVerseSetSummary (combat-state.md 11.1) field for
// field onto the payload, plus the two fields the summary does not carry (mode and end reason)
// and the build stamp. Core types only; this module never includes VerseCombat.

namespace VerseDuel
{
	/** Why a set ended, as the wire spells it (bridge-protocol.md 10, `end_reason`). */
	enum class EEndReason : uint8
	{
		SetComplete,
		PlayerLeft,
		VerseQuit,
		CrashRecovered,
		AppQuit,
	};

	/** The only mode that exists in verse.bridge/1; every set the hub raises is one of it. */
	inline const TCHAR* const DeathmatchMode = TEXT("deathmatch_1v1");

	/** The tier an adaptive bot starts on (bot.md 9.2, StartSkill 0.5 = hard). */
	inline const TCHAR* const AdaptiveStartTier = TEXT("hard");

	const TCHAR* EndReasonName(EEndReason Reason);
	bool ParseEndReason(const FString& Name, EEndReason& Out);
	const TCHAR* OutcomeName(EVerseSetOutcome Outcome);

	/** The build stamp a result carries (`build`); both fields are never empty. */
	struct FBuildStamp
	{
		FString Version;
		FString Changelist;

		/** Project version and engine build version of the running build. */
		static FBuildStamp Current();
	};

	/** A weapon id as the wire allows it: lower case, `[a-z0-9_]`, other characters become `_`. */
	FString WireId(FName Id);

	/**
	 * The `data` object of one duel.result. A won or lost set ends with `set_complete`; an
	 * unfinished one with the reason the caller names (player_left by default).
	 */
	TSharedRef<FJsonObject> EncodeResult(const FVerseSetSummary& Summary, EEndReason EndReason, const FBuildStamp& Build);

	/** The reason a set ends with when nothing else is known: complete for finished, left otherwise. */
	EEndReason DefaultEndReason(const FVerseSetSummary& Summary);

	FString ToJsonString(const TSharedRef<FJsonObject>& Object);
	TSharedPtr<FJsonObject> FromJsonString(const FString& Text);
}

#pragma once

#include "CoreMinimal.h"

#include "VerseStationTypes.generated.h"

/**
 * Station kinds (parity S-01): the nine of today's deck manifests plus the hangar armoury. The
 * order is frozen once placements reference it; the wire name is the manifest's `kind`.
 */
UENUM(BlueprintType)
enum class EVerseStationKind : uint8
{
	AgentsList,
	Team,
	ServiceRecord,
	MessCall,
	Games,
	Quartermaster,
	CodingLauncher,
	CreateAgent,
	Lift,
	Armoury
};

namespace VerseStations
{
	constexpr int32 KindCount = 10;

	/** Manifest and event name: "agents_list", ... "armoury". */
	VERSEDECKS_API FName KindName(EVerseStationKind Kind);
	VERSEDECKS_API bool KindFromName(FName Name, EVerseStationKind& OutKind);

	/** Locale keys of the prompt (`verse.station.<kind>.name` / `.action`). */
	VERSEDECKS_API FString NameKey(EVerseStationKind Kind);
	VERSEDECKS_API FString ActionKey(EVerseStationKind Kind);
	/** English text for a key the app did not send (the en locale of today). */
	VERSEDECKS_API FString FallbackName(EVerseStationKind Kind);
	VERSEDECKS_API FString FallbackAction(EVerseStationKind Kind);

	/** Reach of the use key: 2.2 m (life/control.ts STATION_REACH_M), in centimetres. */
	constexpr float ReachCm = 220.f;
	/** Prompt refresh: 5 times a second (parity S-13). */
	constexpr float PromptIntervalS = 0.2f;
}

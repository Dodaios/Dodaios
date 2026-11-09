#pragma once

#include "Crew/VerseCrewDeck.h"
#include "Crew/VerseCrewTypes.h"
#include "CoreMinimal.h"

/** Where one member should be and what it does there (life/planner.ts Intent). */
struct VERSECREW_API FVerseCrewIntent
{
	FName Deck;
	EVerseCrewVenue Venue = EVerseCrewVenue::Mess;
	EVerseCrewActivity Activity = EVerseCrewActivity::StandRest;
	/** Turn toward the commander rather than the socket's facing. */
	bool bFaceCommander = false;
};

struct VERSECREW_API FVerseCrewPlacement
{
	FVerseCrewIntent Intent;
	/** Key of the socket ("seat:pit_p_1"). */
	FString SocketKey;
	int32 SocketIndex = INDEX_NONE;
};

struct VERSECREW_API FVerseCrewDeckPlan
{
	TMap<FString, FVerseCrewPlacement> Placements;
	/** Home console (seat id) of every member who has one on this deck. */
	TMap<FString, FString> Homes;
};

struct VERSECREW_API FVerseCrewPlanInput
{
	const FVerseCrewDeck* Deck = nullptr;
	TArrayView<const FVerseCrewMember> Crew;
	const TMap<FString, EVerseCrewRoundPart>* Rounds = nullptr;
	int64 NowMs = 0;
	/** Last plan's socket keys by member. */
	const TMap<FString, FString>* Previous = nullptr;
	/** Last plan's home consoles by member (seat ids). */
	const TMap<FString, FString>* Homes = nullptr;
	bool bMessCall = false;
	/** Socket keys that may not be used now (inside the arena while it is on). */
	const TSet<FString>* Blocked = nullptr;
};

/**
 * Port of life/planner.ts: pure and deterministic. Golden-tested against the TypeScript
 * function (Content/Verse/Test/WP15/Golden/planner_golden.json).
 */
namespace VerseCrewPlanner
{
	/** Length of one off-duty slot (IDLE_SLOT_MS). */
	inline constexpr int64 IdleSlotMs = 6 * 60 * 1000;

	struct FIdleVenue
	{
		EVerseCrewVenue Venue;
		FName Deck;
		EVerseCrewActivity Activity;
	};

	VERSECREW_API FIdleVenue IdleVenueOf(const FString& MemberId, int64 NowMs);
	VERSECREW_API FVerseCrewIntent IntentOf(const FVerseCrewMember& Member, EVerseCrewRoundPart Part, int64 NowMs, bool bMessCall = false);

	/** Seats with a screen of the same id that belong to no station (consoles, terminals). */
	VERSECREW_API TArray<int32> ConsoleSeats(const FVerseCrewDeck& Deck);
	VERSECREW_API TArray<int32> TeamTableSeats(const FVerseCrewDeck& Deck);
	VERSECREW_API TArray<int32> VenueSockets(const FVerseCrewDeck& Deck, EVerseCrewVenue Venue);

	VERSECREW_API TMap<FString, FString> HomeSeats(const FVerseCrewDeck& Deck, TArrayView<const FVerseCrewMember> Crew, EVerseCrewRole Role,
		const TMap<FString, FString>& Previous);

	VERSECREW_API FVerseCrewDeckPlan PlaceOnDeck(const FVerseCrewPlanInput& Input);

	/** The deck a role has its consoles on (bridge for officers, engineering for technicians). */
	VERSECREW_API FName HomeDeck(EVerseCrewRole Role);
}

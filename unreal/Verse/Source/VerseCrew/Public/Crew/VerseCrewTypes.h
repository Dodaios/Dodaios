#pragma once

#include "CoreMinimal.h"

#include "VerseCrewTypes.generated.h"

// Crew life value types (WP15). Officers are society agents, technicians are coding panes;
// both come from the roster topic of contracts/bridge-protocol.md 4.

/** Duty status values of bridge-protocol.md 4.2 (DUTY_STATUSES). The backend computes them. */
UENUM(BlueprintType)
enum class EVerseCrewDuty : uint8
{
	Working,
	Waiting,
	Idle,
	Paused,
	Error,
};

UENUM(BlueprintType)
enum class EVerseCrewRole : uint8
{
	/** A society agent: bridge consoles. */
	Officer,
	/** A coding pane: engineering terminals. */
	Technician,
};

/** Where a crew member goes (port of life/planner.ts Venue). */
UENUM(BlueprintType)
enum class EVerseCrewVenue : uint8
{
	Console,
	Terminal,
	Briefing,
	Mess,
	Corridor,
	Viewport,
	Bunk,
	Workshop,
};

/** What a crew member does at its socket (port of life/planner.ts Activity). The anim layer reads it. */
UENUM(BlueprintType)
enum class EVerseCrewActivity : uint8
{
	SitType,
	StandWait,
	StandAlert,
	SitRest,
	StandRest,
	Sleep,
	Talk,
	Listen,
	StandGuard,
	/** Walking to a goal (not a planner activity; the pawn's own state). */
	Walk,
};

/** How the status beacon over a head behaves (parity E-10). */
UENUM(BlueprintType)
enum class EVerseCrewBeacon : uint8
{
	None,
	Steady,
	SlowPulse,
};

/** A team round part (planner.ts RoundPart). */
enum class EVerseCrewRoundPart : uint8
{
	None,
	Speaker,
	Listener,
};

/** One member as crew life sees it (port of life/crew.ts CrewMember plus the roster fields Verse shows). */
struct VERSECREW_API FVerseCrewMember
{
	/** agent_id or pane_id. */
	FString Id;
	FString Name;
	FString Title;
	EVerseCrewRole Role = EVerseCrewRole::Officer;
	/** The duty in effect (backend duty, or a QA override). */
	EVerseCrewDuty Duty = EVerseCrewDuty::Idle;
	/** Arrival order on the roster: the service-order tie breaker (createdMs in the TS code). */
	int64 ArrivalOrder = 0;
	/** The assistant's lead agent (tier "lead"). */
	bool bLead = false;
	int32 Level = 1;
	FString RankId;
	FString Tier;
	FString Look;
	FString FigureArchetype;
	FString FigurePalette;
	TArray<FString> TeamIds;
	/** Technicians: the pane's history id (stable body and accent per pane lifetime, parity F-04). */
	FString HistoryId;
	FString WorkspaceId;
};

/** Service order: lead first, then by arrival, then by id (life/crew.ts byServiceOrder). */
VERSECREW_API bool VerseCrewServiceOrderLess(const FVerseCrewMember& A, const FVerseCrewMember& B);

namespace VerseCrew
{
	/** FNV-1a over UTF-16 code units, identical to life/crew.ts hash32. */
	VERSECREW_API uint32 Hash32(const FString& Text);

	/** Parses a bridge duty value; anything unknown is Idle (bridge-protocol.md 4.2 fallback). */
	VERSECREW_API EVerseCrewDuty ParseDuty(const FString& Value);
	/** Parses a duty value strictly; false for anything outside DUTY_STATUSES. */
	VERSECREW_API bool TryParseDuty(const FString& Value, EVerseCrewDuty& Out);
	VERSECREW_API const TCHAR* DutyName(EVerseCrewDuty Duty);

	VERSECREW_API const TCHAR* VenueName(EVerseCrewVenue Venue);
	VERSECREW_API const TCHAR* ActivityName(EVerseCrewActivity Activity);

	/** Own walk pace 1.20-1.45 m/s from the id (life/cast.ts walkPace), in cm/s. */
	VERSECREW_API float WalkPaceCmPerSecond(const FString& Id);
}

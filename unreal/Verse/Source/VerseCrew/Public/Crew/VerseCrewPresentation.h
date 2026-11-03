#pragma once

#include "Crew/VerseCrewTypes.h"
#include "CoreMinimal.h"

/** How a duty status looks on a crew member (parity E-10, E-11). */
struct VERSECREW_API FVerseCrewDutyLook
{
	EVerseCrewDuty Duty = EVerseCrewDuty::Idle;
	EVerseCrewBeacon Beacon = EVerseCrewBeacon::None;
	/** Beacon and floor ring colour (linear). */
	FLinearColor Colour = FLinearColor::Gray;
	/** Pulse period of a slow pulse, seconds. */
	float PulseSeconds = 2.f;
	/** Off duty: the ring is drawn grey. */
	bool bOnDuty = false;
	/** Key of the localised status word (verse.ranks.duty.<id>). */
	FString LabelKey;
};

/** One rung of the rank ladder (dodaios/progression/rules.py RANKS, ranks/ranks.ts plates). */
struct VERSECREW_API FVerseCrewRank
{
	FString Id;
	int32 Level = 1;
	/** deck, line, command, flag. */
	FString Tier;
	/** Six plate slots, top row then bottom row. */
	TArray<bool> PlateLit;
};

struct VERSECREW_API FVerseCrewTierStyle
{
	FString Tier;
	FString Uniform;
	FLinearColor Tile = FLinearColor::Gray;
};

/** The full look of one member: uniform, rank plate, status. */
struct VERSECREW_API FVerseCrewLook
{
	FString RankId;
	FString Tier;
	FString Uniform;
	FLinearColor Tile = FLinearColor::Gray;
	TArray<bool> PlateLit;
	/** Stable accent hue per look id (technicians: per history id), 0..1. */
	float AccentHue = 0.f;
};

/**
 * Crew presentation data: duty looks, the rank ladder and tier styles, read from
 * unreal/Verse/Data/crew/{duty_presentation,ranks}.json with the same values built in.
 */
class VERSECREW_API FVerseCrewPresentation
{
public:
	FVerseCrewPresentation();

	/** Reads the JSON files in Dir; keeps the built-in values for anything missing. */
	bool LoadFrom(const FString& Dir, FString& OutError);

	const FVerseCrewDutyLook& DutyLook(EVerseCrewDuty Duty) const;
	/** The look of a raw bridge duty value; anything unknown is the idle look. */
	const FVerseCrewDutyLook& DutyLookOf(const FString& RawDuty) const;

	/** The rank by id, or the first rank (bridge-protocol.md 4.2 fallback). */
	const FVerseCrewRank& Rank(const FString& RankId) const;
	/** The rank a level holds (rules.py rank_for). */
	const FVerseCrewRank& RankForLevel(int32 Level) const;
	const FVerseCrewTierStyle& TierStyle(const FString& Tier) const;
	const TArray<FVerseCrewRank>& Ranks() const { return Ladder; }

	FVerseCrewLook LookOf(const FVerseCrewMember& Member) const;

	/** unreal/Verse/Data/crew. */
	static FString DefaultDataDir();

private:
	TArray<FVerseCrewDutyLook> Duties;
	TArray<FVerseCrewRank> Ladder;
	TArray<FVerseCrewTierStyle> Tiers;
};

/** Crew life tuning (unreal/Verse/Data/crew/crew_tuning.json). Start values, not contract. */
struct VERSECREW_API FVerseCrewTuning
{
	/** Re-plan off-duty moves at least this often (parity C-16). */
	float ReplanSeconds = 20.f;
	/** A new agent counts as arriving this long (life/useCrewLife.ts ARRIVAL_MS). */
	float ArrivalSeconds = 40.f;
	float WalkTogetherMetres = 50.f;
	float HeelMetres = 2.5f;
	float WalkTogetherCooldownSeconds = 20.f;
	float WorldActionTickSeconds = 0.5f;
	/** Companion drone: cruise pace, top speed when catching up, hover height, heel offset behind and right. */
	float CompanionPaceCmS = 170.f;
	float CompanionMaxCmS = 900.f;
	float CompanionHoverCm = 140.f;
	FVector2D CompanionHeelOffsetCm = FVector2D(-120.f, 60.f);
	/** Crowd: capsule radius used for separation, separation strength. */
	float CrewRadiusCm = 35.f;
	float SeparationGain = 1.f;
	/** A pawn that has not got closer to its goal for this long counts as stuck. */
	float StuckSeconds = 6.f;
	/** A walker without progress for this long squeezes past others (doorway jams in counterflow). */
	float YieldSeconds = 2.f;
	float ArriveToleranceCm = 15.f;
	/** Hangar arena bounds, deck-local cm (WP11 owns the real zone; this is its start value). */
	FBox ArenaBoundsCm = FBox(FVector(1000.f, 400.f, -100.f), FVector(6000.f, 4400.f, 1500.f));
	/** Open commands per second at most (bridge-protocol.md 11: 4/s). */
	float OpenCommandsPerSecond = 4.f;
	/** Placeholder body until WP13's crew rig lands (contracts/art-pipeline.md 12). */
	FString BodyMesh = TEXT("/Game/Verse/Test/G0/SK_Test_Human.SK_Test_Human");
	float SitDropCm = 45.f;
	float BeaconHeightCm = 215.f;
	float NameplateHeightCm = 235.f;
	/** Salute after a commander promotion (parity C-19). */
	float SaluteSeconds = 3.f;
	/**
	 * Game-thread budget per tick for queued crew work (planning a deck, spawning a pawn, a
	 * nav path query, retiring a pawn): work stops once the tick has used this much; the rest
	 * waits for the next tick (A15.5: the crew tick stays at most 1 ms).
	 */
	float TickBudgetMs = 0.45f;
	/** No work item starts unless its predicted cost keeps the tick under this. */
	float TickHardCapMs = 0.8f;
	/** How far a socket may sit from the navmesh and still be reached (chairs block their own cell). */
	FVector NavProjectExtentCm = FVector(150.f, 150.f, 250.f);
	/** Retired pawns kept hidden for reuse, so churn does not spawn and destroy actors. */
	int32 PawnPoolSize = 16;

	bool LoadFrom(const FString& Path, FString& OutError);
	static FString DefaultPath();
};

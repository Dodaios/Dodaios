#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

/** Side of a pairing: A is the side under test. */
enum class EVerseSide : uint8
{
	A,
	B,
	None
};

/** One kill on the bout timeline (verse.bout/1 "kills"). */
struct VERSEHARNESS_API FVerseBoutKill
{
	double T = 0.0;
	EVerseSide Killer = EVerseSide::None;
	EVerseDamageSource Cause = EVerseDamageSource::Bolt;
	bool bHeadshot = false;
	bool bWall = false;
	float RangeM = -1.f;
	float TtkS = -1.f;
	bool bSpawnKill = false;
};

/** Per-side counters of one bout (verse.bout/1 "a" and "b"). */
struct VERSEHARNESS_API FVerseBoutSide
{
	int32 Kills = 0;
	int32 Deaths = 0;
	int32 Shots = 0;
	int32 Hits = 0;
	int32 HeadshotHits = 0;
	TArray<float> TimeToContactS;
	int32 BulwarkUses = 0;
	int32 BreachUses = 0;
	int32 ReloadsInFight = 0;
	int32 StuckEvents = 0;

	// Per-life state.
	double LifeStartS = 0.0;
	double FirstHitTakenS = -1.0;
	bool bContactThisLife = false;
	double LastFightS = -1.0e9;
	FVector LastMovedFrom = FVector::ZeroVector;
	double LastMovedS = 0.0;
	bool bHasPosition = false;
};

/**
 * Turns hub events of one bout into the verse.bout/1 record (bot.md 11.3). Pure logic: the
 * gauntlet controller feeds it events and clock values, the tests feed it synthetic ones.
 * Times are seconds of match time since the bout began.
 */
class VERSEHARNESS_API FVerseBoutRecorder
{
public:
	/** Kills within this long of the victim's (re)spawn are spawn kills (bot.md 11.3). */
	static constexpr double SpawnKillWindowS = 3.0;
	/** A reload this soon after a hit involving the reloader counts as in-fight. */
	static constexpr double FightWindowS = 3.0;
	/** Alive and not moved 50 cm for this long is a stuck event. */
	static constexpr double StuckAfterS = 15.0;
	static constexpr double StuckDistanceCm = 50.0;

	FVerseBoutRecorder(int32 InPlayerIdA, int32 InPlayerIdB, int32 InKillsToWin, double InTimeLimitS);

	EVerseSide SideOf(int32 PlayerId) const;

	void OnFire(const FVerseFireEvent& Event, double T);
	void OnHit(const FVerseHitEvent& Event, double T);
	void OnDeath(const FVerseDeathEvent& Event, double T);
	void OnReload(const FVerseReloadEvent& Event, double T);
	void OnGadget(const FVerseGadgetEvent& Event, double T);

	/** A respawn of PlayerId at time T (starts a life). */
	void OnRespawn(int32 PlayerId, double T);

	/** Pawn position sample for the stuck counter; bAlive false pauses it. */
	void SamplePosition(EVerseSide Side, const FVector& Location, bool bAlive, double T);

	/** True once a side reached KillsToWin or the time limit passed. */
	bool IsOver(double T) const;

	EVerseSide Winner() const;

	const FVerseBoutSide& Side(EVerseSide S) const { return S == EVerseSide::A ? SideA : SideB; }
	const TArray<FVerseBoutKill>& Kills() const { return KillList; }

	/** The verse.bout/1 line (no trailing newline). */
	FString ToJsonLine(const FString& Pairing, int32 Match, int32 Bout, uint32 Seed, int32 SpawnSideA,
		double DurationS, double MatchTimeStartS, const TArray<float>& AdaptiveTrace) const;

private:
	FVerseBoutSide& Mutable(EVerseSide S) { return S == EVerseSide::A ? SideA : SideB; }
	void Contact(EVerseSide S, double T);

	int32 PlayerIdA;
	int32 PlayerIdB;
	int32 KillsToWin;
	double TimeLimitS;
	FVerseBoutSide SideA;
	FVerseBoutSide SideB;
	TArray<FVerseBoutKill> KillList;
	/** The killing hit seen last per victim side, to classify the death that follows. */
	FVerseHitEvent LastHitOn[2];
	bool bHasLastHit[2] = {false, false};
};

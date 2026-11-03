#pragma once

#include "CoreMinimal.h"

// The scenario file one headless harness process plays (schema verse.scenario/1,
// unreal/Verse/Harness/schema/scenario.schema.json; contracts/bot.md 11.1). balance.py writes
// it, UVerseBalanceGauntletController reads it from -VerseHarness=<file>.

enum class EVerseHarnessSlotKind : uint8
{
	Bot,
	Model
};

/** One side of a pairing. */
struct VERSEHARNESS_API FVerseHarnessSlot
{
	EVerseHarnessSlotKind Kind = EVerseHarnessSlotKind::Bot;

	/** normal, hard, elite, adaptive for a bot; the base tier of a trick model ("base hard"). */
	FName Tier;

	/** Per-match learning on (bot.md 7); BG8 runs the same pairing with it off. */
	bool bLearning = true;

	/** skilled or average (person_models.json); empty for a tier-based trick model. */
	FName Model;

	/** One of the 17 trick ids of bot.md 11.2, or none. */
	FName Trick;

	bool IsBot() const { return Kind == EVerseHarnessSlotKind::Bot; }

	/** The label balance.py uses in pairing ids: "hard", "hard-nolearn", "skilled+spray", "spray". */
	FString Label() const;
};

/** One match of one pairing: the smallest unit of work, seeded independently of --jobs. */
struct VERSEHARNESS_API FVerseHarnessUnit
{
	FString Pairing;
	FString Set;
	int32 Match = 0;
	uint32 Seed = 0;
	int32 Bouts = 1;
	FVerseHarnessSlot A;
	FVerseHarnessSlot B;
	int32 KillsToWin = 15;

	/** A bout ends at KillsToWin or after this much match time (bot.md 11.1: 10 minutes). */
	double MatchTimeLimitS = 600.0;

	/** Scripted scenario id (wall_opened_unseen, destruction_storm) or none. */
	FName Scenario;

	/** The --patch tier overrides as JSON text, applied by the bot when it lands (WP09). */
	FString TierPatchJson;
};

struct VERSEHARNESS_API FVerseHarnessScenario
{
	FString Run;
	int32 Job = 0;
	FString Map;
	FString OutputDir;

	/** Wall-clock guard; the process ends its run cleanly when it passes. 0 = none. */
	double MaxWallS = 0.0;

	bool bTraceBearing = false;
	bool bTraceFireAudit = true;
	TArray<FVerseHarnessUnit> Units;

	/** Parses a verse.scenario/1 document. False with a reason on any schema error. */
	static bool Parse(const FString& JsonText, FVerseHarnessScenario& Out, FString& OutError);
};

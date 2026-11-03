#pragma once

#include "CoreMinimal.h"

// Person models and tricks of contracts/bot.md 11.2, loaded from
// unreal/Verse/Data/bot/person_models.json. A person model is the bot brain with person
// parameters; a trick is a set of input overrides plus intent hints the brain reads.

/** The 17 trick ids of bot.md 11.2 (frozen ids; the order here is not frozen). */
enum class EVerseTrick : uint8
{
	None,
	Spray,
	Camper,
	Rusher,
	Slider,
	JumpPeek,
	LeanSpam,
	Prone,
	WallSpam,
	Turtle,
	Breacher,
	Knife,
	Finisher,
	Kiter,
	Watcher,
	Silent,
	Repeek,
	Hider,
	Count
};

VERSEHARNESS_API bool VerseTrickFromName(FName Name, EVerseTrick& OutTrick);
VERSEHARNESS_API FName VerseTrickName(EVerseTrick Trick);

/** Number of real tricks (bot.md 11.2: 17). */
constexpr int32 VerseTrickCount = int32(EVerseTrick::Count) - 1;

/** Person parameters the model controller applies on top of the shared brain. */
struct VERSEHARNESS_API FVersePersonModel
{
	FName Name;
	float ReactionMeanMs = 250.f;
	float ReactionSdMs = 30.f;
	float TurnRateDegS = 800.f;
	float RecoilPatternComp = 0.6f;
	float HeadAimChance = 0.2f;
	float AimWanderSdDeg = 1.f;
	float AimWanderTheta = 3.f;
	bool bLearning = true;
	float LearnWeight = 0.1f;
};

/** What a trick asks of the brain's decisions (read by the brain once WP08 lands). */
struct VERSEHARNESS_API FVerseTrickIntent
{
	float HoldSpawnCoverRadiusM = 0.f;
	bool bRushBelief = false;
	float PreferRangeM = 0.f;
	bool bWallShotAuthorityOff = false;
	bool bFireThroughPenetrable = false;
	bool bStayBehindBulwark = false;
	bool bBreachEveryRoutePiece = false;
	bool bStalkForFinisher = false;
	bool bWatchOpponentSpawn = false;
	float RepeekSameAngleWithinS = 0.f;
	bool bAvoidFights = false;
};

/** Input-level parameters of a trick (person_models.json "input"). */
struct VERSEHARNESS_API FVerseTrickConfig
{
	EVerseTrick Trick = EVerseTrick::None;
	FVerseTrickIntent Intent;
	float LeanFlipMinMs = 150.f;
	float LeanFlipMaxMs = 300.f;
	float ProneBeyondM = 20.f;
	float MeleeRangeM = 2.f;
	float BackOffInsideM = 30.f;
	float SlideCooldownS = 1.5f;
};

struct VERSEHARNESS_API FVersePersonModelSet
{
	TMap<FName, FVersePersonModel> Models;
	TMap<FName, FVerseTrickConfig> Tricks;

	static bool Parse(const FString& JsonText, FVersePersonModelSet& Out, FString& OutError);

	/** Reads <ProjectDir>/Data/bot/person_models.json. */
	static bool LoadDefault(FVersePersonModelSet& Out, FString& OutError);

	static FString DefaultPath();
};

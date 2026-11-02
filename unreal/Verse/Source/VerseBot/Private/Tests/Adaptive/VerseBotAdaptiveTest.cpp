#include "Adaptive/VerseBotAdaptiveController.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Tests/Tiers/VerseBotTierTestUtil.h"
#include "VerseRng.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Bot.Adaptive.*: the adaptive mode of bot.md 9.2 (WP09.7), acceptance A9.5.

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// A9.5: steps never above 0.05, s in [0, 1], no change inside the deadband or before 4 kills,
// applied only at respawn.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAdaptiveTest, "Verse.Bot.Adaptive", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAdaptiveTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set = VerseBotTierTest::LoadTierSet();
	for (const FString& Error : Set.Errors) AddError(Error);
	if (!Set.IsValid())
	{
		return false;
	}
	const UVerseBotAdaptiveConfig& Config = *Set.Adaptive;
	int32 BigSteps = 0;
	int32 OutOfRange = 0;
	int32 DeadbandMoves = 0;
	int32 WarmupMoves = 0;
	int32 MidLifeApplies = 0;
	int32 Moves = 0;
	for (int32 Match = 0; Match < 1000; ++Match)
	{
		FVerseRng Rng(Match, 0, EVerseRngSalt::Harness);
		const double PersonP = Rng.Range(0.0, 1.0);
		FVerseBotAdaptiveController A;
		A.Reset(Config);
		TestEqual(TEXT("starts at StartSkill"), A.GetAppliedSkill(), Config.StartSkill);
		for (int32 Kill = 0; Kill < 80; ++Kill)
		{
			const float Before = A.GetPendingSkill();
			const float AppliedBefore = A.GetAppliedSkill();
			const bool bPerson = Rng.Chance(PersonP);
			A.OnKill(bPerson);
			const float After = A.GetPendingSkill();
			const float Step = FMath::Abs(After - Before);
			BigSteps += Step > Config.MaxStepPerKill + 1.0e-6f ? 1 : 0;
			OutOfRange += (After < 0.f || After > 1.f) ? 1 : 0;
			Moves += Step > 0.f ? 1 : 0;
			if (A.GetKillsSoFar() < Config.WarmupKills && Step > 0.f) ++WarmupMoves;
			if (FMath::Abs(A.GetWindowShare() - Config.TargetPersonShare) <= Config.Deadband && Step > 0.f) ++DeadbandMoves;
			MidLifeApplies += A.GetAppliedSkill() != AppliedBefore ? 1 : 0;
			// The bot respawns after a person kill (the bot died).
			if (bPerson)
			{
				A.OnBotRespawn();
				TestEqual(TEXT("respawn applies the pending skill"), A.GetAppliedSkill(), A.GetPendingSkill());
			}
		}
	}
	AddInfo(FString::Printf(TEXT("1000 matches x 80 kills: %d moves"), Moves));
	TestEqual(TEXT("steps above MaxStepPerKill (0.05)"), BigSteps, 0);
	TestEqual(TEXT("s outside [0, 1]"), OutOfRange, 0);
	TestEqual(TEXT("changes inside the deadband"), DeadbandMoves, 0);
	TestEqual(TEXT("changes before WarmupKills"), WarmupMoves, 0);
	TestEqual(TEXT("changes applied outside a respawn"), MidLifeApplies, 0);
	TestTrue(TEXT("the controller moves at all"), Moves > 1000);
	TestTrue(TEXT("the config caps the step at 0.05"), Config.MaxStepPerKill <= 0.05f);

	// Direction: the person winning makes the bot stronger, losing makes it weaker.
	FVerseBotAdaptiveController Up;
	Up.Reset(Config);
	for (int32 I = 0; I < 10; ++I) Up.OnKill(true);
	TestTrue(TEXT("person winning raises s"), Up.GetPendingSkill() > Config.StartSkill);
	FVerseBotAdaptiveController Down;
	Down.Reset(Config);
	for (int32 I = 0; I < 10; ++I) Down.OnKill(false);
	TestTrue(TEXT("bot winning lowers s"), Down.GetPendingSkill() < Config.StartSkill);
	TestEqual(TEXT("not applied before the respawn"), Down.GetAppliedSkill(), Config.StartSkill);
	return true;
}

// The interpolation rule of bot.md 9.2 through the controller's BuildTier.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAdaptiveTierTest, "Verse.Bot.Adaptive.Interpolation", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAdaptiveTierTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set = VerseBotTierTest::LoadTierSet();
	for (const FString& Error : Set.Errors) AddError(Error);
	if (!Set.IsValid())
	{
		return false;
	}
	TStrongObjectPtr<UVerseBotTier> Out(NewObject<UVerseBotTier>());
	FVerseBotAdaptiveController::BuildTier(*Set.Normal, *Set.Hard, *Set.Elite, 0.f, *Out);
	TestEqual(TEXT("s = 0 is normal"), Out->ReactionMs.X, Set.Normal->ReactionMs.X);
	TestTrue(TEXT("TierId is adaptive"), Out->TierId == FName(TEXT("adaptive")));
	FVerseBotAdaptiveController::BuildTier(*Set.Normal, *Set.Hard, *Set.Elite, 0.5f, *Out);
	TestEqual(TEXT("s = 0.5 is hard"), Out->TurnRateDegS, Set.Hard->TurnRateDegS);
	TestEqual(TEXT("int fields at hard"), Out->MaxBurstShots, Set.Hard->MaxBurstShots);
	FVerseBotAdaptiveController::BuildTier(*Set.Normal, *Set.Hard, *Set.Elite, 1.f, *Out);
	TestEqual(TEXT("s = 1 is elite"), Out->AimNoiseDeg, Set.Elite->AimNoiseDeg);
	FVerseBotAdaptiveController::BuildTier(*Set.Normal, *Set.Hard, *Set.Elite, 0.25f, *Out);
	TestTrue(TEXT("s = 0.25 halfway normal to hard"),
		FMath::IsNearlyEqual(Out->TurnRateDegS, 0.5f * (Set.Normal->TurnRateDegS + Set.Hard->TurnRateDegS), 1.0e-3f));
	TestTrue(TEXT("int fields round"), Out->MaxBurstShots == FMath::RoundToInt(0.5f * (Set.Normal->MaxBurstShots + Set.Hard->MaxBurstShots)));
	FVerseBotAdaptiveController::BuildTier(*Set.Normal, *Set.Hard, *Set.Elite, 1.5f, *Out);
	TestEqual(TEXT("never above elite"), Out->ReactionMs.X, Set.Elite->ReactionMs.X);
	FVerseBotAdaptiveController::BuildTier(*Set.Normal, *Set.Hard, *Set.Elite, -0.5f, *Out);
	TestEqual(TEXT("never below normal"), Out->ReactionMs.X, Set.Normal->ReactionMs.X);
	TestTrue(TEXT("the interpolated tier stays inside the contract"), Out->SatisfiesContractBounds());
	return true;
}

/**
 * Evidence: the s trace against two toy person models whose kill chance against the bot falls
 * linearly with s (anchored at the README targets: a skilled person takes about 40 % against
 * elite). This is not BG10; BG10 needs the WP10 harness with the real brain (WP08).
 */
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAdaptiveTraceTest, "Verse.Bot.Adaptive.Trace", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAdaptiveTraceTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set = VerseBotTierTest::LoadTierSet();
	for (const FString& Error : Set.Errors) AddError(Error);
	if (!Set.IsValid())
	{
		return false;
	}
	struct FModel
	{
		const TCHAR* Name;
		double AtNormal;
		double AtElite;
	};
	const FModel Models[] = {{TEXT("skilled"), 0.80, 0.40}, {TEXT("average"), 0.55, 0.15}};
	TArray<FString> Rows;
	for (const FModel& Model : Models)
	{
		double ShareSum = 0.0;
		constexpr int32 Matches = 400;
		TArray<FString> FirstTrace;
		for (int32 Match = 0; Match < Matches; ++Match)
		{
			FVerseRng Rng(7000 + Match, 0, EVerseRngSalt::Harness);
			FVerseBotAdaptiveController A;
			A.Reset(*Set.Adaptive);
			int32 PersonKills = 0;
			for (int32 Kill = 1; Kill <= 60; ++Kill)
			{
				const double P = FMath::Lerp(Model.AtNormal, Model.AtElite, double(A.GetAppliedSkill()));
				const bool bPerson = Rng.Chance(P);
				A.OnKill(bPerson);
				if (bPerson)
				{
					A.OnBotRespawn();
				}
				if (Kill > 30)
				{
					PersonKills += bPerson ? 1 : 0;
				}
				if (Match == 0)
				{
					FirstTrace.Add(FString::Printf(TEXT("%.4f"), A.GetAppliedSkill()));
				}
			}
			ShareSum += PersonKills / 30.0;
		}
		const double Share = ShareSum / Matches;
		AddInfo(FString::Printf(TEXT("toy %s person: share over kills 30-60 = %.3f"), Model.Name, Share));
		TestTrue(FString::Printf(TEXT("toy %s: share 0.40-0.60"), Model.Name), Share >= 0.40 && Share <= 0.60);
		Rows.Add(FString::Printf(TEXT("\"%s\": {\"personShareKills30to60\": %.4f, \"sAfterEveryKillMatch0\": [%s]}"), Model.Name, Share,
			*FString::Join(FirstTrace, TEXT(", "))));
	}
	FFileHelper::SaveStringToFile(TEXT("{") + FString::Join(Rows, TEXT(", ")) + TEXT("}"), *FPaths::Combine(VerseBotTierTest::ProofDir(TEXT("WP09.7")), TEXT("adaptive_s_trace.json")));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

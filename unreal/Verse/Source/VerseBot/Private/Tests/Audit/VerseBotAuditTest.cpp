#include "Audit/VerseBotFireAudit.h"
#include "Bot/VerseBotTier.h"
#include "Misc/AutomationTest.h"
#include "Tests/Brain/Fakes/FakeVerseDuelSim.h"
#include "Tests/Brain/VerseBotTestProof.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// 8.10: the F4 classifier (bot.md 8.4) and the log format.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAuditClassifierTest, "Verse.Bot.Audit.Classifier", VERSE_BOT_TEST_FLAGS)

bool FVerseBotAuditClassifierTest::RunTest(const FString& Parameters)
{
	UVerseBotTier* T = NewObject<UVerseBotTier>();
	UVerseBotTier::ApplyStartValues(TEXT("hard"), *T);
	using EMode = EVerseBotFireMode;
	{
		FVerseBotFireEvidence E;
		E.bTargetVisible = true;
		TestEqual(TEXT("visible"), FVerseBotFireClassifier::Classify(E, *T), EMode::Visible);
		E.bTargetSpawnProtected = true;
		TestEqual(TEXT("never at a spawn-protected target"), FVerseBotFireClassifier::Classify(E, *T), EMode::Unclassified);
	}
	{
		FVerseBotFireEvidence E;
		E.SinceSightLostS = 0.3f;
		E.LastSeenLocation = FVector(1000.f, 0.f, 100.f);
		E.AimPoint = FVector(1150.f, 0.f, 100.f);
		TestEqual(TEXT("suppression inside 0.35 s and 2 m"), FVerseBotFireClassifier::Classify(E, *T), EMode::Suppression);
		E.SinceSightLostS = 0.36f;
		TestEqual(TEXT("no suppression after 0.35 s"), FVerseBotFireClassifier::Classify(E, *T), EMode::Unclassified);
		E.SinceSightLostS = 0.3f;
		E.AimPoint = FVector(1250.f, 0.f, 100.f);
		TestEqual(TEXT("no suppression beyond 2 m"), FVerseBotFireClassifier::Classify(E, *T), EMode::Unclassified);
	}
	{
		FVerseBotFireEvidence E;
		E.bPrefireRolled = true;
		E.bAimAtPeekEdge = true;
		E.HeardAgeS = 1.5f;
		E.HeardLocation = FVector(500.f, 0.f, 0.f);
		E.AimPoint = FVector(900.f, 0.f, 0.f);
		E.SupportedMassAtAim = 0.5f;
		TestEqual(TEXT("prefire"), FVerseBotFireClassifier::Classify(E, *T), EMode::Prefire);
		E.HeardAgeS = 2.5f;
		TestEqual(TEXT("no prefire on an old sound"), FVerseBotFireClassifier::Classify(E, *T), EMode::Unclassified);
		E.HeardAgeS = 1.5f;
		E.SupportedMassAtAim = 0.3f;
		TestEqual(TEXT("no prefire below WallbangMinBelief"), FVerseBotFireClassifier::Classify(E, *T), EMode::Unclassified);
	}
	{
		FVerseBotFireEvidence E;
		E.bAimInTopCluster = true;
		E.bPriorOnly = false;
		E.SupportedMassAtAim = 0.5f;
		E.SupportAgeS = 2.f;
		E.TraceDamageFrac = 0.6f;
		E.TracePieces = 1;
		TestEqual(TEXT("wall shot with authority"), FVerseBotFireClassifier::Classify(E, *T), EMode::WallShot);
		E.bPriorOnly = true;
		TestEqual(TEXT("prior-only mass never authorises"), FVerseBotFireClassifier::Classify(E, *T), EMode::Unclassified);
	}
	{
		FVerseBotFireEvidence E;
		E.ServerTimeMs = 1234;
		E.bTargetVisible = true;
		E.SightPerceptId = 42;
		E.MassAtAim = 0.75f;
		E.SupportAgeS = 0.f;
		const FVerseBotFireAudit A = FVerseBotFireClassifier::MakeAudit(E, EMode::Visible);
		TestEqual(TEXT("log line"), A.ToLogLine(), FString(TEXT("VerseBotFire t=1234 mode=visible visible=1 percepts=42 mass=0.750 age=0.00")));
	}
	return true;
}

// A8.3 / F4: every fire-held tick of the bot is classified; 0 unclassified over 1,000 bouts.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAuditBoutsTest, "Verse.Bot.Audit.Bouts", VERSE_BOT_TEST_FLAGS)

bool FVerseBotAuditBoutsTest::RunTest(const FString& Parameters)
{
	constexpr int32 TargetBouts = 1000;
	int32 Bouts = 0;
	int64 FireTicks = 0;
	int64 Audited = 0;
	int64 Unclassified = 0;
	int64 ByMode[5] = {};
	int64 Reclassified = 0;
	FString Sample;
	const FName Tiers[3] = {TEXT("normal"), TEXT("hard"), TEXT("elite")};
	for (int32 Run = 0; Bouts < TargetBouts && Run < 400; ++Run)
	{
		FFakeVerseDuelSim::FConfig Cfg;
		Cfg.Seed = 9000 + Run;
		FFakeVerseDuelSim Sim(Tiers[Run % 3], Cfg);
		// One run: up to 5 bouts or 4 minutes.
		for (int32 t = 0; t < 4 * 60 * 60 && Sim.Kills() < 5; ++t)
		{
			Sim.Tick();
		}
		Bouts += Sim.Kills();
		FireTicks += Sim.FireTicks;
		const FVerseBotFireAuditLog& Log = Sim.Brain.GetFireAudit();
		Audited += Log.Num();
		for (const FVerseBotFireAudit& A : Log.GetEntries())
		{
			++ByMode[int32(A.Mode)];
			Unclassified += A.Mode == EVerseBotFireMode::Unclassified ? 1 : 0;
			Reclassified += A.PerceptIds.Num() > 0 || A.Mode == EVerseBotFireMode::Suppression ? 1 : 0;
		}
		if (Sample.IsEmpty() && Log.Num() > 0)
		{
			for (int32 i = 0; i < FMath::Min(20, Log.Num()); ++i)
			{
				Sample += Log.GetEntries()[i].ToLogLine() + TEXT("\n");
			}
		}
	}
	TestTrue(TEXT("1,000 bouts played"), Bouts >= TargetBouts);
	TestEqual(TEXT("every fire-held tick has an audit record"), Audited, FireTicks);
	TestEqual(TEXT("0 unclassified shots"), Unclassified, int64(0));
	TestTrue(TEXT("every audit names its backing percepts"), Reclassified == Audited);
	VerseBotTestProof::Write(TEXT("8.10"), TEXT("f4_fire_audit.json"),
		FString::Printf(TEXT("{\n  \"test\": \"F4\",\n  \"bouts\": %d,\n  \"fireTicks\": %lld,\n  \"audited\": %lld,\n  \"unclassified\": %lld,\n  \"visible\": %lld,\n  \"suppression\": %lld,\n  \"prefire\": %lld,\n  \"wallShot\": %lld\n}\n"),
			Bouts, FireTicks, Audited, Unclassified, ByMode[1], ByMode[2], ByMode[3], ByMode[4]));
	VerseBotTestProof::Write(TEXT("8.10"), TEXT("fire_audit_sample.log"), Sample);
	AddInfo(FString::Printf(TEXT("F4: %d bouts, %lld audited fire ticks, %lld unclassified"), Bouts, Audited, Unclassified));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

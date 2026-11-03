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

// A8.3 / F4 at the shot event: every round the bot's weapon fired over 1,000 bouts has an audit
// record of that tick, no record is unclassified, and an independent pass over the percepts the
// sim delivered re-derives each record's mode (fire intents the gate blocked are reported apart).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAuditBoutsTest, "Verse.Bot.Audit.Bouts", VERSE_BOT_TEST_FLAGS)

namespace VerseBotAuditTest
{
	using FSim = FFakeVerseDuelSim;

	/** The independent re-check of one record against the delivered percepts (8.4 windows). */
	bool Recheck(const FVerseBotFireAudit& A, const FSim::FShot& Shot, const TMap<uint32, FSim::FDelivered>& Delivered)
	{
		auto AgeMs = [&](uint32 Id, FSim::EDelivered Kind, uint32& OutAge) -> bool
		{
			const FSim::FDelivered* D = Delivered.Find(Id);
			if (!D || D->Kind != Kind || D->TimeMs > Shot.TimeMs)
			{
				return false;
			}
			OutAge = Shot.TimeMs - D->TimeMs;
			return true;
		};
		uint32 Age = 0;
		switch (A.Mode)
		{
		case EVerseBotFireMode::Visible:
			// A sighting delivered this very tick, and the fair sight rule held (sim truth).
			return A.bTargetVisible && Shot.bBotSawOpponent && A.PerceptIds.Num() > 0
				&& AgeMs(A.PerceptIds[0], FSim::EDelivered::Sight, Age) && Age == 0;
		case EVerseBotFireMode::Suppression:
			// A sighting delivered at most 0.35 s (+ one tick) before the shot.
			return A.PerceptIds.Num() > 0 && AgeMs(A.PerceptIds[0], FSim::EDelivered::Sight, Age) && Age <= 350 + 17;
		case EVerseBotFireMode::Prefire:
			// A heard percept of the last 2 s backs it.
			for (uint32 Id : A.PerceptIds)
			{
				if (AgeMs(Id, FSim::EDelivered::Heard, Age) && Age <= 2000)
				{
					return true;
				}
			}
			return false;
		case EVerseBotFireMode::WallShot:
			// A seen or heard percept within the contract's 4 s source-age cap backs it.
			for (uint32 Id : A.PerceptIds)
			{
				if ((AgeMs(Id, FSim::EDelivered::Heard, Age) || AgeMs(Id, FSim::EDelivered::Sight, Age)) && Age <= 4000)
				{
					return true;
				}
			}
			return false;
		default:
			return false;
		}
	}
}

bool FVerseBotAuditBoutsTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotAuditTest;
	constexpr int32 TargetBouts = 1000;
	int32 Bouts = 0;
	int64 Shots = 0;
	int64 ShotsWithoutRecord = 0;
	int64 Records = 0;
	int64 Unclassified = 0;
	int64 RecheckFailures = 0;
	int64 Blocked = 0;
	int64 ByMode[5] = {};
	FString Sample;
	FString FirstFailure;
	const FName Tiers[3] = {TEXT("normal"), TEXT("hard"), TEXT("elite")};
	for (int32 Run = 0; Bouts < TargetBouts && Run < 400; ++Run)
	{
		FSim::FConfig Cfg;
		Cfg.Seed = 9000 + Run;
		FSim Sim(Tiers[Run % 3], Cfg);
		Sim.bRecordShots = true;
		Sim.Brain.GetFireAudit().SetCaptureAll(true);
		// One run: up to 5 bouts or 4 minutes.
		for (int32 t = 0; t < 4 * 60 * 60 && Sim.Kills() < 5; ++t)
		{
			Sim.Tick();
		}
		Bouts += Sim.Kills();
		const FVerseBotFireAuditLog& Log = Sim.Brain.GetFireAudit();
		const TArray<FVerseBotFireAudit> Entries = Log.GetEntries();
		Records += Entries.Num();
		Blocked += Log.BlockedCount();
		TMap<uint32, int32> ByTime;
		for (int32 i = 0; i < Entries.Num(); ++i)
		{
			ByTime.Add(Entries[i].ServerTimeMs, i);
			Unclassified += Entries[i].Mode == EVerseBotFireMode::Unclassified ? 1 : 0;
		}
		for (const FSim::FShot& Shot : Sim.Shots)
		{
			++Shots;
			const int32* Index = ByTime.Find(Shot.TimeMs);
			if (!Index)
			{
				++ShotsWithoutRecord;
				continue;
			}
			const FVerseBotFireAudit& A = Entries[*Index];
			++ByMode[int32(A.Mode)];
			if (!Recheck(A, Shot, Sim.Delivered))
			{
				++RecheckFailures;
				if (FirstFailure.IsEmpty())
				{
					FirstFailure = A.ToLogLine();
				}
			}
		}
		if (Sample.IsEmpty() && Entries.Num() > 0)
		{
			for (int32 i = 0; i < FMath::Min(20, Entries.Num()); ++i)
			{
				Sample += Entries[i].ToLogLine() + TEXT("\n");
			}
		}
	}
	TestTrue(TEXT("1,000 bouts played"), Bouts >= TargetBouts);
	TestTrue(TEXT("the bot fired"), Shots > 0);
	TestEqual(TEXT("every fired round has an audit record of its tick"), ShotsWithoutRecord, int64(0));
	TestEqual(TEXT("0 unclassified records"), Unclassified, int64(0));
	TestEqual(TEXT("the independent pass re-derives every fired round's mode"), RecheckFailures, int64(0));
	if (!FirstFailure.IsEmpty())
	{
		AddInfo(FString::Printf(TEXT("first recheck failure: %s"), *FirstFailure));
	}
	VerseBotTestProof::Write(TEXT("8.10"), TEXT("f4_fire_audit.json"),
		FString::Printf(TEXT("{\n  \"test\": \"F4\",\n  \"bouts\": %d,\n  \"shotsFired\": %lld,\n  \"shotsWithoutRecord\": %lld,\n  \"records\": %lld,\n  \"unclassified\": %lld,\n  \"recheckFailures\": %lld,\n  \"blockedFireIntents\": %lld,\n  \"shotsVisible\": %lld,\n  \"shotsSuppression\": %lld,\n  \"shotsPrefire\": %lld,\n  \"shotsWallShot\": %lld\n}\n"),
			Bouts, Shots, ShotsWithoutRecord, Records, Unclassified, RecheckFailures, Blocked, ByMode[1], ByMode[2], ByMode[3], ByMode[4]));
	VerseBotTestProof::Write(TEXT("8.10"), TEXT("fire_audit_sample.log"), Sample);
	AddInfo(FString::Printf(TEXT("F4: %d bouts, %lld rounds fired, %lld without record, %lld recheck failures, %lld blocked intents"),
		Bouts, Shots, ShotsWithoutRecord, RecheckFailures, Blocked));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

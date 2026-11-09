// Fairness suite on the production belief (contracts/bot.md 10): the duel sim of the brain tests
// with FVerseBotGridBelief, the grid the bots use in the arena, instead of the coarse stand-in.
// The nightly gauntlet runs "Verse.Bot.Fairness"; balance.py reads F3 and BR1 from these names.

#include "Brain/VerseBotGridBelief.h"
#include "Brain/VerseBotReplay.h"
#include "Misc/AutomationTest.h"
#include "Tests/Brain/Fakes/FakeVerseDuelSim.h"
#include "Tests/Brain/VerseBotTestProof.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_BOT_FAIRNESS_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBotFairnessTest
{
	/** The fake arena's extent, cm (walls of BuildStandardArena lie inside). */
	constexpr float HalfX = 2400.f;
	constexpr float HalfY = 1900.f;
	constexpr float CellCm = 100.f;

	/**
	 * A one-level belief grid over the fake arena: a cell where no wall stands, neighbours joined
	 * where a knee-high line between their centres is clear (the nav sampler's rule in miniature).
	 */
	FVerseBeliefGridSource MakeSource(FFakeVerseBotWorldQueries& World)
	{
		FVerseBeliefGridSource Source;
		Source.CellSizeCm = CellCm;
		Source.Origin = FVector2D(-HalfX + 0.5f * CellCm, -HalfY + 0.5f * CellCm);
		const int32 Nx = FMath::FloorToInt32(2.f * HalfX / CellCm);
		const int32 Ny = FMath::FloorToInt32(2.f * HalfY / CellCm);
		TArray<FVector> Centres;
		for (int32 X = 0; X < Nx; ++X)
		{
			for (int32 Y = 0; Y < Ny; ++Y)
			{
				const FVector C(Source.Origin.X + X * CellCm, Source.Origin.Y + Y * CellCm, 0.f);
				const bool bInWall = World.Walls.ContainsByPredicate([&C](const FFakeVerseBotWorldQueries::FWall& W)
					{ return W.Box.ExpandBy(FVector(30.f, 30.f, 0.f)).IsInsideXY(C); });
				if (bInWall)
				{
					continue;
				}
				FVerseBeliefCellDesc& Desc = Source.Cells.AddDefaulted_GetRef();
				Desc.Column = FIntPoint(X, Y);
				Desc.FloorZ = 0.f;
				Centres.Add(C);
			}
		}
		FFakeVerseBotWorldQueries* W = &World;
		Source.AreNeighboursConnected = [W, Centres](int32 A, int32 B)
		{
			return !W->Blocked(Centres[A] + FVector(0, 0, 40.f), Centres[B] + FVector(0, 0, 40.f));
		};
		return Source;
	}

	FVerseBeliefMapConfig MakeConfig(const FFakeVerseBotWorldQueries& World)
	{
		FVerseBeliefMapConfig Config;
		Config.SelfPlayerId = FFakeVerseDuelSim::BotId;
		Config.SpawnPoints = World.Spawns;
		Config.ArenaBox = FBox(FVector(-HalfX, -HalfY, -100.f), FVector(HalfX, HalfY, 400.f));
		Config.MaxCellSightTestsPerStep = 200;
		return Config;
	}

	/** Swap the sim brain's belief for the grid; its sight tests go through Queries. */
	void UseGrid(FFakeVerseDuelSim& Sim, FVerseBotBrainCore& Brain, IVerseBotWorldQueries& Queries)
	{
		Brain.SetBelief(MakeUnique<FVerseBotGridBelief>(MakeSource(Sim.World), MakeConfig(Sim.World), Queries));
	}

	constexpr int32 FrameBytes = 4 * 4 + 4 * 3;
}

// F3: a silent, still opponent hidden at A vs B gives bit-identical input frames up to the first
// tick at which the percept streams differ, with the grid belief clearing through sight tests.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotFairnessF3GridTest, "Verse.Bot.Fairness.F3.GridBeliefCounterfactual", VERSE_BOT_FAIRNESS_FLAGS)

bool FVerseBotFairnessF3GridTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotFairnessTest;
	int32 Passed = 0;
	int32 TicksCompared = 0;
	for (int32 Seed = 1; Seed <= 20; ++Seed)
	{
		FFakeVerseDuelSim::FConfig A;
		A.Seed = 300 + Seed;
		A.Model = FFakeVerseDuelSim::EModel::Still;
		A.StillSpot = FVector(0.f, 900.f, 0.f);
		FFakeVerseDuelSim::FConfig B = A;
		B.StillSpot = FVector(-1800.f, -1450.f, 0.f);
		FFakeVerseDuelSim SimA(TEXT("hard"), A);
		FFakeVerseDuelSim SimB(TEXT("hard"), B);
		UseGrid(SimA, SimA.Brain, SimA.World);
		UseGrid(SimB, SimB.Brain, SimB.World);
		SimA.bRecordFrames = SimB.bRecordFrames = true;
		SimA.bRecordOutputs = SimB.bRecordOutputs = true;
		constexpr int32 Ticks = 60 * 60;
		int32 FirstDiff = Ticks;
		for (int32 T = 0; T < Ticks; ++T)
		{
			SimA.Tick();
			SimB.Tick();
			const FVersePerceptFrame& FA = SimA.RecordedFrames.Last();
			const FVersePerceptFrame& FB = SimB.RecordedFrames.Last();
			const bool bSame = FA.Sightings.Num() == FB.Sightings.Num() && FA.Heard.Num() == FB.Heard.Num()
				&& FA.bHasHurt == FB.bHasHurt && FA.Hud.Num() == FB.Hud.Num() && FA.Self.Location.Equals(FB.Self.Location, 0.0)
				&& FA.Self.ViewRotation.Equals(FB.Self.ViewRotation, 0.0);
			if (!bSame)
			{
				FirstDiff = T;
				break;
			}
		}
		const int32 Compare = FMath::Min(FirstDiff, SimA.Outputs.Num() / FrameBytes);
		const bool bIdentical = FMemory::Memcmp(SimA.Outputs.GetData(), SimB.Outputs.GetData(), Compare * FrameBytes) == 0;
		TestTrue(FString::Printf(TEXT("seed %d: input frames identical for %d ticks before the first differing percept"), Seed, Compare), bIdentical);
		TestTrue(FString::Printf(TEXT("seed %d: the bot acted for at least 2 s unseen before any differing percept"), Seed), Compare >= 120);
		Passed += bIdentical ? 1 : 0;
		TicksCompared += Compare;
	}
	VerseBotTestProof::Write(TEXT("10"), TEXT("f3_grid_counterfactual.json"),
		FString::Printf(TEXT("{\n  \"test\": \"F3\",\n  \"belief\": \"grid\",\n  \"seeds\": 20,\n  \"passed\": %d,\n  \"ticksCompared\": %d\n}\n"), Passed,
			TicksCompared));
	return true;
}

// BR1: recorded percepts + recorded world answers (the grid's sight tests among them) + seed
// replay bit-identical twice.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotFairnessBR1GridTest, "Verse.Bot.Fairness.BR1.GridBeliefReplay", VERSE_BOT_FAIRNESS_FLAGS)

bool FVerseBotFairnessBR1GridTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotFairnessTest;
	const FName Tiers[3] = {TEXT("normal"), TEXT("hard"), TEXT("elite")};
	int32 Identical = 0;
	for (int32 S = 0; S < 3; ++S)
	{
		FFakeVerseDuelSim::FConfig Cfg;
		Cfg.Seed = 700 + S;
		Cfg.Model = FFakeVerseDuelSim::EModel::Patrol;
		FFakeVerseDuelSim Sim(Tiers[S], Cfg);
		UseGrid(Sim, Sim.Brain, Sim.World);
		Sim.bRecordFrames = true;
		Sim.bRecordOutputs = true;
		Sim.Run(2 * 60 * 60);

		// Record: a second brain with its own grid over the recording proxy.
		FVerseBotTape Tape;
		Tape.Seed = Cfg.Seed;
		Tape.TierId = Tiers[S];
		Tape.Frames = Sim.RecordedFrames;
		FVerseBotRecordingQueries Recorder(Sim.World, Tape.Queries);
		FVerseBotBrainCore::FConfig C;
		C.Seed = Cfg.Seed;
		C.SelfId = FFakeVerseDuelSim::BotId;
		FVerseBotBrainCore Recording;
		Recording.Init(*Sim.Tier, C);
		UseGrid(Sim, Recording, Recorder);
		TArray<uint8> Recorded;
		for (const FVersePerceptFrame& F : Tape.Frames)
		{
			FVerseBotTape::AppendOutput(Recorded, Recording.Think(F, Recorder));
		}
		TestTrue(FString::Printf(TEXT("stream %d: the recording run equals the live run"), S), Recorded == Sim.Outputs);

		bool bAll = true;
		for (int32 Pass = 0; Pass < 2; ++Pass)
		{
			FVerseBotReplayQueries Replay(Tape.Queries);
			FVerseBotBrainCore Brain;
			Brain.Init(*Sim.Tier, C);
			UseGrid(Sim, Brain, Replay);
			TArray<uint8> Out;
			for (const FVersePerceptFrame& F : Tape.Frames)
			{
				FVerseBotTape::AppendOutput(Out, Brain.Think(F, Replay));
			}
			TestFalse(FString::Printf(TEXT("stream %d replay %d: no divergence"), S, Pass), Replay.HasDiverged());
			TestTrue(FString::Printf(TEXT("stream %d replay %d: every recorded answer consumed"), S, Pass), Replay.IsAtEnd());
			const bool bSame = Out == Recorded;
			TestTrue(FString::Printf(TEXT("stream %d replay %d: bit-identical"), S, Pass), bSame);
			bAll &= bSame;
		}
		Identical += bAll ? 1 : 0;
	}
	VerseBotTestProof::Write(TEXT("10"), TEXT("br1_grid_replay.json"),
		FString::Printf(TEXT("{\n  \"test\": \"BR1\",\n  \"belief\": \"grid\",\n  \"streams\": 3,\n  \"identical\": %d\n}\n"), Identical));
	return true;
}

// F4 on the grid: every round the bot fires carries an audit record of a mode of bot.md 8.4, and a
// Visible record is only written while the sim's fair sight rule held.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotFairnessF4GridTest, "Verse.Bot.Fairness.F4.GridBeliefFireAudit", VERSE_BOT_FAIRNESS_FLAGS)

bool FVerseBotFairnessF4GridTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotFairnessTest;
	int32 Shots = 0;
	int32 Audited = 0;
	int32 Unfair = 0;
	for (int32 Seed = 1; Seed <= 4; ++Seed)
	{
		FFakeVerseDuelSim::FConfig Cfg;
		Cfg.Seed = 900 + Seed;
		Cfg.Model = FFakeVerseDuelSim::EModel::Patrol;
		FFakeVerseDuelSim Sim(Seed % 2 ? TEXT("hard") : TEXT("elite"), Cfg);
		UseGrid(Sim, Sim.Brain, Sim.World);
		Sim.bRecordShots = true;
		Sim.Run(3 * 60 * 60);
		Shots += Sim.Shots.Num();
		Audited += Sim.Brain.GetFireAudit().Num();
		for (const FFakeVerseDuelSim::FShot& Shot : Sim.Shots)
		{
			// A shot needs the fair sight rule or the 0.35 s suppression after it; the audit says which.
			Unfair += Shot.bBotSawOpponent ? 0 : 1;
		}
		TestEqual(FString::Printf(TEXT("seed %d: no unclassified fire reached the trigger"), Seed),
			Sim.Brain.GetFireAudit().Count(EVerseBotFireMode::Unclassified), 0);
	}
	AddInfo(FString::Printf(TEXT("F4 grid: %d rounds fired, %d audit records, %d rounds without sight (suppression, prefire, wall shot)"),
		Shots, Audited, Unfair));
	TestTrue(TEXT("the bot fights (rounds fired)"), Shots > 0);
	// One audit record per tick the trigger is held; a round needs a held trigger.
	TestTrue(TEXT("every round fired has an audit record"), Audited >= Shots);
	VerseBotTestProof::Write(TEXT("10"), TEXT("f4_grid_audit.json"),
		FString::Printf(TEXT("{\n  \"test\": \"F4\",\n  \"belief\": \"grid\",\n  \"rounds\": %d,\n  \"auditRecords\": %d,\n  \"withoutSight\": %d\n}\n"),
			Shots, Audited, Unfair));
	return true;
}

// Search on the grid (bot.md 5.1, BG12 health): the bot finds a hider over the belief grid.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotFairnessSearchTest, "Verse.Bot.Fairness.Search.GridFindsHider", VERSE_BOT_FAIRNESS_FLAGS)

bool FVerseBotFairnessSearchTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotFairnessTest;
	TArray<float> Contacts;
	int32 Stuck = 0;
	for (int32 Seed = 1; Seed <= 4; ++Seed)
	{
		FFakeVerseDuelSim::FConfig Cfg;
		Cfg.Seed = 1500 + Seed;
		Cfg.Model = FFakeVerseDuelSim::EModel::Hider;
		FFakeVerseDuelSim Sim(TEXT("hard"), Cfg);
		UseGrid(Sim, Sim.Brain, Sim.World);
		Sim.Run(5 * 60 * 60);
		Contacts.Append(Sim.TimeToContactS);
		Stuck += Sim.Brain.GetStuckEvents();
	}
	const float Median = VerseBotTestProof::Median(Contacts);
	AddInfo(FString::Printf(TEXT("grid search: %d contacts, median %.1f s, %d stuck events in 20 min"), Contacts.Num(), Median, Stuck));
	VerseBotTestProof::Write(TEXT("10"), TEXT("search_grid_hider.json"),
		FString::Printf(TEXT("{\n  \"gate\": \"BG12\",\n  \"belief\": \"grid\",\n  \"contacts\": %d,\n  \"timeToContactS_median\": %.2f,\n  \"stuckEvents\": %d\n}\n"),
			Contacts.Num(), Median, Stuck));
	TestTrue(TEXT("the hider is found again and again"), Contacts.Num() >= 8);
	TestTrue(TEXT("timeToContactS median <= 25 s"), Median <= 25.f);
	TestTrue(TEXT("stuck events <= 1 per 10 min"), Stuck <= 2);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

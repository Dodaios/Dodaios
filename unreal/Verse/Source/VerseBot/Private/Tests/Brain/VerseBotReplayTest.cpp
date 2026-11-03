#include "Brain/VerseBotReplay.h"
#include "Misc/AutomationTest.h"
#include "Tests/Brain/Fakes/FakeVerseDuelSim.h"
#include "Tests/Brain/VerseBotTestProof.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBotReplayTest
{
	/** Replays a tape on a fresh brain with the same seed and tier; returns the output bytes. */
	bool Replay(const FVerseBotTape& Tape, UVerseBotTier& Tier, TArray<uint8>& OutOutputs, bool& bOutDiverged, bool& bOutAtEnd)
	{
		FVerseBotBrainCore Brain;
		FVerseBotBrainCore::FConfig C;
		C.Seed = Tape.Seed;
		C.SelfId = FFakeVerseDuelSim::BotId;
		Brain.Init(Tier, C);
		FVerseBotReplayQueries Queries(Tape.Queries);
		OutOutputs.Reset();
		for (const FVersePerceptFrame& F : Tape.Frames)
		{
			FVerseBotTape::AppendOutput(OutOutputs, Brain.Think(F, Queries));
		}
		bOutDiverged = Queries.HasDiverged();
		bOutAtEnd = Queries.IsAtEnd();
		return !bOutDiverged;
	}
}

// A8.1 / BR1: 10 recorded 5-minute streams replay bit-identical, and the brain cost per tick.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotReplayTest, "Verse.Bot.Brain.Replay", VERSE_BOT_TEST_FLAGS)

bool FVerseBotReplayTest::RunTest(const FString& Parameters)
{
	constexpr int32 Streams = 10;
	constexpr int32 TicksPerStream = 5 * 60 * 60;
	const FName Tiers[3] = {TEXT("normal"), TEXT("hard"), TEXT("elite")};
	TArray<double> AllUs;
	FString Rows;
	int32 Identical = 0;
	for (int32 s = 0; s < Streams; ++s)
	{
		FFakeVerseDuelSim::FConfig Cfg;
		Cfg.Seed = 1000 + s;
		Cfg.Model = (s % 3 == 2) ? FFakeVerseDuelSim::EModel::Hider : FFakeVerseDuelSim::EModel::Patrol;
		const FName TierId = Tiers[s % 3];

		// Live run: the sim world, its percept frames and the brain's outputs.
		FFakeVerseDuelSim Sim(TierId, Cfg);
		FVerseBotTape Tape;
		Tape.Seed = Cfg.Seed;
		Tape.TierId = TierId;
		Sim.bRecordFrames = true;
		Sim.bRecordOutputs = true;
		Sim.bMeasure = true;
		FVerseBotRecordingQueries Recorder(Sim.World, Tape.Queries);
		Sim.Run(TicksPerStream);
		Tape.Frames = Sim.RecordedFrames;
		Tape.Outputs = Sim.Outputs;

		// Record: a second brain sees the same frames through the recording proxy over the same world
		// and must give the live run's outputs.
		FVerseBotBrainCore Second;
		FVerseBotBrainCore::FConfig C;
		C.Seed = Cfg.Seed;
		C.SelfId = FFakeVerseDuelSim::BotId;
		Second.Init(*Sim.Tier, C);
		TArray<uint8> SecondOut;
		for (const FVersePerceptFrame& F : Tape.Frames)
		{
			FVerseBotTape::AppendOutput(SecondOut, Second.Think(F, Recorder));
		}
		TestTrue(FString::Printf(TEXT("stream %d: recording run equals live run"), s), SecondOut == Tape.Outputs);

		TArray<uint8> Out1, Out2;
		bool bDiv1 = false, bDiv2 = false, bEnd1 = false, bEnd2 = false;
		VerseBotReplayTest::Replay(Tape, *Sim.Tier, Out1, bDiv1, bEnd1);
		VerseBotReplayTest::Replay(Tape, *Sim.Tier, Out2, bDiv2, bEnd2);
		TestFalse(FString::Printf(TEXT("stream %d: replay 1 did not diverge"), s), bDiv1);
		TestFalse(FString::Printf(TEXT("stream %d: replay 2 did not diverge"), s), bDiv2);
		TestTrue(FString::Printf(TEXT("stream %d: replay consumed every recorded query"), s), bEnd1 && bEnd2);
		const bool bSame = Out1 == Tape.Outputs && Out2 == Tape.Outputs;
		TestTrue(FString::Printf(TEXT("stream %d: replays bit-identical"), s), bSame);
		Identical += bSame ? 1 : 0;
		AllUs.Append(Sim.ThinkUs);
		Rows += FString::Printf(TEXT("%s    {\"stream\": %d, \"tier\": \"%s\", \"ticks\": %d, \"queryBytes\": %d, \"kills\": %d, \"identical\": %s}"),
			s == 0 ? TEXT("") : TEXT(",\n"), s, *TierId.ToString(), Tape.Frames.Num(), Tape.Queries.Num(), Sim.Kills(), bSame ? TEXT("true") : TEXT("false"));
	}
	const double P50 = VerseBotTestProof::Percentile(AllUs, 50.0);
	const double P99 = VerseBotTestProof::Percentile(AllUs, 99.0);
	const FString Json = FString::Printf(TEXT("{\n  \"test\": \"BR1\",\n  \"streams\": %d,\n  \"identical\": %d,\n  \"ticksPerStream\": %d,\n  \"thinkUsP50\": %.2f,\n  \"thinkUsP99\": %.2f,\n  \"budgetUs\": 500,\n  \"rows\": [\n%s\n  ]\n}\n"),
		Streams, Identical, TicksPerStream, P50, P99, *Rows);
	VerseBotTestProof::Write(TEXT("8.1"), TEXT("br1_replay.json"), Json);
	AddInfo(FString::Printf(TEXT("BR1: %d/%d identical; Think p50 %.1f us, p99 %.1f us"), Identical, Streams, P50, P99));
	// A8.4 cost: bot total at most 0.5 ms p99 per tick (here without perception and engine nav).
	TestTrue(TEXT("Think p99 under 500 us"), P99 <= 500.0);
	return true;
}

// F3 (counterfactual invariance, world-free part): a silent, still opponent hidden at A vs B gives
// bit-identical input frames up to the first tick at which the percept streams differ.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotCounterfactualTest, "Verse.Bot.Brain.Counterfactual", VERSE_BOT_TEST_FLAGS)

bool FVerseBotCounterfactualTest::RunTest(const FString& Parameters)
{
	int32 Passed = 0;
	for (int32 Seed = 1; Seed <= 20; ++Seed)
	{
		FFakeVerseDuelSim::FConfig A;
		A.Seed = Seed;
		A.Model = FFakeVerseDuelSim::EModel::Still;
		A.StillSpot = FVector(0.f, 900.f, 0.f);  // behind the north panel
		FFakeVerseDuelSim::FConfig B = A;
		B.StillSpot = FVector(-1800.f, -1450.f, 0.f);  // behind the south-west wall
		FFakeVerseDuelSim SimA(TEXT("hard"), A);
		FFakeVerseDuelSim SimB(TEXT("hard"), B);
		SimA.bRecordFrames = SimB.bRecordFrames = true;
		SimA.bRecordOutputs = SimB.bRecordOutputs = true;
		constexpr int32 Ticks = 60 * 60;
		int32 FirstDiffPercept = Ticks;
		for (int32 t = 0; t < Ticks; ++t)
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
				FirstDiffPercept = t;
				break;
			}
		}
		constexpr int32 FrameBytes = 4 * 4 + 4 * 3;
		const int32 Compare = FMath::Min(FirstDiffPercept, SimA.Outputs.Num() / FrameBytes);
		const bool bIdentical = FMemory::Memcmp(SimA.Outputs.GetData(), SimB.Outputs.GetData(), Compare * FrameBytes) == 0;
		TestTrue(FString::Printf(TEXT("seed %d: input frames identical for %d ticks before the first differing percept"), Seed, Compare), bIdentical);
		Passed += bIdentical ? 1 : 0;
	}
	VerseBotTestProof::Write(TEXT("8.1"), TEXT("f3_counterfactual.json"),
		FString::Printf(TEXT("{\n  \"test\": \"F3\",\n  \"seeds\": 20,\n  \"passed\": %d\n}\n"), Passed));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

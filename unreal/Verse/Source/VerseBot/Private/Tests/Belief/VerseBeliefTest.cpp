#include "Belief/VerseBeliefDebugDraw.h"
#include "Belief/VerseBeliefGrid.h"
#include "Belief/VerseBeliefMap.h"
#include "Belief/VerseBeliefNavSampler.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "Noise/VerseAudibilityTable.h"
#include "Perception/VersePerceptionModel.h"
#include "Serialization/MemoryWriter.h"
#include "Tests/Belief/VerseBeliefTestFixture.h"
#include "VerseGameplayTags.h"
#include "VerseRng.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Bot.Belief.*: the belief grid, opponent estimates and piece belief of contracts/bot.md 4
// (WP07.5-7.10) and the acceptance tests A7.3 (F3), A7.4 (tracking), A7.5 (mass), A7.6 (cost) and
// A7.7 (F7 wall_opened_unseen).

#define VERSE_BELIEF_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

using namespace VerseBotBeliefTests;

namespace VerseBotBeliefTests
{
	const FVector ObserverFeet = ColumnCentre(25, 5);
	constexpr float ObserverYaw = 90.f;

	double MinActiveMass(const FVerseBeliefGrid& Grid)
	{
		double Min = TNumericLimits<double>::Max();
		for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
		{
			if (Grid.IsActive(Cell))
			{
				Min = FMath::Min(Min, double(Grid.GetMass(Cell)));
			}
		}
		return Min;
	}

	/** A stand-in for WP08's brain: a pure function of the belief and the frame (bot.md B5). */
	FVerseInputFrame NullBrain(const FVerseBeliefMap& Map, const FVersePerceptFrame& Frame)
	{
		FVerseInputFrame Input;
		Input.ServerTimeMs = Frame.ServerTimeMs;
		const FVerseBeliefDerived& Derived = Map.GetDerived();
		const FVector To = Derived.TopCluster.Centre - Frame.Self.Location;
		Input.LookDeltaDeg = FVector2f(float(FRotator::NormalizeAxis(To.Rotation().Yaw - Frame.Self.ViewRotation.Yaw)) * 0.1f,
			Derived.SpreadM * 0.01f);
		Input.Move = FVector2f(float(To.X), float(To.Y)).GetSafeNormal() * Derived.Confidence;
		Input.Buttons = uint32(Derived.State);
		return Input;
	}

	TArray<uint8> InputBytes(const FVerseInputFrame& Input)
	{
		TArray<uint8> Bytes;
		Bytes.Append(reinterpret_cast<const uint8*>(&Input.Move), sizeof(Input.Move));
		Bytes.Append(reinterpret_cast<const uint8*>(&Input.LookDeltaDeg), sizeof(Input.LookDeltaDeg));
		Bytes.Append(reinterpret_cast<const uint8*>(&Input.Buttons), sizeof(Input.Buttons));
		Bytes.Append(reinterpret_cast<const uint8*>(&Input.Pressed), sizeof(Input.Pressed));
		Bytes.Append(reinterpret_cast<const uint8*>(&Input.ServerTimeMs), sizeof(Input.ServerTimeMs));
		return Bytes;
	}

	TArray<uint8> FrameBytes(const FVersePerceptFrame& Frame)
	{
		TArray<uint8> Bytes;
		FMemoryWriter Writer(Bytes);
		FVersePerceptFrame Copy = Frame;
		FVersePerceptFrame::StaticStruct()->SerializeItem(Writer, &Copy, nullptr);
		return Bytes;
	}

	FVerseSightPercept Sighting(const FVector& Pelvis, const FVector& Velocity)
	{
		FVerseSightPercept Sight;
		Sight.PerceptId = 1;
		Sight.PelvisLocation = Pelvis;
		Sight.Velocity = Velocity;
		Sight.VisibleMask = 0xFF;
		return Sight;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefGridBuildTest, "Verse.Bot.Belief.Grid", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefGridBuildTest::RunTest(const FString& Parameters)
{
	// WP07.5: 1 m columns, 8-neighbour adjacency that respects walls, links, gates.
	FLaneFixture Fixture;
	FVerseBeliefGrid Grid;
	Grid.Build(Fixture.Source);
	TestEqual(TEXT("one cell per column"), Grid.NumCells(), 50 * 40);
	const int32 Open = Grid.FindCell(FIntPoint(10, 10), EVerseArenaLevel::Floor);
	TestEqual(TEXT("open floor: 8 neighbours"), Grid.NumNeighbours(Open), 8);
	const int32 BelowWall = Grid.FindCell(FIntPoint(10, 19), EVerseArenaLevel::Floor);
	const int32 AboveWall = Grid.FindCell(FIntPoint(10, 20), EVerseArenaLevel::Floor);
	TArray<int32> Neighbours;
	Grid.GetNeighbours(BelowWall, Neighbours);
	TestFalse(TEXT("no step through wall A"), Neighbours.Contains(AboveWall));
	const int32 DoorBelow = Grid.FindCell(FIntPoint(24, 19), EVerseArenaLevel::Floor);
	const int32 DoorAbove = Grid.FindCell(FIntPoint(24, 20), EVerseArenaLevel::Floor);
	Grid.GetNeighbours(DoorBelow, Neighbours);
	TestTrue(TEXT("the door connects"), Neighbours.Contains(DoorAbove));
	const TArray<int32> Path = Grid.FindPath(Grid.FindCell(ObserverFeet), Grid.FindCell(ColumnCentre(10, 23)));
	TestTrue(TEXT("a path into the lane exists"), Path.Num() > 0);
	bool bThroughDoor = false;
	for (const int32 Cell : Path)
	{
		const FIntPoint C = Grid.GetCell(Cell).Column;
		bThroughDoor |= C.Y == 20 && (C.X == 24 || C.X == 25);
	}
	TestTrue(TEXT("the path goes through the door"), bThroughDoor);
	TestTrue(TEXT("uniform start sums to 1"), FMath::Abs(Grid.TotalMass() - 1.0) < 1e-6);

	// Links, levels and gates on a small two-level source.
	FVerseBeliefGridSource Small;
	for (int32 Level = 0; Level < 2; ++Level)
	{
		for (int32 X = 0; X < 4; ++X)
		{
			FVerseBeliefCellDesc& Cell = Small.Cells.AddDefaulted_GetRef();
			Cell.Column = FIntPoint(X, 0);
			Cell.Level = EVerseArenaLevel(Level);
			Cell.FloorZ = 400.f * Level;
			if (Level == 1 && X == 3)
			{
				Cell.Gate = EVerseBeliefGate::WhenStanding;
				Cell.GatePiece = 4;
			}
		}
	}
	FVerseBeliefLinkDesc& Stair = Small.Links.AddDefaulted_GetRef();
	Stair.From = 0;
	Stair.To = 4;
	Stair.TraversalS = 2.f;
	FVerseBeliefLinkDesc& Breach = Small.Links.AddDefaulted_GetRef();
	Breach.From = 3;
	Breach.To = 7;
	Breach.Gate = EVerseBeliefGate::WhenOpen;
	Breach.GatePiece = 9;
	FVerseBeliefGrid Two;
	Two.Build(Small);
	TestEqual(TEXT("8 cells on two levels"), Two.NumCells(), 8);
	Two.GetNeighbours(0, Neighbours);
	TestTrue(TEXT("stair link up"), Neighbours.Contains(4));
	Two.GetNeighbours(4, Neighbours);
	TestTrue(TEXT("stair link down"), Neighbours.Contains(0));
	Two.GetNeighbours(3, Neighbours);
	TestFalse(TEXT("closed breach link inactive"), Neighbours.Contains(7));
	TestTrue(TEXT("standing catwalk cell active"), Two.IsActive(7));
	Two.ApplyGates([](int32 Piece) { return Piece == 9; }, [](int32 Piece) { return true; });
	Two.GetNeighbours(3, Neighbours);
	TestTrue(TEXT("opened breach link active"), Neighbours.Contains(7));
	Two.ApplyGates([](int32 Piece) { return Piece == 9; }, [](int32 Piece) { return Piece != 4; });
	TestFalse(TEXT("destroyed catwalk cell inactive"), Two.IsActive(7));
	TestEqual(TEXT("inactive cell holds no mass"), Two.GetMass(7), 0.f);
	TestTrue(TEXT("mass renormalised"), FMath::Abs(Two.TotalMass() - 1.0) < 1e-6);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefMassTest, "Verse.Bot.Belief.Mass", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefMassTest::RunTest(const FString& Parameters)
{
	// A7.5: after every step the mass sums to 1 within 1e-6 and no cell is exactly 0.
	FLaneFixture Fixture;
	FVerseBeliefGrid Grid;
	Grid.Build(Fixture.Source);
	FVerseRng Rng(2024);
	double WorstSum = 0.0;
	double SmallestMass = TNumericLimits<double>::Max();
	int32 Checked = 0;
	int32 Failures = 0;
	TArray<float> Prior;
	Prior.Init(0.f, Grid.NumCells());
	for (int32 Cell = 0; Cell < Prior.Num(); ++Cell)
	{
		Prior[Cell] = Cell % 7 == 0 ? 3.f : 0.f;
	}
	for (int32 Step = 0; Step < 3000; ++Step)
	{
		const float NowS = Step * 0.1f;
		const int32 Op = Rng.RangeInt(0, 9);
		if (Step == 1500)
		{
			Grid.SetPositionPrior(Prior);
			const TArray<float> Matrix = {0.8f, 0.2f, 0.4f, 0.6f};
			Grid.SetZoneTransitionPrior(2, Matrix);
		}
		Grid.Predict(0.1f, NowS);
		const FVector Eye = ColumnCentre(Rng.RangeInt(0, 49), Rng.RangeInt(0, 39), 165.f);
		Grid.Clear(Eye, [&](int32 Cell) { return Fixture.World.Clear(Eye, Grid.GetCellCentre(Cell) + FVector(0.0, 0.0, 100.0)); }, NowS);
		switch (Op)
		{
		case 0:
			Grid.ApplySighting(ColumnCentre(Rng.RangeInt(0, 49), Rng.RangeInt(0, 39), 95.f), NowS);
			Grid.SetMomentum(FVector(Rng.Range(-450.0, 450.0), Rng.Range(-450.0, 450.0), 0.0), NowS);
			break;
		case 1:
		case 2:
		{
			FVerseHeardPercept Heard;
			Heard.Location = ColumnCentre(Rng.RangeInt(0, 49), Rng.RangeInt(0, 39));
			Heard.ErrorSdM = float(Rng.Range(0.5, 6.0));
			Heard.LevelGuess = EVerseArenaLevel::Floor;
			Grid.ApplyHeard(Heard, NowS);
			break;
		}
		case 3:
			Grid.ApplyWedge(Eye, FVector(Rng.Range(-1.0, 1.0), Rng.Range(-1.0, 1.0), 0.0), float(Rng.Range(500.0, 6000.0)), NowS);
			break;
		case 4:
			if (Rng.Chance(0.1))
			{
				Grid.ApplyOpponentDead();
				Grid.Normalise();
				TestEqual(TEXT("dead: no mass"), Grid.TotalMass(), 0.0);
				const TArray<FVector> Spawns = {ColumnCentre(5, 35), ColumnCentre(45, 35), ColumnCentre(5, 2)};
				Grid.ApplySpawnPrior(Spawns, NowS);
			}
			break;
		default:
			break;
		}
		Grid.Normalise();
		const double Sum = Grid.TotalMass();
		const double Min = MinActiveMass(Grid);
		WorstSum = FMath::Max(WorstSum, FMath::Abs(Sum - 1.0));
		SmallestMass = FMath::Min(SmallestMass, Min);
		Failures += (FMath::Abs(Sum - 1.0) > 1e-6 || !(Min > 0.0)) ? 1 : 0;
		++Checked;
	}
	TestEqual(TEXT("A7.5 every step: sum 1 within 1e-6, no cell at 0"), Failures, 0);
	SaveProof(TEXT("7.6"), TEXT("mass.json"),
		FString::Printf(TEXT("{\n  \"test\": \"A7.5 mass\",\n  \"steps\": %d,\n  \"worstAbsSumError\": %.3e,\n")
						TEXT("  \"smallestCellMass\": %.3e,\n  \"failures\": %d,\n  \"pass\": %s\n}\n"),
			Checked, WorstSum, SmallestMass, Failures, Failures == 0 ? TEXT("true") : TEXT("false")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefRulesTest, "Verse.Bot.Belief.Rules", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefRulesTest::RunTest(const FString& Parameters)
{
	// WP07.6 / 7.7: each update rule and the derived values.
	FLaneFixture Fixture;
	FVerseBeliefGrid Grid;
	Grid.Build(Fixture.Source);

	FVerseBeliefDerived Derived = Grid.ComputeDerived(0.f, false);
	TestTrue(TEXT("uniform: Lost"), Derived.State == EVerseBeliefState::Lost);
	TestTrue(TEXT("uniform: wide spread"), Derived.SpreadM > 10.f);

	const FVector Seen = ColumnCentre(10, 10, 95.f);
	Grid.ApplySighting(Seen, 1.f);
	Grid.Normalise();
	Derived = Grid.ComputeDerived(1.f, true);
	TestTrue(TEXT("sighting: Known"), Derived.State == EVerseBeliefState::Known);
	TestTrue(TEXT("sighting: TopCluster at the sighting"), FVector::Dist2D(Derived.TopCluster.Centre, Seen) < 50.0);
	TestTrue(TEXT("sighting: confidence > 0.95"), Derived.Confidence > 0.95f);
	TestTrue(TEXT("sighting: support seen, age 0"), Derived.SupportKind == EVerseBeliefSupport::Seen && Derived.SupportAgeS < 1e-3f);
	TestTrue(TEXT("sighting: spread under 1 m"), Derived.SpreadM < 1.f);
	Derived = Grid.ComputeDerived(1.f, false);
	TestTrue(TEXT("sighting without sight now: Tracked"), Derived.State == EVerseBeliefState::Tracked);

	// Predict spreads mass but keeps the cluster; support ages.
	for (int32 Step = 0; Step < 10; ++Step)
	{
		Grid.Predict(0.1f, 1.f + 0.1f * Step);
		Grid.Normalise();
	}
	Derived = Grid.ComputeDerived(2.f, false);
	TestTrue(TEXT("predict: spread grows"), Derived.SpreadM > 1.f);
	TestTrue(TEXT("predict: support age 1 s"), FMath::Abs(Derived.SupportAgeS - 1.f) < 1e-3f);

	// Clear: a visible cell loses 95 % of its mass at short range.
	const int32 Centre = Grid.FindCell(Seen);
	const float Before = Grid.GetMass(Centre);
	Grid.Clear(ColumnCentre(10, 5, 165.f), [Centre](int32 Cell) { return Cell == Centre; }, 2.f);
	TestTrue(TEXT("clear multiplies by 1 - 0.95"), FMath::IsNearlyEqual(Grid.GetMass(Centre), Before * 0.05f, Before * 1e-4f));
	TestEqual(TEXT("clear sets LastCleared"), Grid.GetLastClearedS(Centre), 2.f);
	Grid.Normalise();

	// Heard: mass moves toward the heard point on the guessed level.
	Grid.ResetUniform();
	FVerseHeardPercept Heard;
	Heard.Location = ColumnCentre(40, 10);
	Heard.ErrorSdM = 2.f;
	Heard.LevelGuess = EVerseArenaLevel::Floor;
	Heard.Noise = VerseTags::Noise_Shot;
	Grid.ApplyHeard(Heard, 3.f);
	Grid.Normalise();
	Derived = Grid.ComputeDerived(3.f, false);
	TestTrue(TEXT("heard: cluster near the heard point"), FVector::Dist2D(Derived.TopCluster.Centre, Heard.Location) < 150.0);
	TestTrue(TEXT("heard: support heard"), Derived.SupportKind == EVerseBeliefSupport::Heard);

	// Wedge: mass along the back-traced bolt line, cut at the opaque distance.
	Grid.ResetUniform();
	Grid.ApplyWedge(ColumnCentre(5, 5), FVector(1.0, 0.0, 0.0), 1500.f, 4.f);
	Grid.Normalise();
	const float OnLine = Grid.GetMass(Grid.FindCell(FIntPoint(15, 5), EVerseArenaLevel::Floor));
	const float OffLine = Grid.GetMass(Grid.FindCell(FIntPoint(15, 15), EVerseArenaLevel::Floor));
	const float Beyond = Grid.GetMass(Grid.FindCell(FIntPoint(30, 5), EVerseArenaLevel::Floor));
	TestTrue(TEXT("wedge: on the line > off the line"), OnLine > 20.f * OffLine);
	TestTrue(TEXT("wedge: cut at the first opaque piece"), OnLine > 20.f * Beyond);

	// Kill feed: dead, then the spawn prior over the top 3 points 0.5 / 0.3 / 0.2.
	Grid.ApplyOpponentDead();
	Grid.Normalise();
	TestTrue(TEXT("dead state"), Grid.ComputeDerived(5.f, false).State == EVerseBeliefState::Dead);
	const TArray<FVector> Spawns = {ColumnCentre(5, 35), ColumnCentre(45, 35), ColumnCentre(5, 2), ColumnCentre(45, 2)};
	Grid.ApplySpawnPrior(Spawns, 6.f);
	Grid.Normalise();
	auto MassNear = [&Grid](const FVector& Point) {
		double Sum = 0.0;
		for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
		{
			Sum += FVector::Dist2D(Grid.GetCellCentre(Cell), Point) <= 500.0 ? Grid.GetMass(Cell) : 0.f;
		}
		return Sum;
	};
	TestTrue(TEXT("spawn 1 about 0.5"), FMath::Abs(MassNear(Spawns[0]) - 0.5) < 0.03);
	TestTrue(TEXT("spawn 2 about 0.3"), FMath::Abs(MassNear(Spawns[1]) - 0.3) < 0.03);
	TestTrue(TEXT("spawn 3 about 0.2"), FMath::Abs(MassNear(Spawns[2]) - 0.2) < 0.03);
	TestTrue(TEXT("spawn 4 gets only the prior"), MassNear(Spawns[3]) < 0.01);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefMapTest, "Verse.Bot.Belief.Map", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefMapTest::RunTest(const FString& Parameters)
{
	// The map: 10 Hz steps, at once on a positive percept; estimates; spawn ranking; own death.
	FLaneFixture Fixture;
	FVerseBeliefMap Map;
	Map.Initialize(Fixture.Source, Fixture.Config(), Fixture.BeliefWorld());
	const FVerseBeliefWorld World = Fixture.BeliefWorld();
	uint32 NowMs = 1000;
	int32 Steps = 0;
	for (int32 Tick = 0; Tick < 60; ++Tick)
	{
		NowMs += 17;
		Steps += Map.ApplyFrame(SelfFrame(NowMs, ObserverFeet, ObserverYaw), World) ? 1 : 0;
	}
	TestTrue(TEXT("about 10 steps per second"), Steps >= 9 && Steps <= 11);
	FVersePerceptFrame Frame = SelfFrame(NowMs + 1, ObserverFeet, ObserverYaw);
	Frame.Sightings.Add(Sighting(ColumnCentre(25, 15, 95.f), FVector::ZeroVector));
	TestTrue(TEXT("a sighting steps at once"), Map.ApplyFrame(Frame, World));
	TestTrue(TEXT("Known after a sighting"), Map.GetDerived().State == EVerseBeliefState::Known);

	// Cleared view: the visible hall in front of the observer holds almost nothing after a while.
	Map.OnOwnDeath(2.f);
	for (int32 Tick = 0; Tick < 120; ++Tick)
	{
		NowMs += 17;
		Map.ApplyFrame(SelfFrame(NowMs, ObserverFeet, ObserverYaw), World);
	}
	double Visible = 0.0;
	double Lane = 0.0;
	for (int32 Cell = 0; Cell < Map.GetGrid().NumCells(); ++Cell)
	{
		const FIntPoint C = Map.GetGrid().GetCell(Cell).Column;
		if (C.Y >= 8 && C.Y <= 18 && C.X >= 20 && C.X <= 30)
		{
			Visible += Map.GetGrid().GetMass(Cell);
		}
		if (C.Y >= 21 && C.Y <= 25 && (C.X < 20 || C.X > 30))
		{
			Lane += Map.GetGrid().GetMass(Cell);
		}
	}
	TestTrue(TEXT("visible area cleared"), Visible < 0.02);
	TestTrue(TEXT("hidden lane keeps mass"), Lane > 0.1);

	// Estimates: shots heard lower the ammo estimate; a heard reload refills; hit markers lower health.
	FVersePerceptFrame Shots = SelfFrame(NowMs += 200, ObserverFeet, ObserverYaw);
	for (int32 Shot = 0; Shot < 12; ++Shot)
	{
		FVerseHeardPercept& Heard = Shots.Heard.AddDefaulted_GetRef();
		Heard.Noise = VerseTags::Noise_Shot;
		Heard.Location = ColumnCentre(10, 23);
		Heard.ErrorSdM = 2.f;
	}
	FVerseHudEvent& Marker = Shots.Hud.AddDefaulted_GetRef();
	Marker.Kind = EVerseHudEventKind::HitMarker;
	Marker.KillerId = SelfId;
	Marker.VictimId = OpponentId;
	Map.ApplyFrame(Shots, World);
	TestEqual(TEXT("ammo estimate after 12 shots"), Map.GetOpponent().EstimatedAmmo(), 18);
	TestEqual(TEXT("health estimate after one hit"), Map.GetOpponent().EstimatedHealth(NowMs / 1000.f), 75.f);
	FVersePerceptFrame Reload = SelfFrame(NowMs += 200, ObserverFeet, ObserverYaw);
	FVerseHeardPercept& Heard = Reload.Heard.AddDefaulted_GetRef();
	Heard.Noise = VerseTags::Noise_Reload;
	Heard.Location = ColumnCentre(10, 23);
	Heard.ErrorSdM = 2.f;
	Map.ApplyFrame(Reload, World);
	TestEqual(TEXT("heard reload refills the estimate"), Map.GetOpponent().EstimatedAmmo(), 30);
	TestTrue(TEXT("heard reload flag for flank and finisher queries"), Map.GetOpponent().bHeardReload);

	// Spawn rule: out of sight first, then farthest.
	const TArray<FVector> Ranked = Map.RankSpawnPoints(ObserverFeet + FVector(0.0, 0.0, 165.0), &Fixture.World);
	TestEqual(TEXT("hidden far spawn first"), Ranked[0], ColumnCentre(47, 37));
	TestEqual(TEXT("hidden spawn second"), Ranked[1], ColumnCentre(5, 35));

	// Kill feed through the map: opponent dead, then respawned.
	FVersePerceptFrame Kill = SelfFrame(NowMs += 200, ObserverFeet, ObserverYaw);
	FVerseHudEvent& Dead = Kill.Hud.AddDefaulted_GetRef();
	Dead.Kind = EVerseHudEventKind::Kill;
	Dead.KillerId = SelfId;
	Dead.VictimId = OpponentId;
	Map.ApplyFrame(Kill, World);
	TestTrue(TEXT("opponent dead"), Map.GetDerived().State == EVerseBeliefState::Dead);
	FVersePerceptFrame Respawn = SelfFrame(NowMs += 3000, ObserverFeet, ObserverYaw);
	FVerseHudEvent& Back = Respawn.Hud.AddDefaulted_GetRef();
	Back.Kind = EVerseHudEventKind::OpponentRespawned;
	Back.VictimId = OpponentId;
	Map.ApplyFrame(Respawn, World);
	TestTrue(TEXT("respawn: belief at the best hidden spawn"),
		FVector::Dist2D(Map.GetDerived().TopCluster.Centre, ColumnCentre(47, 37)) < 300.0);
	TestEqual(TEXT("respawn resets the health estimate"), Map.GetOpponent().EstimatedHealth(NowMs / 1000.f), 100.f);
	return true;
}

namespace VerseBotBeliefTests
{
	/** How the hidden opponent moves after it leaves the observer's view (A7.4 and its variants). */
	enum class ETrackingMove : uint8
	{
		/** Runs into the lane and along it (the A7.4 case). */
		Straight,
		/** Stops 0.5 s after it was last seen. */
		Stop,
		/** Turns back 1 s after it was last seen. */
		TurnBack
	};

	struct FTrackingResult
	{
		double ContainRate = 0.0;
		double MeanErrorM = 0.0;
		double MedianErrorM = 0.0;
	};

	/**
	 * Trials of a sighting at the lane door, then hidden movement at 4.5 m/s for 3 s: the share in
	 * which the TopCluster (3 m disc) contains the true position. Whenever the truth is in the
	 * observer's cone with line of sight it is sighted again, as the perception service would.
	 */
	FTrackingResult RunTrackingTrials(const FLaneFixture& Fixture, ETrackingMove Move, const FVerseBeliefTuning& Tuning,
		int32 Trials, bool bSaveShots)
	{
		const FVerseBeliefWorld World = Fixture.BeliefWorld();
		const FVector Eye = ObserverFeet + FVector(0.0, 0.0, 165.0);
		const FVersePerceptionModel::FCone Cone = FVersePerceptionModel::ConeFor(false, 70.f);
		const FRotator View(0.f, ObserverYaw, 0.f);
		int32 Hits = 0;
		double SumError = 0.0;
		TArray<double> Errors;
		for (int32 Trial = 0; Trial < Trials; ++Trial)
		{
			FVerseRng Rng(uint64(Trial) + 1);
			FVerseBeliefMap Map;
			Map.Initialize(Fixture.Source, Fixture.Config(), World, Tuning);
			const double Side = Rng.Chance(0.5) ? 1.0 : -1.0;
			const double LaneY = 2300.0 + Rng.Range(-150.0, 250.0);
			FVector Truth(2500.0 + Rng.Range(-80.0, 80.0), 2060.0, 95.0);
			const FVector Waypoints[2] = {FVector(2500.0 + Side * 150.0, LaneY, 95.0), FVector(2500.0 + Side * 3000.0, LaneY, 95.0)};
			const FVector BackTarget(2500.0 - Side * 3000.0, LaneY, 95.0);
			int32 Waypoint = 0;
			uint32 NowMs = 1000;
			double HiddenS = 0.0;
			bool bTurned = false;
			bool bFirst = true;
			const bool bShots = bSaveShots && Trial == 0;
			double NextShotS = 0.0;
			for (int32 Tick = 0; Tick < 600 && HiddenS < 3.0; ++Tick)
			{
				FVector Velocity = FVector::ZeroVector;
				if (!bFirst)
				{
					if (Waypoint == 0 && FVector::Dist2D(Truth, Waypoints[0]) < 50.0)
					{
						Waypoint = 1;
					}
					bTurned |= Move == ETrackingMove::TurnBack && HiddenS > 1.0;
					const bool bStopped = Move == ETrackingMove::Stop && HiddenS > 0.5;
					const FVector Goal = bTurned ? BackTarget : Waypoints[Waypoint];
					Velocity = bStopped ? FVector::ZeroVector : (Goal - Truth).GetSafeNormal2D() * 450.0;
					Truth += Velocity * (1.0 / 60.0);
					NowMs += 17;
				}
				else
				{
					Velocity = (Waypoints[0] - Truth).GetSafeNormal2D() * 450.0;
				}
				FVersePerceptFrame Frame = SelfFrame(NowMs, ObserverFeet, ObserverYaw);
				bool bVisible = bFirst;
				for (const double Height : {75.0, 0.0})
				{
					const FVector Point = Truth + FVector(0.0, 0.0, Height);
					bVisible |= FVersePerceptionModel::Classify(Eye, View, Cone, Point) == FVersePerceptionModel::EConeZone::Inside &&
						Fixture.World.Clear(Eye, Point);
				}
				if (bVisible)
				{
					Frame.Sightings.Add(Sighting(Truth, Velocity));
					HiddenS = 0.0;
				}
				else
				{
					HiddenS += 1.0 / 60.0;
				}
				Map.ApplyFrame(Frame, World);
				if (bShots)
				{
					const double SinceSighting = (NowMs - 1000) / 1000.0;
					if (SinceSighting >= NextShotS)
					{
						const TCHAR* Shot = NextShotS == 0.0 ? TEXT("heatmap_sighting.png")
															: (NextShotS == 1.0 ? TEXT("heatmap_plus1s.png") : TEXT("heatmap_plus3s.png"));
						NextShotS = NextShotS == 0.0 ? 1.0 : (NextShotS == 1.0 ? 3.0 : 1e9);
						const FVector Marks[1] = {Truth};
						FVerseBeliefDebugDraw::SavePng(ProofDir(TEXT("7.10")) / Shot, Map.GetGrid(), Map.GetDerived(),
							EVerseArenaLevel::Floor, 12, Marks);
					}
				}
				bFirst = false;
			}
			if (bShots)
			{
				const FVector Marks[1] = {Truth};
				FVerseBeliefDebugDraw::SavePng(ProofDir(TEXT("7.10")) / TEXT("heatmap_hidden3s.png"), Map.GetGrid(), Map.GetDerived(),
					EVerseArenaLevel::Floor, 12, Marks);
			}
			const double Error = FVector::Dist2D(Map.GetDerived().TopCluster.Centre, Truth);
			Errors.Add(Error);
			SumError += Error;
			Hits += Error <= Map.GetGrid().GetTuning().ClusterRadiusCm ? 1 : 0;
		}
		Errors.Sort();
		FTrackingResult Result;
		Result.ContainRate = Trials > 0 ? double(Hits) / Trials : 0.0;
		Result.MeanErrorM = Trials > 0 ? SumError / Trials / 100.0 : 0.0;
		Result.MedianErrorM = Trials > 0 ? Errors[Trials / 2] / 100.0 : 0.0;
		return Result;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefTrackingTest, "Verse.Bot.Belief.Tracking", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefTrackingTest::RunTest(const FString& Parameters)
{
	// A7.4: a sighting at the lane door, then 3 s hidden movement at 4.5 m/s: the TopCluster
	// contains the true position in at least 70 % of 200 trials. The variants (the opponent stops
	// or turns back after the last sighting) and the same trials under the bot.md 4.2 rules alone
	// (no momentum term) are reported for the contract-change review; they are not gated.
	FLaneFixture Fixture;
	const FVerseBeliefTuning WithMomentum = FVerseBeliefTuning();
	FVerseBeliefTuning ContractOnly;
	ContractOnly.MomentumMaxFraction = 0.f;

	const FTrackingResult Straight = RunTrackingTrials(Fixture, ETrackingMove::Straight, WithMomentum, 200, true);
	const FTrackingResult StraightContract = RunTrackingTrials(Fixture, ETrackingMove::Straight, ContractOnly, 200, false);
	const FTrackingResult Stop = RunTrackingTrials(Fixture, ETrackingMove::Stop, WithMomentum, 100, false);
	const FTrackingResult StopContract = RunTrackingTrials(Fixture, ETrackingMove::Stop, ContractOnly, 100, false);
	const FTrackingResult Turn = RunTrackingTrials(Fixture, ETrackingMove::TurnBack, WithMomentum, 100, false);
	const FTrackingResult TurnContract = RunTrackingTrials(Fixture, ETrackingMove::TurnBack, ContractOnly, 100, false);

	AddInfo(FString::Printf(TEXT("contain rate with momentum / contract rules only: straight %.1f / %.1f %%, stop %.1f / %.1f %%, turn back %.1f / %.1f %%"),
		Straight.ContainRate * 100.0, StraightContract.ContainRate * 100.0, Stop.ContainRate * 100.0, StopContract.ContainRate * 100.0,
		Turn.ContainRate * 100.0, TurnContract.ContainRate * 100.0));
	TestTrue(FString::Printf(TEXT("A7.4 TopCluster contains the truth in %.1f %% of trials (>= 70 %%)"), Straight.ContainRate * 100.0),
		Straight.ContainRate >= 0.70);
	SaveProof(TEXT("7.6"), TEXT("tracking.json"),
		FString::Printf(TEXT("{\n  \"test\": \"A7.4 belief tracking\",\n  \"trials\": 200,\n  \"hidden_s\": 3.0,\n")
						TEXT("  \"speed_m_s\": 4.5,\n  \"containRate\": %.4f,\n  \"meanErrorM\": %.3f,\n  \"medianErrorM\": %.3f,\n")
						TEXT("  \"momentumTermIsAContractChangeProposal\": true,\n")
						TEXT("  \"containRateContractRulesOnly\": %.4f,\n")
						TEXT("  \"variants\": {\"stopAfter0_5s\": {\"trials\": 100, \"withMomentum\": %.4f, \"contractRulesOnly\": %.4f},\n")
						TEXT("               \"turnBackAfter1s\": {\"trials\": 100, \"withMomentum\": %.4f, \"contractRulesOnly\": %.4f}},\n")
						TEXT("  \"pass\": %s\n}\n"),
			Straight.ContainRate, Straight.MeanErrorM, Straight.MedianErrorM, StraightContract.ContainRate, Stop.ContainRate,
			StopContract.ContainRate, Turn.ContainRate, TurnContract.ContainRate, Straight.ContainRate >= 0.70 ? TEXT("true") : TEXT("false")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefPlateauTest, "Verse.Bot.Belief.Plateau", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefPlateauTest::RunTest(const FString& Parameters)
{
	// bot.md 4.3: TopCluster is the 3 m disc with the most mass anywhere. A broad heard percept
	// (sd 14 m) makes a plateau of far more than a few hundred cells within a factor of 2 of the
	// peak; the best disc lies in the high cell-index region and must still be found there.
	FLaneFixture Fixture;
	FVerseBeliefGrid Grid;
	Grid.Build(Fixture.Source);
	Grid.ResetUniform();
	FVerseHeardPercept Heard;
	Heard.Location = ColumnCentre(38, 14);
	Heard.ErrorSdM = 14.f;
	Heard.LevelGuess = EVerseArenaLevel::Floor;
	Heard.Noise = VerseTags::Noise_Shot;
	Grid.ApplyHeard(Heard, 1.f);
	Grid.Normalise();
	int32 Plateau = 0;
	float Peak = 0.f;
	for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
	{
		Peak = FMath::Max(Peak, Grid.GetMass(Cell));
	}
	for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
	{
		Plateau += Grid.GetMass(Cell) >= 0.5f * Peak ? 1 : 0;
	}
	TestTrue(FString::Printf(TEXT("plateau of %d cells within 2x of the peak (> 384)"), Plateau), Plateau > 384);
	const FVerseBeliefDerived Derived = Grid.ComputeDerived(1.f, false);
	// Brute force: the disc sum of every active cell.
	double BestMass = -1.0;
	int32 BestCell = INDEX_NONE;
	for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
	{
		if (!Grid.IsActive(Cell))
		{
			continue;
		}
		double Mass = 0.0;
		for (int32 Other = 0; Other < Grid.NumCells(); ++Other)
		{
			if (Grid.IsActive(Other) && FVector::DistSquared2D(Grid.GetCellCentre(Cell), Grid.GetCellCentre(Other)) <= 300.0 * 300.0 + 1.0)
			{
				Mass += Grid.GetMass(Other);
			}
		}
		if (Mass > BestMass + 1e-9)
		{
			BestMass = Mass;
			BestCell = Cell;
		}
	}
	TestTrue(TEXT("TopCluster disc holds the most mass (brute force)"), FMath::Abs(Derived.TopCluster.Mass - BestMass) <= 1e-5);
	TestTrue(TEXT("TopCluster in the high-index region near the heard point"),
		FVector::Dist2D(Derived.TopCluster.Centre, Heard.Location) < 200.0 && Grid.GetCell(Derived.TopCluster.CentreCell).Column.X >= 33);
	AddInfo(FString::Printf(TEXT("plateau %d cells, best disc mass %.5f (brute force cell %d, grid cell %d)"), Plateau, BestMass, BestCell,
		Derived.TopCluster.CentreCell));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefF3Test, "Verse.Bot.Belief.F3", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefF3Test::RunTest(const FString& Parameters)
{
	// A7.3 / F3 counterfactual invariance: a silent, still opponent at hidden spot A vs B. For 20
	// seeds the percept frames, the belief and the (null) brain's input frames are bit-identical up
	// to the first tick at which the percept streams differ (the opponent fires at tick 300).
	FLaneFixture Fixture;
	UVerseAudibilityTable* Audibility = NewObject<UVerseAudibilityTable>();
	Audibility->AddToRoot();
	const FVerseBeliefWorld BeliefWorld = Fixture.BeliefWorld();
	FVersePerceptionWorld PerceptionWorld;
	const FFakeVerseBeliefWorld* Geometry = &Fixture.World;
	PerceptionWorld.TestSight = [Geometry](const FVector& A, const FVector& B) { return Geometry->Clear(A, B); };
	PerceptionWorld.Audibility = Audibility;

	constexpr int32 Seeds = 20;
	constexpr int32 Ticks = 420;
	constexpr int32 FireTick = 300;
	int32 Passed = 0;
	FString Detail;
	for (int32 Seed = 0; Seed < Seeds; ++Seed)
	{
		struct FRun
		{
			TArray<TArray<uint8>> Frames;
			TArray<TArray<uint8>> Inputs;
			TArray<uint32> Mass;
		};
		auto Run = [&](const FVector& Spot) {
			FRun Out;
			FVersePerceptionModel Model;
			FVersePerceptionProfile Profile;
			Profile.Seed = 1000 + Seed;
			Model.AddObserver(SelfId, Profile);
			FVerseBeliefMap Map;
			Map.Initialize(Fixture.Source, Fixture.Config(), BeliefWorld);
			FVersePerceptionBody Target;
			Target.PlayerId = OpponentId;
			Target.Pelvis = Spot;
			Target.SetSamplePointsFromStance();
			const FVersePerceptionBody Bodies[1] = {Target};
			FVerseRng Sweep(uint64(Seed) * 7 + 3);
			const float StartYaw = float(Sweep.Range(0.0, 360.0));
			uint32 NowMs = 1000;
			for (int32 Tick = 0; Tick < Ticks; ++Tick)
			{
				NowMs += 17;
				if (Tick == FireTick)
				{
					FVerseNoiseEvent Shot;
					Shot.Noise = VerseTags::Noise_Shot;
					Shot.SourceId = OpponentId;
					Shot.Location = Spot;
					Shot.ServerTime = NowMs / 1000.f;
					Model.OnNoise(Shot);
				}
				FVersePerceptionObserverInput Input;
				Input.Self = SelfFrame(NowMs, ObserverFeet, StartYaw + Tick * 0.75f).Self;
				const FVersePerceptFrame Frame = Model.BuildFrame(SelfId, Input, Bodies, PerceptionWorld, NowMs, 1.f / 60.f);
				Map.ApplyFrame(Frame, BeliefWorld);
				Out.Frames.Add(FrameBytes(Frame));
				Out.Inputs.Add(InputBytes(NullBrain(Map, Frame)));
				Out.Mass.Add(Map.GetGrid().HashMass());
			}
			return Out;
		};
		const FRun A = Run(ColumnCentre(10, 23, 95.f));
		const FRun B = Run(ColumnCentre(40, 23, 95.f));
		int32 FirstPerceptDiff = Ticks;
		int32 FirstInputDiff = Ticks;
		int32 FirstMassDiff = Ticks;
		for (int32 Tick = 0; Tick < Ticks; ++Tick)
		{
			if (FirstPerceptDiff == Ticks && A.Frames[Tick] != B.Frames[Tick])
			{
				FirstPerceptDiff = Tick;
			}
			if (FirstInputDiff == Ticks && A.Inputs[Tick] != B.Inputs[Tick])
			{
				FirstInputDiff = Tick;
			}
			if (FirstMassDiff == Ticks && A.Mass[Tick] != B.Mass[Tick])
			{
				FirstMassDiff = Tick;
			}
		}
		const bool bOk = FirstPerceptDiff == FireTick && FirstInputDiff >= FirstPerceptDiff && FirstMassDiff >= FirstPerceptDiff;
		Passed += bOk ? 1 : 0;
		Detail += FString::Printf(TEXT("%s    {\"seed\": %d, \"firstPerceptDiff\": %d, \"firstInputDiff\": %d, \"firstMassDiff\": %d}"),
			Seed == 0 ? TEXT("") : TEXT(",\n"), Seed, FirstPerceptDiff, FirstInputDiff, FirstMassDiff);
		if (!bOk)
		{
			AddError(FString::Printf(TEXT("seed %d: percept diff at %d, input diff at %d, mass diff at %d"), Seed,
				FirstPerceptDiff, FirstInputDiff, FirstMassDiff));
		}
	}
	Audibility->RemoveFromRoot();
	TestEqual(TEXT("A7.3 all 20 seeds invariant up to the first differing percept"), Passed, Seeds);
	SaveProof(TEXT("7.9"), TEXT("f3_counterfactual.json"),
		FString::Printf(TEXT("{\n  \"test\": \"F3 counterfactual invariance (A7.3)\",\n  \"seeds\": %d,\n  \"ticks\": %d,\n")
						TEXT("  \"fireTick\": %d,\n  \"passed\": %d,\n  \"runs\": [\n%s\n  ],\n  \"pass\": %s\n}\n"),
			Seeds, Ticks, FireTick, Passed, *Detail, Passed == Seeds ? TEXT("true") : TEXT("false")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefReplayTest, "Verse.Bot.Belief.Replay", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefReplayTest::RunTest(const FString& Parameters)
{
	// B5 for the belief layer: the same frame stream twice gives bit-identical mass every step.
	FLaneFixture Fixture;
	const FVerseBeliefWorld World = Fixture.BeliefWorld();
	TArray<FVersePerceptFrame> Stream;
	FVerseRng Rng(77);
	uint32 NowMs = 1000;
	for (int32 Tick = 0; Tick < 900; ++Tick)
	{
		NowMs += 17;
		FVersePerceptFrame Frame = SelfFrame(NowMs, ObserverFeet, float(Tick % 360));
		const int32 Roll = Rng.RangeInt(0, 99);
		if (Roll < 3)
		{
			Frame.Sightings.Add(Sighting(ColumnCentre(Rng.RangeInt(0, 49), Rng.RangeInt(0, 39), 95.f),
				FVector(Rng.Range(-400.0, 400.0), Rng.Range(-400.0, 400.0), 0.0)));
		}
		else if (Roll < 8)
		{
			FVerseHeardPercept& Heard = Frame.Heard.AddDefaulted_GetRef();
			Heard.Noise = VerseTags::Noise_Footstep_Run;
			Heard.Location = ColumnCentre(Rng.RangeInt(0, 49), Rng.RangeInt(0, 39));
			Heard.ErrorSdM = float(Rng.Range(1.0, 4.0));
		}
		Stream.Add(Frame);
	}
	auto Play = [&]() {
		TArray<uint32> Hashes;
		FVerseBeliefMap Map;
		Map.Initialize(Fixture.Source, Fixture.Config(), World);
		for (const FVersePerceptFrame& Frame : Stream)
		{
			Map.ApplyFrame(Frame, World);
			Hashes.Add(Map.GetGrid().HashMass());
		}
		return Hashes;
	};
	TestTrue(TEXT("replay: identical mass every step"), Play() == Play());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefPiecesTest, "Verse.Bot.Belief.Pieces", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefPiecesTest::RunTest(const FString& Parameters)
{
	// WP07.8: piece belief from sight, sound and own actions only; cover dependency sets.
	FFakeVerseBeliefWorld World;
	World.AddPiece(1, FVector(1000.0, -200.0, 0.0), FVector(1020.0, 200.0, 300.0), EVersePenetrationMaterial::SheetMetal);
	World.AddPiece(2, FVector(-1020.0, -200.0, 0.0), FVector(-1000.0, 200.0, 300.0), EVersePenetrationMaterial::ContainerWall);
	World.AddPiece(3, FVector(2000.0, -200.0, 0.0), FVector(2050.0, 200.0, 300.0), EVersePenetrationMaterial::Concrete);
	FVersePieceBelief Belief;
	Belief.Initialize(World, FBox(FVector(-5000.0), FVector(5000.0)));
	TestEqual(TEXT("layout of 3 pieces"), Belief.Num(), 3);
	TestEqual(TEXT("layout read no state"), World.StateReads.Num(), 0);

	// Truth changes everywhere; the bot looks at +X and sees piece 1 only (3 is behind 1).
	World.Pieces[0].State = EVersePieceState::Holed;
	World.Pieces[1].State = EVersePieceState::Breached;
	World.Pieces[2].State = EVersePieceState::Damaged;
	Belief.RegisterCover(10, TArray<uint16>{2});
	Belief.RegisterCover(11, TArray<uint16>{1});
	const FVector Eye(0.0, 0.0, 165.0);
	Belief.ObserveSight(Eye, FRotator(0.f, 0.f, 0.f), World, World, 1.f);
	TestTrue(TEXT("seen piece: true state"), Belief.GetBelievedState(1) == EVersePieceState::Holed);
	TestTrue(TEXT("unseen piece behind the bot: still intact"), Belief.GetBelievedState(2) == EVersePieceState::Intact);
	TestTrue(TEXT("occluded piece: still intact"), Belief.GetBelievedState(3) == EVersePieceState::Intact);
	bool bOnlySeen = World.StateReads.Num() > 0;
	for (const uint16 Read : World.StateReads)
	{
		bOnlySeen &= Read == 1;
	}
	TestTrue(TEXT("GetPieceState only for the seen piece (F1, DR6)"), bOnlySeen);
	TestTrue(TEXT("cover on piece 1 dirty"), Belief.ConsumeDirtyCover() == TArray<int32>{11});

	// A heard fracture near piece 2: changed, state unknown; its cover is rescored.
	FVerseHeardPercept Fracture;
	Fracture.Noise = VerseTags::Noise_Fracture;
	Fracture.Location = FVector(-1100.0, 50.0, 0.0);
	Fracture.ErrorSdM = 1.f;
	Belief.OnHeardFracture(Fracture, 2.f);
	TestTrue(TEXT("heard fracture: changed, state unknown"), Belief.Find(2)->bChangedUnknown);
	TestTrue(TEXT("heard fracture: believed state kept"), Belief.GetBelievedState(2) == EVersePieceState::Intact);
	TestFalse(TEXT("heard fracture: not an opening"), Belief.IsBelievedOpen(2));
	TestTrue(TEXT("cover on piece 2 dirty"), Belief.ConsumeDirtyCover() == TArray<int32>{10});

	// Turning around: piece 2 seen, Breached.
	World.StateReads.Reset();
	Belief.ObserveSight(Eye, FRotator(0.f, 180.f, 0.f), World, World, 3.f);
	TestTrue(TEXT("seen after turning: breached"), Belief.IsBelievedOpen(2));
	TestFalse(TEXT("flag cleared once seen"), Belief.Find(2)->bChangedUnknown);

	// Own action and the full reset.
	Belief.OnOwnAction(3, EVersePieceState::Destroyed, 4.f);
	TestFalse(TEXT("own action: destroyed"), Belief.IsBelievedStanding(3));
	Belief.ResetAll();
	TestTrue(TEXT("reset: all intact"), Belief.GetBelievedState(1) == EVersePieceState::Intact &&
		Belief.GetBelievedState(2) == EVersePieceState::Intact && Belief.GetBelievedState(3) == EVersePieceState::Intact);

	// Opaque distance for the hurt wedge: concrete stops at 20 m, sheet metal does not.
	const float Opaque = Belief.OpaqueDistance(FVector(0.0, 0.0, 100.0), FVector(1.0, 0.0, 0.0), 5000.f);
	TestTrue(TEXT("opaque at the concrete piece"), FMath::IsNearlyEqual(Opaque, 2000.f, 5.f));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefF7Test, "Verse.Bot.Belief.F7", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefF7Test::RunTest(const FString& Parameters)
{
	// A7.7 / F7 wall_opened_unseen: a wall between two rooms is breached out of sight and earshot.
	// No believed path uses the opening and no mass flows through it until the bot sees it.
	FFakeVerseBeliefWorld World;
	World.AddPiece(7, FVector(1000.0, 0.0, 0.0), FVector(1100.0, 1000.0, 300.0), EVersePenetrationMaterial::SheetMetal);
	FVerseBeliefGridSource Source;
	Source.Origin = FVector2D(50.0, 50.0);
	for (int32 X = 0; X < 20; ++X)
	{
		for (int32 Y = 0; Y < 10; ++Y)
		{
			FVerseBeliefCellDesc& Cell = Source.Cells.AddDefaulted_GetRef();
			Cell.Column = FIntPoint(X, Y);
			if (X == 10)
			{
				// The wall's column: walkable only through the opening of a breached wall.
				Cell.Gate = EVerseBeliefGate::WhenOpen;
				Cell.GatePiece = 7;
			}
		}
	}
	FVerseBeliefMapConfig Config;
	Config.SelfPlayerId = SelfId;
	Config.ArenaBox = FBox(FVector(-100.0, -100.0, -100.0), FVector(2100.0, 1100.0, 500.0));
	Config.MaxCellSightTestsPerStep = 100000;
	Config.MaxPieceSightTestsPerStep = 100000;
	FVerseBeliefWorld BeliefWorld;
	BeliefWorld.Sight = &World;
	BeliefWorld.Pieces = &World;
	FVerseBeliefMap Map;
	Map.Initialize(Source, Config, BeliefWorld);

	const FVector Feet = ColumnCentre(2, 5);
	const int32 RoomA = Map.GetGrid().FindCell(ColumnCentre(4, 5));
	const int32 RoomB = Map.GetGrid().FindCell(ColumnCentre(15, 5));
	TestTrue(TEXT("no path before the breach"), Map.GetGrid().FindPath(RoomA, RoomB).Num() == 0);

	// Breached out of sight (the bot looks away, -X) and out of earshot (no fracture percept).
	World.Pieces[0].State = EVersePieceState::Breached;
	uint32 NowMs = 1000;
	int32 PlansThroughOpening = 0;
	for (int32 Tick = 0; Tick < 600; ++Tick)
	{
		NowMs += 17;
		Map.ApplyFrame(SelfFrame(NowMs, Feet, 180.f), BeliefWorld);
		PlansThroughOpening += Map.GetGrid().FindPath(RoomA, RoomB).Num() > 0 ? 1 : 0;
	}
	TestEqual(TEXT("A7.7 no plan uses the breach before it is perceived"), PlansThroughOpening, 0);
	TestTrue(TEXT("belief still intact"), Map.GetPieces().GetBelievedState(7) == EVersePieceState::Intact);
	TestFalse(TEXT("opening cells inactive"), Map.GetGrid().IsActive(Map.GetGrid().FindCellAnyState(FIntPoint(10, 5), EVerseArenaLevel::Floor)));
	TestEqual(TEXT("piece truth never read while unseen"), World.StateReads.Num(), 0);

	// The bot turns toward the wall: it sees the breach and may now plan through it.
	NowMs += 17;
	Map.ApplyFrame(SelfFrame(NowMs, Feet, 0.f), BeliefWorld);
	TestTrue(TEXT("seen: breached"), Map.GetPieces().GetBelievedState(7) == EVersePieceState::Breached);
	const TArray<int32> Path = Map.GetGrid().FindPath(RoomA, RoomB);
	TestTrue(TEXT("seen: a path through the opening"), Path.Num() > 0);

	SaveProof(TEXT("7.9"), TEXT("f7_wall_opened_unseen.json"),
		FString::Printf(TEXT("{\n  \"test\": \"F7 wall_opened_unseen (A7.7)\",\n  \"ticksUnseen\": 600,\n")
						TEXT("  \"plansThroughOpeningWhileUnseen\": %d,\n  \"pathAfterSeen\": %s,\n  \"pass\": %s\n}\n"),
			PlansThroughOpening, Path.Num() > 0 ? TEXT("true") : TEXT("false"), HasAnyErrors() ? TEXT("false") : TEXT("true")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefCostTest, "Verse.Perf.Bot.BeliefCost", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefCostTest::RunTest(const FString& Parameters)
{
	// A7.6: the belief step (predict with momentum, clear of the cached visible cells, normalise,
	// derived values) at most 0.05 ms with 6,000 cells. Sight traces are TestSight's (WP03) cost,
	// bounded by the map's per-step budget; Verse.Perf.Bot.BeliefTraceCost times them with real
	// line traces on a Recast-built arena.
	FVerseBeliefGrid Grid;
	Grid.Build(MakeThreeLevelSource());
	TestEqual(TEXT("6,000 cells"), Grid.NumCells(), 6000);
	const FVector Eye(2500.0, 500.0, 165.0);
	TArray<int32> Visible;
	for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
	{
		if (Grid.GetCell(Cell).Level == EVerseArenaLevel::Floor && Grid.GetCell(Cell).Column.Y < 15)
		{
			Visible.Add(Cell);
		}
	}
	// Spread the mass everywhere first (worst case: no empty cell to skip).
	Grid.ApplySighting(FVector(2500.0, 2000.0, 95.0), 0.f);
	Grid.SetMomentum(FVector(300.0, 200.0, 0.0), 0.f);
	for (int32 Step = 0; Step < 200; ++Step)
	{
		Grid.Predict(0.1f, Step * 0.1f);
		Grid.Normalise();
	}
	double Best = TNumericLimits<double>::Max();
	double Total = 0.0;
	int32 Steps = 0;
	FVerseBeliefDerived Derived;
	for (int32 Batch = 0; Batch < 5; ++Batch)
	{
		const double Start = FPlatformTime::Seconds();
		for (int32 Step = 0; Step < 100; ++Step)
		{
			const float NowS = 20.f + (Batch * 100 + Step) * 0.1f;
			Grid.Predict(0.1f, NowS);
			Grid.Clear(Eye, Visible, NowS);
			Grid.Normalise();
			Derived = Grid.ComputeDerived(NowS, false);
		}
		const double Elapsed = FPlatformTime::Seconds() - Start;
		Best = FMath::Min(Best, Elapsed / 100.0);
		Total += Elapsed;
		Steps += 100;
	}
	const double BestMs = Best * 1000.0;
	const double MeanMs = Total / Steps * 1000.0;

	// Per phase, best of 5 batches, for the report.
	double PhaseBest[4] = {1e9, 1e9, 1e9, 1e9};
	for (int32 Batch = 0; Batch < 5; ++Batch)
	{
		double Phase[4] = {0.0, 0.0, 0.0, 0.0};
		for (int32 Step = 0; Step < 100; ++Step)
		{
			const float NowS = 100.f + (Batch * 100 + Step) * 0.1f;
			double T0 = FPlatformTime::Seconds();
			Grid.Predict(0.1f, NowS);
			double T1 = FPlatformTime::Seconds();
			Grid.Clear(Eye, Visible, NowS);
			double T2 = FPlatformTime::Seconds();
			Grid.Normalise();
			double T3 = FPlatformTime::Seconds();
			Derived = Grid.ComputeDerived(NowS, false);
			double T4 = FPlatformTime::Seconds();
			Phase[0] += T1 - T0;
			Phase[1] += T2 - T1;
			Phase[2] += T3 - T2;
			Phase[3] += T4 - T3;
		}
		for (int32 Index = 0; Index < 4; ++Index)
		{
			PhaseBest[Index] = FMath::Min(PhaseBest[Index], Phase[Index] / 100.0 * 1000.0);
		}
	}
	AddInfo(FString::Printf(TEXT("phases ms: predict %.4f clear %.4f normalise %.4f derived %.4f"), PhaseBest[0], PhaseBest[1],
		PhaseBest[2], PhaseBest[3]));

	// The full map step on the lane fixture with the fake sight query and the default trace budget.
	FLaneFixture Fixture;
	FVerseBeliefMapConfig Config = Fixture.Config();
	Config.MaxCellSightTestsPerStep = FVerseBeliefMapConfig().MaxCellSightTestsPerStep;
	Config.MaxPieceSightTestsPerStep = FVerseBeliefMapConfig().MaxPieceSightTestsPerStep;
	FVerseBeliefMap Map;
	Map.Initialize(Fixture.Source, Config, Fixture.BeliefWorld());
	uint32 NowMs = 1000;
	const double MapStart = FPlatformTime::Seconds();
	int32 MapSteps = 0;
	for (int32 Tick = 0; Tick < 1200; ++Tick)
	{
		NowMs += 17;
		MapSteps += Map.ApplyFrame(SelfFrame(NowMs, ObserverFeet, float(Tick % 360)), Fixture.BeliefWorld()) ? 1 : 0;
	}
	const double MapMs = (FPlatformTime::Seconds() - MapStart) * 1000.0 / FMath::Max(1, MapSteps);

	TestTrue(FString::Printf(TEXT("A7.6 belief step %.4f ms with 6,000 cells <= 0.05"), BestMs), BestMs <= 0.05);
	SaveProof(TEXT("7.6"), TEXT("belief_cost.json"),
		FString::Printf(TEXT("{\n  \"test\": \"A7.6 belief cost\",\n  \"cells\": %d,\n  \"msPerStepBestBatch\": %.5f,\n")
						TEXT("  \"msPerStepMean\": %.5f,\n  \"budgetMs\": 0.05,\n  \"mapStepWithFakeSightMs\": %.5f,\n")
						TEXT("  \"mapCellSightTestsPerStep\": %d,\n  \"phaseMs\": {\"predict\": %.5f, \"clear\": %.5f, \"normalise\": %.5f, \"derived\": %.5f},\n")
						TEXT("  \"pass\": %s\n}\n"),
			Grid.NumCells(), BestMs, MeanMs, MapMs, Config.MaxCellSightTestsPerStep, PhaseBest[0], PhaseBest[1], PhaseBest[2], PhaseBest[3],
			BestMs <= 0.05 ? TEXT("true") : TEXT("false")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefDebugDrawTest, "Verse.Bot.Belief.DebugDraw", VERSE_BELIEF_TEST_FLAGS)

bool FVerseBeliefDebugDrawTest::RunTest(const FString& Parameters)
{
	// WP07.10: the top-down render covers the grid, outlines the cluster and uses no cyan or violet.
	FLaneFixture Fixture;
	FVerseBeliefGrid Grid;
	Grid.Build(Fixture.Source);
	Grid.ApplySighting(ColumnCentre(25, 30, 95.f), 0.f);
	Grid.Normalise();
	const FVerseBeliefDerived Derived = Grid.ComputeDerived(0.f, true);
	TArray<FColor> Pixels;
	int32 Width = 0;
	int32 Height = 0;
	FVerseBeliefDebugDraw::RenderTopDown(Grid, Derived, EVerseArenaLevel::Floor, 8, Pixels, Width, Height);
	TestEqual(TEXT("width 50 columns x 8"), Width, 400);
	TestEqual(TEXT("height 40 rows x 8"), Height, 320);
	int32 Gold = 0;
	int32 CoolHue = 0;
	for (const FColor& Pixel : Pixels)
	{
		Gold += Pixel == FColor(212, 175, 55) ? 1 : 0;
		CoolHue += (Pixel.B > Pixel.R + 20 && Pixel.B > 60) ? 1 : 0;
	}
	TestTrue(TEXT("cluster outlined in gold"), Gold > 50);
	TestEqual(TEXT("no cyan or violet pixels"), CoolHue, 0);
	TestTrue(TEXT("png written"), FVerseBeliefDebugDraw::SavePng(ProofDir(TEXT("7.10")) / TEXT("heatmap_render_check.png"), Grid,
		Derived, EVerseArenaLevel::Floor, 8));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

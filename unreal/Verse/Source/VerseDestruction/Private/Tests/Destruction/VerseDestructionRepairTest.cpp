#include "Tests/Destruction/VerseDestructionTestUtil.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "VerseGameplayTags.h"

using namespace VerseDestructionTest;

namespace
{
	/** Ticks until Pred holds or the limit passes; returns the time it held, or 0. */
	template <typename TPred>
	uint32 TickUntil(FVerseDestructionSim& Sim, uint32& Now, uint32 LimitMs, TPred Pred, TFunctionRef<bool(const FBox&)> Encroach = NeverEncroached)
	{
		for (; Now <= LimitMs; Now += TickMs)
		{
			Sim.Tick(Now, Encroach);
			Sim.DrainEvents();
			Sim.DrainNoise();
			Sim.DrainDirtyItems();
			if (Pred())
			{
				return Now;
			}
		}
		return 0;
	}

	FVerseDestructionSim MakeSim(TArray<FVersePieceDef> Defs, int32 NumDocks)
	{
		FVerseDestructionSim Sim;
		Sim.Init(MoveTemp(Defs), FVerseDestructionSimTuning::Contract(), VerseDestructionTest::Docks(NumDocks), 3);
		return Sim;
	}
}

// A6.5: repair starts 60 s after the last damage within one tick; damage during repair returns the
// piece to RepairFrom; a downed drone cancels; at most 3 drones active; completion waits while a
// pawn overlaps.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionRepairTiming, "Verse.Destruction.Repair.Timing", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionRepairTiming::RunTest(const FString&)
{
	const FVersePieceDef Wall = MakePiece(EVersePieceClass::WallPanel, FVector(0, 0, 0), 0);
	FVerseDestructionSim Sim = MakeSim({Wall}, 1);
	uint32 Now = 990;
	FVersePieceDamage Damage = Bolt(Wall);
	Sim.ApplyDamage(Damage, Now);
	const uint32 LastDamage = Now;
	// A second hit 10 s later restarts the 60 s.
	Now = Run(Sim, Now, LastDamage + 10000);
	Sim.ApplyDamage(Damage, Now);
	const uint32 Restart = Now;
	const uint32 Dispatched = TickUntil(Sim, Now, Restart + 70000, [&Sim] { return Sim.GetDrones()[0].Task == EVerseDroneTask::Outbound; });
	TestTrue(TEXT("dispatched"), Dispatched != 0);
	TestTrue(FString::Printf(TEXT("no dispatch before 60 s after the last damage (%u ms)"), Dispatched - Restart), Dispatched - Restart >= 60000);
	TestTrue(FString::Printf(TEXT("dispatch within one tick of 60 s (%u ms)"), Dispatched - Restart), Dispatched - Restart < 60000 + TickMs);
	TestEqual(TEXT("still Damaged while the drone flies"), Sim.GetItem(0).State, EVersePieceState::Damaged);

	const uint32 Arrived = TickUntil(Sim, Now, Now + 20000, [&Sim] { return Sim.GetItem(0).State == EVersePieceState::Repairing; });
	TestTrue(TEXT("Repairing starts on arrival"), Arrived != 0);
	TestEqual(TEXT("RepairFrom is the broken state"), Sim.GetItem(0).RepairFrom, EVersePieceState::Damaged);
	TestEqual(TEXT("the proxy stays the pre-repair proxy"), Sim.GetItem(0).GetProxyState(), EVersePieceState::Damaged);
	const uint32 Done = TickUntil(Sim, Now, Now + 20000, [&Sim] { return Sim.GetItem(0).State == EVersePieceState::Intact; });
	TestTrue(TEXT("repair completes"), Done != 0);
	TestTrue(FString::Printf(TEXT("wall panel repair takes 8 s (%u ms)"), Done - Arrived), Done - Arrived >= 8000 && Done - Arrived < 8000 + 2 * TickMs);
	TestEqual(TEXT("full HP after repair"), Sim.GetHp(0), 200.f);
	TestEqual(TEXT("HealthQ 255"), int32(Sim.GetItem(0).HealthQ), 255);
	TestEqual(TEXT("drone flies home"), Sim.GetDrones()[0].Task, EVerseDroneTask::Returning);
	TestEqual(TEXT("one repair counted"), Sim.GetCounters().Repairs, 1);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionRepairInterrupt, "Verse.Destruction.Repair.Interrupt", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionRepairInterrupt::RunTest(const FString&)
{
	const FVersePieceDef Wall = MakePiece(EVersePieceClass::ContainerWall, FVector(0, 0, 0), 0);
	FVerseDestructionSim Sim = MakeSim({Wall}, 1);
	uint32 Now = 0;
	FVersePieceDamage Charge = Breach(Wall);
	Sim.ApplyDamage(Charge, Now);
	TestEqual(TEXT("Breached"), Sim.GetItem(0).State, EVersePieceState::Breached);
	TestTrue(TEXT("repair starts"), TickUntil(Sim, Now, 90000, [&Sim] { return Sim.GetItem(0).State == EVersePieceState::Repairing; }) != 0);
	// Damage during the repair: back to RepairFrom, drone leaves, the 60 s restart.
	Now += TickMs;
	Sim.ApplyDamage(Bolt(Wall), Now);
	TestEqual(TEXT("damage during repair returns the piece to RepairFrom"), Sim.GetItem(0).State, EVersePieceState::Breached);
	TestEqual(TEXT("the drone leaves"), Sim.GetDrones()[0].Task, EVerseDroneTask::Returning);
	TestEqual(TEXT("the 60 s restart at the interrupting hit"), Sim.GetLastDamageMs(0), Now);
	TestEqual(TEXT("interruption counted"), Sim.GetCounters().RepairsInterrupted, 1);
	const uint32 Interrupted = Now;
	const uint32 Again = TickUntil(Sim, Now, Interrupted + 70000, [&Sim] { return Sim.GetDrones()[0].Task == EVerseDroneTask::Outbound; });
	TestTrue(TEXT("a new dispatch only 60 s after the interruption"), Again != 0 && Again - Interrupted >= 60000);

	// A downed drone cancels the repair as well.
	TestTrue(TEXT("repairing again"), TickUntil(Sim, Now, Now + 30000, [&Sim] { return Sim.GetItem(0).State == EVersePieceState::Repairing; }) != 0);
	TestFalse(TEXT("29 HP does not down the drone"), Sim.ApplyDroneDamage(0, 29.f, Now));
	TestEqual(TEXT("still repairing after a graze"), Sim.GetItem(0).State, EVersePieceState::Repairing);
	TestTrue(TEXT("30 HP downs the drone"), Sim.ApplyDroneDamage(0, 1.f, Now));
	TestEqual(TEXT("downing the drone returns the piece to RepairFrom"), Sim.GetItem(0).State, EVersePieceState::Breached);
	TestEqual(TEXT("downed drone"), Sim.GetDrones()[0].Task, EVerseDroneTask::Down);
	TestEqual(TEXT("generation bumped (client debris)"), Sim.GetDrones()[0].Generation, 1u);
	Now += TickMs;
	Sim.Tick(Now, NeverEncroached);
	TestEqual(TEXT("the dock replaces it"), Sim.GetDrones()[0].Task, EVerseDroneTask::Docked);
	TestEqual(TEXT("with full HP"), Sim.GetDrones()[0].Hp, 30.f);
	TestFalse(TEXT("an unknown drone takes no damage"), Sim.ApplyDroneDamage(7, 100.f, Now));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionRepairQueue, "Verse.Destruction.Repair.Queue", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionRepairQueue::RunTest(const FString&)
{
	// Six broken pieces and five docks: at most 3 drones active; catwalks, then walls, then glass,
	// then ceiling panels; within a class the longest-broken first.
	TArray<FVersePieceDef> Defs;
	Defs.Add(MakePiece(EVersePieceClass::CeilingPanel, FVector(0, 0, 500), 0));
	Defs.Add(MakePiece(EVersePieceClass::GlassPane, FVector(500, 0, 0), 1));
	Defs.Add(MakePiece(EVersePieceClass::WallPanel, FVector(1000, 0, 0), 2));
	Defs.Add(MakePiece(EVersePieceClass::CatwalkSegment, FVector(1500, 0, 300), 3));
	Defs.Add(MakePiece(EVersePieceClass::ContainerWall, FVector(2000, 0, 0), 4));
	Defs.Add(MakePiece(EVersePieceClass::WallPanel, FVector(2500, 0, 0), 5));
	FVerseDestructionSim Sim = MakeSim(Defs, 5);
	uint32 Now = 0;
	// Break order: wall 5 first (longest broken among the walls), then the others at once.
	FVersePieceDamage D = Bolt(Defs[5]);
	D.PieceIndex = 5;
	Sim.ApplyDamage(D, Now);
	Now += 1000;
	for (const int32 Index : {0, 1, 2, 4})
	{
		D = Index == 0 ? Bolt(Defs[0], 10.f, FVector(0, 0, 1)) : Bolt(Defs[Index]);
		D.PieceIndex = uint16(Index);
		Sim.ApplyDamage(D, Now);
	}
	FVersePieceDamage Charge = Breach(Defs[3], FVector(0, 0, 5));
	Charge.PieceIndex = 3;
	Sim.ApplyDamage(Charge, Now);
	TestEqual(TEXT("catwalk Destroyed"), Sim.GetItem(3).State, EVersePieceState::Destroyed);

	TArray<int32> FirstWave;
	int32 PeakActive = 0;
	for (; Now < 200000; Now += TickMs)
	{
		Sim.Tick(Now, NeverEncroached);
		Sim.DrainEvents();
		Sim.DrainNoise();
		Sim.DrainDirtyItems();
		PeakActive = FMath::Max(PeakActive, Sim.NumActiveDrones());
		if (FirstWave.Num() == 0 && Sim.NumActiveDrones() > 0 && Now >= 61000)
		{
			for (const FVerseDroneState& Drone : Sim.GetDrones())
			{
				if (Drone.IsActive())
				{
					FirstWave.Add(Drone.TargetPiece);
				}
			}
		}
	}
	TestEqual(TEXT("at most 3 drones active"), PeakActive, 3);
	FirstWave.Sort();
	// Wall 5 broke first and is due 1 s earlier: it alone goes at 60 s. At 61 s three are active:
	// wall 5, then the catwalk and the longest-broken walls (2 and 4 tie; index order).
	TestEqual(TEXT("first wave: catwalk and walls before glass and ceiling"), FirstWave, TArray<int32>({2, 3, 5}));
	for (int32 Index = 0; Index < Defs.Num(); ++Index)
	{
		TestEqual(FString::Printf(TEXT("piece %d repaired in the end"), Index), Sim.GetItem(uint16(Index)).State, EVersePieceState::Intact);
	}
	TestEqual(TEXT("six repairs"), Sim.GetCounters().Repairs, 6);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionRepairEncroach, "Verse.Destruction.Repair.Encroachment", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionRepairEncroach::RunTest(const FString&)
{
	const FVersePieceDef Glass = MakePiece(EVersePieceClass::GlassPane, FVector(0, 0, 0), 0);
	FVerseDestructionSim Sim = MakeSim({Glass}, 1);
	uint32 Now = 0;
	FVersePieceDamage Charge = Breach(Glass);
	Sim.ApplyDamage(Charge, Now);
	TestTrue(TEXT("repairing"), TickUntil(Sim, Now, 90000, [&Sim] { return Sim.GetItem(0).State == EVersePieceState::Repairing; }) != 0);
	const uint32 RepairStart = Now;
	const uint32 PawnLeaves = RepairStart + 4000 + 2100; // glass repairs in 4 s; a pawn stands in it 2.1 s longer
	FBox Checked(ForceInit);
	auto Encroach = [&Now, PawnLeaves, &Checked](const FBox& Box)
	{
		Checked = Box;
		return Now < PawnLeaves;
	};
	const uint32 Done = TickUntil(Sim, Now, RepairStart + 20000, [&Sim] { return Sim.GetItem(0).State == EVersePieceState::Intact; }, Encroach);
	TestTrue(TEXT("completion waits while a pawn overlaps"), Done >= PawnLeaves);
	TestTrue(TEXT("re-checked every 0.5 s"), Done < PawnLeaves + 500 + TickMs);
	const FBox Expected = Glass.GetWorldBounds(EVersePieceState::Intact, 0).ExpandBy(10.f);
	TestTrue(TEXT("the overlap box is the Intact proxy +10 cm"), Checked.Min.Equals(Expected.Min, 0.01) && Checked.Max.Equals(Expected.Max, 0.01));
	TestEqual(TEXT("glass restored with HP"), Sim.GetHp(0), 20.f);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionRepairNoise, "Verse.Destruction.Repair.Noise", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionRepairNoise::RunTest(const FString&)
{
	const FVersePieceDef Wall = MakePiece(EVersePieceClass::WallPanel, FVector(0, 0, 0), 0);
	FVerseDestructionSim Sim = MakeSim({Wall}, 1);
	Sim.ApplyDamage(Bolt(Wall), 0);
	Sim.DrainNoise();
	int32 DroneNoise = 0;
	float Loudness = 0.f;
	for (uint32 Now = 0; Now < 75000; Now += TickMs)
	{
		Sim.Tick(Now, NeverEncroached);
		for (const FVerseNoiseEvent& Noise : Sim.DrainNoise())
		{
			if (Noise.Noise == VerseTags::Noise_Drone)
			{
				++DroneNoise;
				Loudness = Noise.Loudness;
				TestEqual(TEXT("world source"), Noise.SourceId, -1);
			}
		}
		Sim.DrainEvents();
		Sim.DrainDirtyItems();
	}
	TestTrue(TEXT("flight and welding emit Noise.Drone"), DroneNoise >= 5);
	TestEqual(TEXT("drone loudness 0.15"), Loudness, 0.15f);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

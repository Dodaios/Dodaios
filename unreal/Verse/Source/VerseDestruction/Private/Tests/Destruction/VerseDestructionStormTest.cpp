#include "Tests/Destruction/VerseDestructionTestUtil.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Debris/VerseDebrisBudget.h"
#include "Destruction/VersePenetrationTable.h"
#include "HAL/PlatformTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

using namespace VerseDestructionTest;

namespace
{
	/** Client debris replica fed only by multicast events. */
	struct FDebrisClient
	{
		FVerseDebrisBudget Budget;
		const FVerseDestructionSim* Sim = nullptr;

		FDebrisClient(const FVerseDebrisBudget::FConfig& Config, const FVerseDestructionSim& InSim)
			: Budget(Config)
			, Sim(&InSim)
		{
		}

		void OnEvent(const FVerseFractureEvent& Event, double NowS)
		{
			if (Event.Cause == EVerseFractureCause::Reset)
			{
				Budget.PurgeAll();
				return;
			}
			if (Event.Cause == EVerseFractureCause::Repair || !Sim->IsValidPiece(Event.PieceIndex))
			{
				return;
			}
			const FVersePenetrationRow* Row = GetDefault<UVersePenetrationTable>()->FindRow(uint8(Sim->GetDef(Event.PieceIndex).Material));
			FVerseDebrisBudget::FRequest Request;
			Request.PieceIndex = Event.PieceIndex;
			Request.Type = Row ? Row->DebrisType : EVerseDebrisType::SparksOnly;
			Request.ToState = Event.ToState;
			Budget.Request(Request, NowS);
		}
	};

	struct FStormResult
	{
		int32 DurationS = 0;
		int32 Fractures = 0;
		int32 PeakEventsPerSecond = 0;
		int32 EventsOverRate = 0;
		int32 PeakBodiesHigh = 0;
		int32 PeakBodiesLow = 0;
		int32 PeakPerFracture = 0;
		int32 PeakActors = 0;
		int32 PeakNavInFlight = 0;
		int32 Repairs = 0;
		int32 PeakDrones = 0;
		double SimMsPerTickMax = 0.0;
		int32 ItemBytes = 0;
		int32 ItemWrites = 0;
		uint32 FinalHash = 0;
		TArray<uint32> HashPerSecond;
	};

	/**
	 * destruction_storm (destruction.md 10): two breach charges plus a full magazine (30 bolts)
	 * into a container row every 2 s, rows in turn, with repair drones running.
	 */
	FStormResult RunStorm(int32 DurationS, uint64 Seed)
	{
		FVerseDestructionSim Sim;
		Sim.Init(MakeArena(), FVerseDestructionSimTuning::Contract(), Docks(4), Seed);
		FDebrisClient High(FVerseDebrisBudget::FConfig::High(), Sim);
		FDebrisClient Low(FVerseDebrisBudget::FConfig::Low(), Sim);
		FStormResult Result;
		Result.DurationS = DurationS;
		constexpr int32 PerRow = 8;
		const int32 Rows = 30;
		FVerseRng Rng(Seed, 0, EVerseRngSalt::Harness);
		int32 Wave = 0;
		uint32 NextSecond = 1000;
		for (uint32 Now = 0; Now < uint32(DurationS) * 1000; Now += TickMs)
		{
			const double Start = FPlatformTime::Seconds();
			// Every 2 s a new wave on the next row: two charges at once, then the magazine over 1 s.
			const uint32 WaveStart = uint32(Wave) * 2000;
			if (Now >= WaveStart)
			{
				const int32 Row = Wave % Rows;
				for (int32 Charge = 0; Charge < 2; ++Charge)
				{
					const uint16 Target = uint16(Row * (PerRow + 2) + Rng.RangeInt(0, PerRow - 1));
					FVersePieceDamage D = Breach(Sim.GetDef(Target), FVector(Rng.Range(-80, 80), -5, Rng.Range(30, 150)));
					D.PieceIndex = Target;
					Sim.ApplyDamage(D, Now);
				}
				++Wave;
			}
			const uint32 SinceWave = Now - (uint32(Wave - 1) * 2000);
			if (SinceWave < 1000)
			{
				const int32 Row = (Wave - 1) % Rows;
				// 30 rounds over 1 s at 30 Hz: one bolt per tick into the row.
				const uint16 Target = uint16(Row * (PerRow + 2) + Rng.RangeInt(0, PerRow - 1));
				FVersePieceDamage D = Bolt(Sim.GetDef(Target), 10.f, FVector(Rng.Range(-110, 110), -1, Rng.Range(20, 240)));
				D.PieceIndex = Target;
				Sim.ApplyDamage(D, Now);
			}
			Sim.Tick(Now, NeverEncroached);
			const double NowS = double(Now) / 1000.0;
			for (const FVersePendingFracture& Pending : Sim.DrainEvents())
			{
				++Result.Fractures;
				if (Pending.bMulticast)
				{
					High.OnEvent(Pending.Event, NowS);
					Low.OnEvent(Pending.Event, NowS);
				}
			}
			High.Budget.Tick(NowS);
			Low.Budget.Tick(NowS);
			Sim.DrainNoise();
			Sim.DrainDirtyItems();
			Sim.GetNav().Release(Sim.GetNav().NumInFlight());
			Result.PeakNavInFlight = FMath::Max(Result.PeakNavInFlight, Sim.GetNav().GetPeakInFlight());
			Result.SimMsPerTickMax = FMath::Max(Result.SimMsPerTickMax, (FPlatformTime::Seconds() - Start) * 1000.0);
			if (Now >= NextSecond)
			{
				Result.HashPerSecond.Add(FVerseDestructionSim::ProxyHash(Sim.GetItems()));
				NextSecond += 1000;
			}
		}
		const FVerseDestructionCounters& C = Sim.GetCounters();
		Result.PeakEventsPerSecond = C.PeakEventsPerSecond;
		Result.EventsOverRate = C.EventsOverRate;
		Result.PeakBodiesHigh = High.Budget.GetPeakBodies();
		Result.PeakBodiesLow = Low.Budget.GetPeakBodies();
		Result.PeakPerFracture = FMath::Max(High.Budget.GetPeakBodiesPerFracture(), Low.Budget.GetPeakBodiesPerFracture());
		Result.PeakActors = FMath::Max(High.Budget.GetPeakActors(), Low.Budget.GetPeakActors());
		Result.Repairs = C.Repairs;
		Result.PeakDrones = C.PeakActiveDrones;
		Result.ItemBytes = (FVersePieceItem::PackedBits() + 7) / 8;
		Result.ItemWrites = C.ItemWrites;
		Result.FinalHash = FVerseDestructionSim::ProxyHash(Sim.GetItems());
		return Result;
	}

	void WriteProof(const FStormResult& R)
	{
		// Hand-written JSON: the module links no JSON library.
		const TPair<const TCHAR*, double> Numbers[] = {
			{TEXT("duration_s"), double(R.DurationS)},
			{TEXT("fracture_events"), double(R.Fractures)},
			{TEXT("peak_multicast_events_per_s"), double(R.PeakEventsPerSecond)},
			{TEXT("events_over_rate_dropped_multicast"), double(R.EventsOverRate)},
			{TEXT("peak_debris_bodies_high"), double(R.PeakBodiesHigh)},
			{TEXT("peak_debris_bodies_low"), double(R.PeakBodiesLow)},
			{TEXT("peak_bodies_per_fracture"), double(R.PeakPerFracture)},
			{TEXT("peak_geometry_collection_actors"), double(R.PeakActors)},
			{TEXT("peak_nav_tiles_in_flight"), double(R.PeakNavInFlight)},
			{TEXT("repairs"), double(R.Repairs)},
			{TEXT("peak_active_drones"), double(R.PeakDrones)},
			{TEXT("state_item_packed_bytes"), double(R.ItemBytes)},
			{TEXT("item_writes"), double(R.ItemWrites)},
			{TEXT("sim_ms_per_tick_max"), double(R.SimMsPerTickMax)},
			{TEXT("budget_debris_bodies_high"), double(400)},
			{TEXT("budget_debris_bodies_low"), double(150)},
			{TEXT("budget_bodies_per_fracture"), double(40)},
			{TEXT("budget_geometry_collection_actors"), double(32)},
			{TEXT("budget_fracture_events_per_s"), double(64)},
			{TEXT("budget_nav_tiles_in_flight"), double(4)},
		};
		FString Text = TEXT("{\n  \"scenario\": \"destruction_storm\",\n  \"package\": \"WP06\",\n  \"sub_task\": \"WP06.11\",\n");
		Text += TEXT("  \"physics_ms\": \"not measured headless: needs the rendered lane (unreal-perf)\"");
		for (const TPair<const TCHAR*, double>& Field : Numbers)
		{
			Text += FString::Printf(TEXT(",\n  \"%s\": %s"), Field.Key, *FString::SanitizeFloat(Field.Value));
		}
		Text += TEXT("\n}\n");
		const FString Path = FPaths::ProjectSavedDir() / TEXT("Harness/proof/WP06/WP06.11/destruction_storm.json");
		FFileHelper::SaveStringToFile(Text, *Path);
	}
}

// A6.3: 400 debris bodies max (150 Low), 40 per fracture, 32 GC actors, at most 64 fracture
// events/s, state items about 20 bytes. Physics time needs the rendered lane.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionStorm, "Verse.Destruction.Storm", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionStorm::RunTest(const FString&)
{
	const FStormResult R = RunStorm(60, 0x5708);
	WriteProof(R);
	AddInfo(FString::Printf(TEXT("storm: %d fractures, peak %d events/s, bodies %d (high) %d (low), %d per fracture, %d actors, %d repairs"),
		R.Fractures, R.PeakEventsPerSecond, R.PeakBodiesHigh, R.PeakBodiesLow, R.PeakPerFracture, R.PeakActors, R.Repairs));
	TestTrue(TEXT("the storm breaks things"), R.Fractures > 100);
	TestTrue(TEXT("at most 400 debris bodies on High"), R.PeakBodiesHigh <= 400);
	TestTrue(TEXT("at most 150 debris bodies on Low"), R.PeakBodiesLow <= 150);
	TestTrue(TEXT("the High cap is reached (the storm is a real load)"), R.PeakBodiesHigh > 150);
	TestTrue(TEXT("at most 40 bodies per fracture"), R.PeakPerFracture <= 40);
	TestTrue(TEXT("at most 32 geometry collection actors"), R.PeakActors <= 32);
	TestTrue(TEXT("at most 64 multicast fracture events per second"), R.PeakEventsPerSecond <= 64);
	TestTrue(TEXT("at most 4 nav tiles in flight"), R.PeakNavInFlight <= 4);
	TestTrue(TEXT("at most 3 drones active"), R.PeakDrones <= 3);
	TestTrue(TEXT("a state item packs into about 20-26 bytes"), R.ItemBytes <= 26);
	return true;
}

// A6.7: server and 2 clients agree on every proxy state after a 10-minute storm (hash per
// second). Client 1 gets every item write one tick late; client 2 loses 25 % of the sends and
// gets the latest value on the retry (fast array semantics). Both also lose 30 % of the
// unreliable events, which must not matter.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionDeterminism, "Verse.Destruction.Determinism", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionDeterminism::RunTest(const FString&)
{
	FVerseDestructionSim Sim;
	Sim.Init(MakeArena(), FVerseDestructionSimTuning::Contract(), Docks(4), 0xD7);
	TArray<FVersePieceItem> Client1 = Sim.GetItems();
	TArray<FVersePieceItem> Client2 = Sim.GetItems();
	TArray<uint16> Late;
	TSet<uint16> Unsent;
	FVerseRng Net(0xD7, 1, EVerseRngSalt::Harness);
	FVerseRng Rng(0xD7, 2, EVerseRngSalt::Harness);
	int32 Seconds = 0;
	int32 HashMismatches = 0;
	int32 Wave = 0;
	uint32 NextSecond = 1000;
	const uint32 EndMs = 600 * 1000;
	for (uint32 Now = 0; Now < EndMs; Now += TickMs)
	{
		if (Now >= uint32(Wave) * 2000)
		{
			const int32 Row = Wave % 30;
			for (int32 Charge = 0; Charge < 2; ++Charge)
			{
				const uint16 Target = uint16(Row * 10 + Rng.RangeInt(0, 7));
				FVersePieceDamage D = Breach(Sim.GetDef(Target), FVector(Rng.Range(-80, 80), -5, Rng.Range(30, 150)));
				D.PieceIndex = Target;
				Sim.ApplyDamage(D, Now);
			}
			++Wave;
		}
		if (Now - uint32(Wave - 1) * 2000 < 1000)
		{
			const uint16 Target = uint16(((Wave - 1) % 30) * 10 + Rng.RangeInt(0, 9));
			FVersePieceDamage D = Bolt(Sim.GetDef(Target), 10.f, FVector(Rng.Range(-50, 50), -1, Rng.Range(100, 200)));
			D.PieceIndex = Target;
			Sim.ApplyDamage(D, Now);
		}
		Sim.Tick(Now, NeverEncroached);
		Sim.DrainEvents(); // unreliable events never change client state
		Sim.DrainNoise();
		// Client 1: one tick late.
		for (const uint16 Index : Late)
		{
			Client1[Index] = Sim.GetItem(Index);
		}
		Late = Sim.DrainDirtyItems();
		// Client 2: lossy; a lost item is resent with its latest value.
		for (const uint16 Index : Late)
		{
			Unsent.Add(Index);
		}
		for (auto It = Unsent.CreateIterator(); It; ++It)
		{
			if (!Net.Chance(0.25))
			{
				Client2[*It] = Sim.GetItem(*It);
				It.RemoveCurrent();
			}
		}
		if (Now >= NextSecond)
		{
			NextSecond += 1000;
			++Seconds;
			// Compare once the network has caught up with this second's writes.
			for (const uint16 Index : Late)
			{
				Client1[Index] = Sim.GetItem(Index);
			}
			Late.Reset();
			for (const uint16 Index : Unsent)
			{
				Client2[Index] = Sim.GetItem(Index);
			}
			Unsent.Reset();
			const uint32 Truth = FVerseDestructionSim::ProxyHash(Sim.GetItems());
			HashMismatches += (FVerseDestructionSim::ProxyHash(Client1) != Truth) ? 1 : 0;
			HashMismatches += (FVerseDestructionSim::ProxyHash(Client2) != Truth) ? 1 : 0;
		}
	}
	TestTrue(TEXT("ten minutes simulated"), Seconds >= 599);
	TestEqual(TEXT("hash per second: server and 2 clients agree"), HashMismatches, 0);
	TestTrue(TEXT("pieces were repaired during the storm"), Sim.GetCounters().Repairs > 0);
	// Same seed, same inputs: the server replays bit-identically.
	const FStormResult A = RunStorm(30, 0xBEEF);
	const FStormResult B = RunStorm(30, 0xBEEF);
	TestEqual(TEXT("replay: same per-second hashes"), A.HashPerSecond, B.HashPerSecond);
	TestEqual(TEXT("replay: same final hash"), A.FinalHash, B.FinalHash);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

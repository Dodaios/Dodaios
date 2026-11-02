#include "Tests/Destruction/VerseDestructionTestUtil.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Pieces/VerseDestructible.h"
#include "Pieces/VerseDestructionManager.h"
#include "Pieces/VersePieceManifest.h"

namespace VerseDestructionTest
{
	/** Defined in VerseDestructionStormTest.cpp: runs destruction_storm and returns its hashes. */
	uint32 StormFinalHash(int32 DurationS, uint64 Seed, TArray<uint32>& OutPerSecond);
}

using namespace VerseDestructionTest;

namespace
{
	/**
	 * Stand-in for WP03's hole store (WP03 owns holes): a bolt into a wall piece that is still
	 * Intact or Damaged leaves a hole record; a fracture event to Holed or beyond, a repair and
	 * a reset clear the piece's records (destruction.md 5). Replicated like the items.
	 */
	struct FStubHoles
	{
		TMap<uint16, TArray<uint32>> ByPiece;

		uint32 Hash(uint16 PieceIndex) const
		{
			uint32 H = 0x9E3779B9u ^ PieceIndex;
			if (const TArray<uint32>* Holes = ByPiece.Find(PieceIndex))
			{
				for (const uint32 Hole : *Holes)
				{
					H = HashCombineFast(H, Hole);
				}
			}
			return H;
		}
	};

	/** One client: its own world, the piece actors and a client manager fed through the fast-array path. */
	struct FClient
	{
		TUniquePtr<FTestWorld> World;
		AVerseDestructionManager* Manager = nullptr;
		FStubHoles Holes;

		FClient(const TCHAR* Name, const TArray<FVersePieceDef>& Defs, UVersePieceManifest* Manifest, TConstArrayView<FVersePieceItem> Initial)
		{
			World = MakeUnique<FTestWorld>(Name);
			for (const FVersePieceDef& Def : Defs)
			{
				World->SpawnPiece(Def);
			}
			Manager = World->SpawnManager(true, 0, Manifest);
			Manager->ReceiveItemsForTest(Initial, true); // the join: the whole fast array once
		}

		void Deliver(uint16 Index, const FVersePieceItem& Item, const FStubHoles& ServerHoles)
		{
			Manager->ReceiveItemsForTest(MakeArrayView(&Item, 1), false);
			if (const TArray<uint32>* Server = ServerHoles.ByPiece.Find(Index))
			{
				Holes.ByPiece.Add(Index, *Server);
			}
			else
			{
				Holes.ByPiece.Remove(Index);
			}
		}

		/** What the client shows and answers for a piece: query state, item variant, actor look, holes. */
		uint32 PieceHash(uint16 Index) const
		{
			const FVersePieceItem* Item = Manager->FindItem(Index);
			const AVerseDestructible* Actor = Manager->GetPieceActor(Index);
			uint32 H = uint32(Manager->GetPieceState(Index));
			H = HashCombineFast(H, Item ? uint32(Item->Variant) : 0xFFu);
			H = HashCombineFast(H, Actor ? uint32(Actor->GetPresentedState()) : 0xFFu);
			H = HashCombineFast(H, Actor ? uint32(Actor->GetPresentedVariant()) : 0xFFu);
			return HashCombineFast(H, Holes.Hash(Index));
		}
	};

	uint32 ServerPieceHash(const FVerseDestructionSim& Sim, const FStubHoles& Holes, uint16 Index)
	{
		const FVersePieceItem& Item = Sim.GetItem(Index);
		uint32 H = uint32(Item.State);
		H = HashCombineFast(H, uint32(Item.Variant));
		H = HashCombineFast(H, uint32(Item.State)); // the server's actor shows the item's state
		H = HashCombineFast(H, uint32(Item.Variant));
		return HashCombineFast(H, Holes.Hash(Index));
	}

	bool IsWall(EVersePieceClass Class)
	{
		return Class == EVersePieceClass::WallPanel || Class == EVersePieceClass::CladdingWall || Class == EVersePieceClass::ContainerWall;
	}
}

// A6.7 (local part): a 10-minute destruction storm; two client managers in their own worlds get
// the item writes through the fast-array callback path, client 1 one tick late, client 2 losing
// 25 % of the sends (a lost item goes again with its latest value, fast array semantics); the
// unreliable events are not delivered at all. Every second each client's query state, item
// variant, actor look and hole set is compared with the server for every piece that has not
// changed for one second; nothing is flushed before comparing. The multi-process run on the WP10
// netcode runner is still open.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionDeterminism, "Verse.Destruction.Determinism", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionDeterminism::RunTest(const FString&)
{
	const TArray<FVersePieceDef> Defs = MakeArena();
	FVerseDestructionSim Sim;
	Sim.Init(Defs, FVerseDestructionSimTuning::Contract(), Docks(4), 0xD7);
	UVersePieceManifest* Manifest = NewObject<UVersePieceManifest>();
	for (const FVersePieceDef& Def : Defs)
	{
		Manifest->PieceGuids.Add(Def.Guid); // the server's index order
	}
	FClient Late(TEXT("VerseDeterminismLate"), Defs, Manifest, Sim.GetItems());
	FClient Lossy(TEXT("VerseDeterminismLossy"), Defs, Manifest, Sim.GetItems());
	if (!TestEqual(TEXT("client manager has every piece"), Late.Manager->NumPieces(), Defs.Num()))
	{
		return false;
	}
	FStubHoles ServerHoles;
	TArray<uint32> LastChangeMs;
	LastChangeMs.Init(0, Defs.Num());
	TArray<uint16> LateQueue;
	TSet<uint16> LossyPending;
	FVerseRng Net(0xD7, 1, EVerseRngSalt::Harness);
	FVerseRng Rng(0xD7, 2, EVerseRngSalt::Harness);
	int32 Seconds = 0;
	int64 Compared = 0;
	int32 Mismatches = 0;
	int32 HoleRecords = 0;
	int32 Wave = 0;
	uint32 NextSecond = 1000;
	const uint32 EndMs = 600 * 1000;
	auto Shoot = [&](const FVersePieceDamage& D, uint32 Now)
	{
		const EVersePieceState Before = Sim.GetItem(D.PieceIndex).State;
		Sim.ApplyDamage(D, Now);
		if (D.Cause == EVerseFractureCause::Bolt && IsWall(Sim.GetDef(D.PieceIndex).Class)
			&& (Before == EVersePieceState::Intact || Before == EVersePieceState::Damaged)
			&& (Sim.GetItem(D.PieceIndex).State == EVersePieceState::Intact || Sim.GetItem(D.PieceIndex).State == EVersePieceState::Damaged))
		{
			ServerHoles.ByPiece.FindOrAdd(D.PieceIndex).Add(GetTypeHash(D.Location));
			LastChangeMs[D.PieceIndex] = Now;
			LateQueue.AddUnique(D.PieceIndex);
			++HoleRecords;
		}
	};
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
				Shoot(D, Now);
			}
			++Wave;
		}
		if (Now - uint32(Wave - 1) * 2000 < 1000)
		{
			const uint16 Target = uint16(((Wave - 1) % 30) * 10 + Rng.RangeInt(0, 9));
			FVersePieceDamage D = Bolt(Sim.GetDef(Target), 4.f, FVector(Rng.Range(-50, 50), -1, Rng.Range(100, 200)));
			D.PieceIndex = Target;
			Shoot(D, Now);
		}
		Sim.Tick(Now, NeverEncroached);
		// WP03 clears a piece's holes when it goes Holed or beyond, is repaired or reset.
		for (const FVersePendingFracture& Pending : Sim.DrainEvents())
		{
			const FVerseFractureEvent& E = Pending.Event;
			if (Pending.bPublishLocal && E.ToState != EVersePieceState::Damaged && E.PieceIndex != Verse::Destruction::AllPieces && ServerHoles.ByPiece.Remove(E.PieceIndex) > 0)
			{
				LastChangeMs[E.PieceIndex] = Now;
				LateQueue.AddUnique(E.PieceIndex);
			}
		}
		Sim.DrainNoise();
		// Client 1 gets last tick's writes now; this tick's go out next tick.
		for (const uint16 Index : LateQueue)
		{
			Late.Deliver(Index, Sim.GetItem(Index), ServerHoles);
		}
		TArray<uint16> Written = Sim.DrainDirtyItems();
		for (const uint16 Index : Written)
		{
			LastChangeMs[Index] = Now;
		}
		for (const uint16 Index : LateQueue)
		{
			Written.AddUnique(Index);
		}
		LateQueue = Written;
		// Client 2: every pending piece goes with its latest value; 25 % of sends are lost and retried.
		for (const uint16 Index : Written)
		{
			LossyPending.Add(Index);
		}
		for (auto It = LossyPending.CreateIterator(); It; ++It)
		{
			if (!Net.Chance(0.25))
			{
				Lossy.Deliver(*It, Sim.GetItem(*It), ServerHoles);
				It.RemoveCurrent();
			}
		}
		if (Now >= NextSecond)
		{
			NextSecond += 1000;
			++Seconds;
			for (int32 Index = 0; Index < Defs.Num(); ++Index)
			{
				if (Now - LastChangeMs[Index] < 1000)
				{
					continue; // still settling: compared again next second
				}
				const uint32 Truth = ServerPieceHash(Sim, ServerHoles, uint16(Index));
				Mismatches += Late.PieceHash(uint16(Index)) != Truth ? 1 : 0;
				Mismatches += Lossy.PieceHash(uint16(Index)) != Truth ? 1 : 0;
				Compared += 2;
			}
		}
	}
	AddInfo(FString::Printf(TEXT("%d seconds, %lld piece comparisons, %d hole records, %d repairs"), Seconds, Compared, HoleRecords, Sim.GetCounters().Repairs));
	TestTrue(TEXT("ten minutes simulated"), Seconds >= 599);
	TestTrue(TEXT("most pieces compared every second"), Compared > int64(Seconds) * Defs.Num());
	TestTrue(TEXT("the stub hole store saw holes"), HoleRecords > 0);
	TestEqual(TEXT("every settled piece: server and 2 clients agree (state, variant, look, holes)"), Mismatches, 0);
	TestTrue(TEXT("pieces were repaired during the storm"), Sim.GetCounters().Repairs > 0);
	// Same seed, same inputs: the server replays bit-identically.
	TArray<uint32> A;
	TArray<uint32> B;
	const uint32 FinalA = StormFinalHash(30, 0xBEEF, A);
	const uint32 FinalB = StormFinalHash(30, 0xBEEF, B);
	TestEqual(TEXT("replay: same per-second hashes"), A, B);
	TestEqual(TEXT("replay: same final hash"), FinalA, FinalB);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

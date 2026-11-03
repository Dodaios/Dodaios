#include "Tests/Destruction/VerseDestructionTestUtil.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Debris/VerseDebrisBudget.h"
#include "Debris/VerseDebrisSubsystem.h"
#include "Events/VerseEventHub.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VerseDestructionManager.h"
#include "Pieces/VersePieceManifest.h"
#include "UObject/CoreNet.h"

using namespace VerseDestructionTest;

namespace
{
	FVersePieceItem RoundTrip(const FVersePieceItem& In, int32& OutBits)
	{
		FNetBitWriter Writer(nullptr, 1024);
		FVersePieceItem Copy = In;
		bool bOk = false;
		Copy.NetSerialize(Writer, nullptr, bOk);
		OutBits = int32(Writer.GetNumBits());
		FNetBitReader Reader(nullptr, Writer.GetData(), Writer.GetNumBits());
		FVersePieceItem Out;
		Out.NetSerialize(Reader, nullptr, bOk);
		return Out;
	}

	bool SameItem(const FVersePieceItem& A, const FVersePieceItem& B)
	{
		return A.PieceIndex == B.PieceIndex && A.State == B.State && A.HealthQ == B.HealthQ && A.Variant == B.Variant
			&& A.RepairFrom == B.RepairFrom && A.LastSeed == B.LastSeed && FMemory::Memcmp(A.LastImpulse, B.LastImpulse, sizeof(A.LastImpulse)) == 0
			&& FMemory::Memcmp(A.LastLocation, B.LastLocation, sizeof(A.LastLocation)) == 0 && A.StateTimeMs == B.StateTimeMs
			&& A.Epoch == B.Epoch;
	}

	TArray<FVersePieceDef> ContainerRow(int32 Count)
	{
		TArray<FVersePieceDef> Defs;
		for (int32 Index = 0; Index < Count; ++Index)
		{
			Defs.Add(MakePiece(EVersePieceClass::ContainerWall, FVector(Index * 1000.0, 0, 0), 700 + Index));
		}
		return Defs;
	}
}

// destruction.md 3.3: the packed item round-trips losslessly and its size is measured, not assumed.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionNetItem, "Verse.Destruction.Net.ItemSerialize", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionNetItem::RunTest(const FString&)
{
	FVersePieceItem Fractured;
	Fractured.PieceIndex = 1999;
	Fractured.State = EVersePieceState::Breached;
	Fractured.HealthQ = 17;
	Fractured.Variant = 3;
	Fractured.LastSeed = 0xDEADBEEF;
	Fractured.LastImpulse[0] = -15000;
	Fractured.LastImpulse[2] = 321;
	Fractured.LastLocation[1] = -1200;
	Fractured.StateTimeMs = 3600000;
	Fractured.Epoch = 65535;
	FVersePieceItem Repairing = Fractured;
	Repairing.State = EVersePieceState::Repairing;
	Repairing.RepairFrom = EVersePieceState::Destroyed;
	FVersePieceItem Reset;
	Reset.PieceIndex = 5;
	Reset.StateTimeMs = 99;
	Reset.Epoch = 2;

	int32 FracturedBits = 0;
	int32 RepairingBits = 0;
	int32 ResetBits = 0;
	TestTrue(TEXT("fractured item round-trips"), SameItem(RoundTrip(Fractured, FracturedBits), Fractured));
	TestTrue(TEXT("repairing item round-trips"), SameItem(RoundTrip(Repairing, RepairingBits), Repairing));
	TestTrue(TEXT("reset item round-trips"), SameItem(RoundTrip(Reset, ResetBits), Reset));
	AddInfo(FString::Printf(TEXT("wire bits: fractured %d, repairing %d, reset %d"), FracturedBits, RepairingBits, ResetBits));
	TestEqual(TEXT("fractured item: 26 bytes measured"), FVersePieceItem::MeasureWireBytes(Fractured), (FracturedBits + 7) / 8);
	TestTrue(TEXT("a fractured item is at most 26 bytes"), FVersePieceItem::MeasureWireBytes(Fractured) <= 26);
	TestTrue(TEXT("a reset item is at most 10 bytes"), FVersePieceItem::MeasureWireBytes(Reset) <= 10);
	TestEqual(TEXT("RepairFrom costs 3 bits only while Repairing"), RepairingBits - FracturedBits, 3);
	return true;
}

// destruction.md 4 and 6.1 through the real manager: several hits on one piece in one frame leave
// one event, and damage calls never hand nav tiles over by themselves.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionNetManagerTick, "Verse.Destruction.Net.ManagerTick", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionNetManagerTick::RunTest(const FString&)
{
	FTestWorld W(TEXT("VerseDestructionManagerTick"));
	const TArray<FVersePieceDef> Defs = ContainerRow(24);
	for (const FVersePieceDef& Def : Defs)
	{
		W.SpawnPiece(Def);
	}
	AVerseDestructionManager* Manager = W.SpawnManager(false);
	UVerseEventHub* Hub = UVerseEventHub::Get(W.World);
	if (!TestNotNull(TEXT("event hub"), Hub))
	{
		return false;
	}
	TArray<FVerseFractureEvent> Events;
	const FDelegateHandle Handle = Hub->OnFracture.AddLambda([&Events](const FVerseFractureEvent& E) { Events.Add(E); });

	// One frame: a breach on piece 0 plus five bolts into it.
	FVersePieceDamage B = Breach(Manager->GetSim().GetDef(0));
	B.PieceIndex = 0;
	B.BreachRadiusCm = 1.f;
	Manager->GetPieceDamage().ApplyPieceDamage(B);
	for (int32 Shot = 0; Shot < 5; ++Shot)
	{
		FVersePieceDamage D = Bolt(Manager->GetSim().GetDef(0), 30.f);
		D.PieceIndex = 0;
		Manager->GetPieceDamage().ApplyPieceDamage(D);
	}
	TestTrue(TEXT("the state is live at once on the server"), Manager->GetPieceState(0) != EVersePieceState::Intact);
	TestEqual(TEXT("no event before the tick"), Events.Num(), 0);
	// Same frame: breach every other piece too (many damage calls, many dirty tiles).
	for (int32 Index = 1; Index < Defs.Num(); ++Index)
	{
		FVersePieceDamage D = Breach(Manager->GetSim().GetDef(uint16(Index)));
		D.PieceIndex = uint16(Index);
		D.BreachRadiusCm = 1.f;
		Manager->GetPieceDamage().ApplyPieceDamage(D);
	}
	TestEqual(TEXT("damage calls hand no nav tile over"), Manager->GetNavTilesInFlight(), 0);
	Manager->Tick(0.f);
	const int32 OnPiece0 = Events.FilterByPredicate([](const FVerseFractureEvent& E) { return E.PieceIndex == 0; }).Num();
	TestEqual(TEXT("one event for piece 0 this tick (coalesced)"), OnPiece0, 1);
	TestTrue(TEXT("at most 4 nav tiles after the tick"), Manager->GetNavTilesInFlight() <= 4);
	TestTrue(TEXT("tiles are still queued"), Manager->GetSim().GetNav().NumQueued() > 0);
	for (int32 Tick = 0; Tick < 200 && Manager->GetSim().GetNav().NumQueued() > 0; ++Tick)
	{
		Manager->Tick(0.f);
		TestTrue(TEXT("never more than 4 in flight"), Manager->GetNavTilesInFlight() <= 4);
	}
	TestEqual(TEXT("the queue drains tick by tick"), Manager->GetSim().GetNav().NumQueued(), 0);
	TestTrue(TEXT("peak in flight at most 4"), Manager->GetPeakNavTilesInFlight() <= 4);
	Hub->OnFracture.Remove(Handle);
	return true;
}

// destruction.md 8: a piece that streams in after the manager registered takes its manifest slot
// and shows the replicated state at once; one that streams out leaves it.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionNetStreaming, "Verse.Destruction.Net.StreamingRegister", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionNetStreaming::RunTest(const FString&)
{
	FTestWorld W(TEXT("VerseDestructionStreaming"));
	const TArray<FVersePieceDef> Defs = ContainerRow(6);
	UVersePieceManifest* Manifest = NewObject<UVersePieceManifest>();
	for (const FVersePieceDef& Def : Defs)
	{
		Manifest->PieceGuids.Add(Def.Guid); // server order
	}
	// Only the first four are loaded when the client manager registers.
	for (int32 Index = 0; Index < 4; ++Index)
	{
		W.SpawnPiece(Defs[Index]);
	}
	AVerseDestructionManager* Client = W.SpawnManager(true, 0, Manifest);
	TestFalse(TEXT("manifest present: the client registers"), Client->IsMissingClientManifest());
	TestEqual(TEXT("every manifest slot exists"), Client->NumPieces(), 6);
	TestNull(TEXT("slot 5 is not loaded yet"), Client->GetPieceActor(5));
	FVersePieceItem Item;
	Item.PieceIndex = 5;
	Item.State = EVersePieceState::Destroyed;
	Client->ReceiveItemsForTest(MakeArrayView(&Item, 1), true);
	TestEqual(TEXT("the client knows the state of an unloaded piece"), Client->GetPieceState(5), EVersePieceState::Destroyed);

	AVerseDestructible* Late = W.SpawnPiece(Defs[5]);
	Client->RegisterPiece(*Late);
	TestTrue(TEXT("the late piece takes slot 5"), Client->GetPieceActor(5) == Late && Late->GetPieceIndex() == 5);
	TestEqual(TEXT("and shows the replicated state at once"), Late->GetPresentedState(), EVersePieceState::Destroyed);
	Item.State = EVersePieceState::Repairing;
	Item.RepairFrom = EVersePieceState::Destroyed;
	Client->ReceiveItemsForTest(MakeArrayView(&Item, 1), false);
	TestEqual(TEXT("then follows the items"), Late->GetPresentedState(), EVersePieceState::Repairing);
	Client->UnregisterPiece(*Late);
	TestNull(TEXT("streamed out: the slot is empty"), Client->GetPieceActor(5));
	TestEqual(TEXT("the state stays"), Client->GetPieceState(5), EVersePieceState::Repairing);
	return true;
}

// destruction.md 10: the burst is the largest authored set that fits the grant, and the budget
// is charged with the bodies really spawned.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionDebrisSets, "Verse.Destruction.Debris.Sets", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionDebrisSets::RunTest(const FString&)
{
	TestEqual(TEXT("largest set within the grant"), UVerseDebrisSubsystem::PickSet(TArray<int32>{6, 12, 40}, 12), 1);
	TestEqual(TEXT("a full set over the grant is never taken"), UVerseDebrisSubsystem::PickSet(TArray<int32>{40}, 12), INDEX_NONE);
	TestEqual(TEXT("empty sets never count"), UVerseDebrisSubsystem::PickSet(TArray<int32>{0, 3}, 12), 1);
	TestEqual(TEXT("no sets, no burst"), UVerseDebrisSubsystem::PickSet(TArray<int32>(), 40), INDEX_NONE);

	FVerseDebrisBudget Budget;
	FVerseDebrisBudget::FRequest Request;
	Request.Type = EVerseDebrisType::MetalShards;
	Request.ToState = EVersePieceState::Holed;
	const FVerseDebrisBudget::FGrant Grant = Budget.Request(Request, 0.0);
	TestEqual(TEXT("Holed sheet metal reserves 12"), Grant.Bodies, 12);
	Budget.Commit(Grant.BurstId, 7);
	TestEqual(TEXT("the budget counts the 7 real bodies"), Budget.ActiveBodies(), 7);
	TestEqual(TEXT("real peak"), Budget.GetPeakRealBodies(), 7);
	const FVerseDebrisBudget::FGrant Second = Budget.Request(Request, 0.1);
	Budget.Commit(Second.BurstId, 0);
	TestEqual(TEXT("nothing spawned frees the reservation"), Budget.ActiveBodies(), 7);
	TestEqual(TEXT("and the actor slot"), Budget.AliveActors(), 1);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

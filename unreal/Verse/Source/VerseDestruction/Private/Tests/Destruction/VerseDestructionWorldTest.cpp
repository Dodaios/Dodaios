#include "Tests/Destruction/VerseDestructionTestUtil.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Algo/Reverse.h"
#include "Debris/VerseDebrisSubsystem.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VerseDestructionManager.h"
#include "Pieces/VersePieceManifest.h"
#include "Repair/VerseRepairDrone.h"
#include "VerseGameplayTags.h"

using namespace VerseDestructionTest;

namespace
{
	TArray<FVersePieceDef> SmallArena()
	{
		TArray<FVersePieceDef> Defs;
		const EVersePieceClass Classes[] = {EVersePieceClass::WallPanel, EVersePieceClass::CladdingWall, EVersePieceClass::ContainerWall,
			EVersePieceClass::GlassPane, EVersePieceClass::CatwalkSegment, EVersePieceClass::CeilingPanel};
		for (int32 Index = 0; Index < 30; ++Index)
		{
			const EVersePieceClass Class = Classes[Index % 6];
			const double Z = Class == EVersePieceClass::CatwalkSegment ? 300.0 : (Class == EVersePieceClass::CeilingPanel ? 600.0 : 0.0);
			Defs.Add(MakePiece(Class, FVector((Index % 6) * 260.0, (Index / 6) * 400.0, Z), 100 + Index));
		}
		return Defs;
	}

	/** Seeded mix of bolts, melee and breach charges on random pieces. */
	void RandomChanges(AVerseDestructionManager& Server, int32 MinChanges, uint64 Seed, FTestWorld& World)
	{
		FVerseRng Rng(Seed);
		int32 Guard = 20000;
		while (Server.GetSim().GetCounters().StateChanges < MinChanges && Guard-- > 0)
		{
			const int32 Index = Rng.RangeInt(0, Server.NumPieces() - 1);
			const FVersePieceDef& Def = Server.GetSim().GetDef(uint16(Index));
			const FBox Box = Def.IntactBounds;
			const FVector Local(Rng.Range(Box.Min.X, Box.Max.X), Box.Min.Y - 1.0, Rng.Range(Box.Min.Z, Box.Max.Z));
			const double Roll = Rng.NextUnit();
			FVersePieceDamage Damage = Roll < 0.85 ? Bolt(Def, 10.f, Local) : (Roll < 0.95 ? Melee(Def) : Breach(Def, Local));
			Damage.PieceIndex = uint16(Index);
			Server.GetPieceDamage().ApplyPieceDamage(Damage);
			World.Advance(0.05f);
			if (Rng.Chance(0.02))
			{
				// A lull longer than the 60 s repair delay: drones fly out and repair in between.
				for (int32 Step = 0; Step < 8; ++Step)
				{
					World.Advance(12.f);
					Server.Tick(0.05f);
				}
			}
		}
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionWorld, "Verse.Destruction.World.ManagerAndPieces", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionWorld::RunTest(const FString&)
{
	FTestWorld W(TEXT("VerseDestructionWorld"));
	const TArray<FVersePieceDef> Defs = SmallArena();
	for (const FVersePieceDef& Def : Defs)
	{
		W.SpawnPiece(Def);
	}
	AVerseDestructionManager* Manager = W.SpawnManager(false, 2);
	TestEqual(TEXT("every piece registered"), Manager->NumPieces(), Defs.Num());
	TestTrue(TEXT("found through the world"), AVerseDestructionManager::Get(W.World) == Manager);
	// Manifest order is GUID order, and the pieces know their index.
	TArray<FGuid> Guids;
	for (const FVersePieceDef& Def : Defs)
	{
		Guids.Add(Def.Guid);
	}
	UVersePieceManifest::SortGuids(Guids);
	for (int32 Index = 0; Index < Guids.Num(); ++Index)
	{
		const AVerseDestructible* Piece = Manager->GetPieceActor(uint16(Index));
		TestTrue(FString::Printf(TEXT("index %d in GUID order"), Index), Piece && Piece->GetPieceGuid() == Guids[Index] && Piece->GetPieceIndex() == Index);
	}

	UVerseEventHub* Hub = UVerseEventHub::Get(W.World);
	TArray<FVerseFractureEvent> Fractures;
	TArray<FVerseNoiseEvent> Noises;
	if (!TestNotNull(TEXT("event hub"), Hub))
	{
		return false;
	}
	const FDelegateHandle A = Hub->OnFracture.AddLambda([&Fractures](const FVerseFractureEvent& E) { Fractures.Add(E); });
	const FDelegateHandle B = Hub->OnNoise.AddLambda([&Noises](const FVerseNoiseEvent& E) { Noises.Add(E); });

	// Find the glass pane and break it through the frozen damage interface.
	int32 GlassIndex = INDEX_NONE;
	for (int32 Index = 0; Index < Manager->NumPieces(); ++Index)
	{
		if (Manager->GetPieceMaterial(uint16(Index)) == EVersePenetrationMaterial::Glass)
		{
			GlassIndex = Index;
			break;
		}
	}
	AVerseDestructible* Glass = Manager->GetPieceActor(uint16(GlassIndex));
	if (!TestNotNull(TEXT("a glass pane"), Glass))
	{
		return false;
	}
	FVersePieceDamage Damage = Breach(Manager->GetSim().GetDef(uint16(GlassIndex)));
	Damage.PieceIndex = uint16(GlassIndex);
	IVersePieceDamage& Sink = Manager->GetPieceDamage();
	Sink.ApplyPieceDamage(Damage);
	Manager->Tick(0.f); // events, noise and nav go out once per server tick
	TestEqual(TEXT("IVersePieceQuery state"), Manager->GetPieceState(uint16(GlassIndex)), EVersePieceState::Destroyed);
	TestEqual(TEXT("the piece shows it"), Glass->GetPresentedState(), EVersePieceState::Destroyed);
	TestFalse(TEXT("destroyed glass has no gameplay bounds"), Manager->GetPieceBounds(uint16(GlassIndex)).IsValid != 0);
	TestTrue(TEXT("hub got the fracture"), Fractures.ContainsByPredicate([GlassIndex](const FVerseFractureEvent& E)
		{ return E.PieceIndex == GlassIndex && E.ToState == EVersePieceState::Destroyed; }));
	TestTrue(TEXT("hub got Noise.Fracture"), Noises.ContainsByPredicate([](const FVerseNoiseEvent& E) { return E.Noise == VerseTags::Noise_Fracture; }));
	TestTrue(TEXT("item replicated state"), Manager->FindItem(uint16(GlassIndex)) && Manager->FindItem(uint16(GlassIndex))->State == EVersePieceState::Destroyed);

	// Queries.
	const FBox All(FVector(-1e5), FVector(1e5));
	TestEqual(TEXT("GetPiecesInBox finds every piece"), Manager->GetPiecesInBox(All).Num(), Defs.Num());
	TestEqual(TEXT("an unknown piece is Intact"), Manager->GetPieceState(9999), EVersePieceState::Intact);
	TestFalse(TEXT("an unknown piece has no bounds"), Manager->GetPieceBounds(9999).IsValid != 0);

	// Reset on the arena switch, with the reset event on the hub.
	Manager->FullReset();
	Manager->Tick(0.f);
	TestEqual(TEXT("reset brings the glass back"), Manager->GetPieceState(uint16(GlassIndex)), EVersePieceState::Intact);
	TestEqual(TEXT("epoch bumped"), int32(Manager->GetEpoch()), 1);
	TestTrue(TEXT("reset event for all pieces"), Fractures.ContainsByPredicate([](const FVerseFractureEvent& E)
		{ return E.PieceIndex == Verse::Destruction::AllPieces && E.Cause == EVerseFractureCause::Reset; }));

	// No debris without a renderer (DR3); the subsystem exists but stays off.
	if (UVerseDebrisSubsystem* Debris = W.World->GetSubsystem<UVerseDebrisSubsystem>())
	{
		TestEqual(TEXT("no debris spawned headless"), Debris->GetSpawnedBursts(), 0);
	}
	Hub->OnFracture.Remove(A);
	Hub->OnNoise.Remove(B);
	return true;
}

// A6.2: a client joining after 200 changes builds the same proxy set as the server, 0 mismatches,
// without spawning debris.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionLateJoin, "Verse.Destruction.LateJoin", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionLateJoin::RunTest(const FString&)
{
	const TArray<FVersePieceDef> Defs = SmallArena();
	FTestWorld ServerWorld(TEXT("VerseDestructionServer"));
	for (const FVersePieceDef& Def : Defs)
	{
		ServerWorld.SpawnPiece(Def);
	}
	AVerseDestructionManager* Server = ServerWorld.SpawnManager(false, 3);
	RandomChanges(*Server, 200, 0xA62, ServerWorld);
	TestTrue(TEXT("at least 200 state changes"), Server->GetSim().GetCounters().StateChanges >= 200);

	FTestWorld ClientWorld(TEXT("VerseDestructionClient"));
	for (const FVersePieceDef& Def : Defs)
	{
		ClientWorld.SpawnPiece(Def);
	}
	AVerseDestructionManager* Client = ClientWorld.SpawnManager(true);
	TestFalse(TEXT("client has no authority"), Client->HasAuthority());
	int32 ClientFractures = 0;
	UVerseEventHub* Hub = UVerseEventHub::Get(ClientWorld.World);
	const FDelegateHandle Handle = Hub ? Hub->OnFracture.AddLambda([&ClientFractures](const FVerseFractureEvent&) { ++ClientFractures; }) : FDelegateHandle();

	// The late joiner receives the whole fast array (destruction.md 3.3).
	TArray<FVersePieceItem> Snapshot;
	for (int32 Index = 0; Index < Server->NumPieces(); ++Index)
	{
		Snapshot.Add(*Server->FindItem(uint16(Index)));
	}
	// Delivered in reverse order: the client must not depend on arrival order.
	Algo::Reverse(Snapshot);
	Client->ReceiveItemsForTest(Snapshot, true);

	int32 Mismatches = 0;
	int32 Broken = 0;
	for (int32 Index = 0; Index < Server->NumPieces(); ++Index)
	{
		const AVerseDestructible* S = Server->GetPieceActor(uint16(Index));
		const AVerseDestructible* C = Client->GetPieceActor(uint16(Index));
		if (!S || !C || S->GetPieceGuid() != C->GetPieceGuid() || S->GetPresentedState() != C->GetPresentedState()
			|| S->GetPresentedVariant() != C->GetPresentedVariant() || Server->GetPieceState(uint16(Index)) != Client->GetPieceState(uint16(Index)))
		{
			++Mismatches;
		}
		Broken += Server->GetPieceState(uint16(Index)) != EVersePieceState::Intact ? 1 : 0;
	}
	TestEqual(TEXT("0 proxy mismatches between server and late joiner"), Mismatches, 0);
	TestTrue(TEXT("the join saw broken pieces"), Broken > 0);
	TestEqual(TEXT("the join raised no fracture event (no debris)"), ClientFractures, 0);
	if (UVerseDebrisSubsystem* Debris = ClientWorld.World->GetSubsystem<UVerseDebrisSubsystem>())
	{
		TestEqual(TEXT("no debris spawned on join"), Debris->GetSpawnedBursts(), 0);
	}
	if (Hub)
	{
		Hub->OnFracture.Remove(Handle);
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

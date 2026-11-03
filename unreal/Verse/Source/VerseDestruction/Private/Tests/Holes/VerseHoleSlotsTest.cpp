#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "GameFramework/Actor.h"
#include "Holes/VerseBoltHoleComponent.h"
#include "Holes/VerseHoleGlow.h"
#include "Holes/VerseHoleRenderComponent.h"
#include "Misc/AutomationTest.h"
#include "Tests/Penetration/Fakes/VerseWP03Fakes.h"

namespace
{
	constexpr EAutomationTestFlags WP03Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	FVector SlotPoint(int32 I)
	{
		return FVector(0.0, -40.0 + 3.0 * (I % 25), -30.0 + 3.0 * (I / 25));
	}

	TArray<uint32> Sequences(const UVerseBoltHoleComponent& Holes)
	{
		TArray<uint32> Out;
		for (const FVerseBoltHoleSlot& Slot : Holes.GetSlots())
		{
			Out.Add(Slot.Sequence);
		}
		return Out;
	}
}

// WP03.5 replication shape (destruction.md 3.3 and 5, interim for CCR #1134): holes sit at
// stable slot indices, so an eviction rewrites one slot and shifts nothing; the per-piece view
// and the change notification name only the pieces that changed.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHoleSlotsTest, "Verse.Destruction.Holes.Slots", WP03Flags)

bool FVerseHoleSlotsTest::RunTest(const FString& Parameters)
{
	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	UVerseBoltHoleComponent* Holes = W.Holes;
	TArray<uint16> Changed;
	int32 AllChanges = 0;
	Holes->OnHolesChanged.AddLambda([&](TConstArrayView<uint16> Pieces, bool bAll) {
		Changed.Append(Pieces.GetData(), Pieces.Num());
		AllChanges += bAll ? 1 : 0;
	});

	// Fill the arena to its cap over 22 pieces.
	uint32 Time = 1000;
	for (int32 I = 0; I < 512; ++I)
	{
		Holes->AddHole(uint16(I % 22), EVersePenetrationMaterial::Glass, SlotPoint(I / 22), FVector::ForwardVector, 15, Time++);
	}
	TestEqual(TEXT("512 holes"), Holes->Num(), 512);
	TestEqual(TEXT("512 slots"), Holes->GetSlots().Num(), 512);

	// At the cap every new hole evicts one: exactly two slots change (the evicted one is reused),
	// nothing shifts and the slot array does not grow.
	for (int32 Round = 0; Round < 50; ++Round)
	{
		const TArray<uint32> Before = Sequences(*Holes);
		Changed.Reset();
		Holes->AddHole(uint16(40 + Round % 3), EVersePenetrationMaterial::Glass, SlotPoint(Round), FVector::ForwardVector, 15, Time++);
		const TArray<uint32> After = Sequences(*Holes);
		int32 Diff = 0;
		for (int32 I = 0; I < FMath::Min(Before.Num(), After.Num()); ++I)
		{
			Diff += Before[I] != After[I] ? 1 : 0;
		}
		if (Diff != 1 || After.Num() != 512)
		{
			AddError(FString::Printf(TEXT("round %d: %d slots changed, %d slots (want 1 and 512)"), Round, Diff, After.Num()));
			break;
		}
		if (!Changed.Contains(uint16(40 + Round % 3)) || Changed.Num() > 2)
		{
			AddError(FString::Printf(TEXT("round %d: change named %d pieces"), Round, Changed.Num()));
			break;
		}
	}
	TestEqual(TEXT("arena stays at 512"), Holes->Num(), 512);

	// The per-piece view stays oldest first and matches the slots.
	TArray<FVerseBoltHole> All;
	Holes->GetAllHoles(All);
	TestEqual(TEXT("every live slot listed"), All.Num(), 512);
	bool bOrdered = true;
	for (int32 I = 1; I < All.Num(); ++I)
	{
		bOrdered &= All[I - 1].ServerTimeMs < All[I].ServerTimeMs;
	}
	TestTrue(TEXT("all holes oldest first"), bOrdered);
	int32 Sum = 0;
	for (uint16 Piece = 0; Piece < 64; ++Piece)
	{
		const TConstArrayView<FVerseBoltHole> PieceHoles = Holes->GetPieceHoles(Piece);
		Sum += PieceHoles.Num();
		for (int32 I = 1; I < PieceHoles.Num(); ++I)
		{
			bOrdered &= PieceHoles[I - 1].ServerTimeMs < PieceHoles[I].ServerTimeMs;
		}
	}
	TestEqual(TEXT("per-piece views add up"), Sum, 512);
	TestTrue(TEXT("per-piece views oldest first"), bOrdered);

	// A clear frees the piece's slots; the next holes reuse them without growing the array.
	const int32 OnPiece3 = Holes->NumOnPiece(3);
	Holes->ClearPiece(3);
	TestEqual(TEXT("clear frees the piece"), Holes->Num(), 512 - OnPiece3);
	for (int32 I = 0; I < OnPiece3; ++I)
	{
		Holes->AddHole(50, EVersePenetrationMaterial::Glass, SlotPoint(I), FVector::ForwardVector, 15, Time++);
	}
	TestEqual(TEXT("freed slots reused"), Holes->GetSlots().Num(), 512);
	Holes->ResetAll(2);
	TestEqual(TEXT("reset empties the slots"), Holes->GetSlots().Num(), 0);
	TestEqual(TEXT("reset notifies everything"), AllChanges, 1);
	return true;
}

// WP03.6 glow clock: records carry server time, so the glow ages against the server clock, and a
// client clock behind the server never lights recent holes as fresh (destruction.md 3.3: late
// joiners see holes already cooled). Each change redraws only the pieces it touched.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHoleClockTest, "Verse.Destruction.Holes.Clock", WP03Flags)

bool FVerseHoleClockTest::RunTest(const FString& Parameters)
{
	TestTrue(TEXT("a past record ages"), VerseWP03Test::Near(VerseHoleGlow::AgeS(1000, 2500), 1.5, 1e-6));
	TestTrue(TEXT("a record within the skew window is fresh"), VerseHoleGlow::AgeS(2600, 2500) == 0.f);
	TestTrue(TEXT("a record far in the future is long cooled"), VerseHoleGlow::AgeS(60000, 2500) >= VerseHoleGlow::DefaultEndS);

	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	UVerseHoleRenderComponent* Render = NewObject<UVerseHoleRenderComponent>(W.Manager, TEXT("HoleRender"));
	Render->RegisterComponent();
	const uint32 WorldMs = Render->CurrentTimeMs();
	TestTrue(TEXT("default clock: the world (no game state in this world)"),
		WorldMs == uint32(W.World()->GetTimeSeconds() * 1000.0));

	// A late joiner: the server is at 120 s, the client clock still at 2 s.
	uint32 ClientNow = 2000;
	Render->SetServerTimeSource([&ClientNow]() { return ClientNow; });
	Render->SetHoleSource(W.Holes);
	const FBox Bounds(FVector(-0.2, -100, -50), FVector(0.2, 100, 50));
	for (uint16 Piece = 0; Piece < 6; ++Piece)
	{
		Render->RegisterPieceVisual(Piece, nullptr, Bounds, W.Manager->GetRootComponent());
	}
	for (int32 I = 0; I < 60; ++I)
	{
		W.Holes->AddHole(uint16(I % 6), EVersePenetrationMaterial::Glass, SlotPoint(I / 6), FVector::ForwardVector, 15, 118000 + I * 30);
	}
	Render->Sync();
	TestEqual(TEXT("client clock behind: none of the recent server holes glows"), Render->NumGlowing(), 0);
	W.Holes->AddHole(0, EVersePenetrationMaterial::Glass, SlotPoint(20), FVector::ForwardVector, 15, ClientNow + 100);
	Render->Sync();
	TestEqual(TEXT("a hole within the skew window glows"), Render->NumGlowing(), 1);
	ClientNow = 120000;
	Render->Sync();
	TestTrue(TEXT("once the clocks agree the young holes glow"), Render->NumGlowing() > 0);

	// Incremental: one new hole redraws one mask and places one slot.
	const int32 Redraws = Render->NumMaskRedraws();
	const int32 Updates = Render->NumSlotUpdates();
	W.Holes->AddHole(4, EVersePenetrationMaterial::Glass, SlotPoint(21), FVector::ForwardVector, 15, ClientNow);
	Render->Sync();
	TestEqual(TEXT("one change redraws one piece mask"), Render->NumMaskRedraws() - Redraws, 1);
	TestEqual(TEXT("one change places one slot"), Render->NumSlotUpdates() - Updates, 1);
	TestEqual(TEXT("slots follow the records"), Render->NumHoleSlots(), W.Holes->Num());
	W.Holes->ClearPiece(5);
	Render->Sync();
	TestEqual(TEXT("a clear redraws that piece only"), Render->NumMaskRedraws() - Redraws, 2);
	TestEqual(TEXT("slots follow the clear"), Render->NumHoleSlots(), W.Holes->Num());
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

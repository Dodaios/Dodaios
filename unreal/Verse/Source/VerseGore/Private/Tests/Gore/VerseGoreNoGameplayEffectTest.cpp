#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Tests/Gore/Fakes/FakeGoreDuel.h"

using namespace VerseGoreTest;

namespace VerseGoreD6
{
	/** 10 minutes at 30 Hz (A5.1). */
	constexpr int32 Ticks = 10 * 60 * 30;

	enum class EMode : uint8 { Off, Full, Reduced };

	TArray<uint32> Run(EMode Mode, uint32 Seed, FVerseGoreBudget& OutBudget, int32& OutQueries)
	{
		FWorld W(Mode != EMode::Off, TEXT("VerseGoreD6World"));
		TArray<uint32> Hashes;
		if (!W.IsValid())
		{
			return Hashes;
		}
		W.AddRoom(900.0);
		W.AddBox(FVector(-900.0, 0.0, 200.0), FVector(20.0, 2000.0, 400.0));
		W.Gore->SetGoreLevel(Mode == EMode::Reduced ? EVerseGoreLevel::Reduced : EVerseGoreLevel::Full);
		W.Gore->SetForceActive(Mode != EMode::Off);
		FFakeGoreDuel Duel(W, Seed);
		Hashes.Reserve(Ticks);
		for (int32 Tick = 0; Tick < Ticks; ++Tick)
		{
			Duel.Step(1.0 / 30.0);
			W.Gore->AdvanceTime(1.f / 30.f);
			Hashes.Add(Duel.StateHash());
		}
		OutBudget = W.Gore->GetBudget();
		OutQueries = Duel.Queries;
		return Hashes;
	}
}

// A5.1 / D6: gore never changes a replicated gameplay value. Runs the fake duel (until WP10's
// bot-vs-bot harness lands) three times from one seed: gore off, Full, Reduced.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreNoGameplayEffectTest, "Verse.Gore.NoGameplayEffect", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreNoGameplayEffectTest::RunTest(const FString&)
{
	using namespace VerseGoreD6;
	const uint32 Seed = 0xD6u;
	FVerseGoreBudget OffBudget, FullBudget, ReducedBudget;
	int32 OffQueries = 0, FullQueries = 0, ReducedQueries = 0;
	const TArray<uint32> Off = Run(EMode::Off, Seed, OffBudget, OffQueries);
	const TArray<uint32> Full = Run(EMode::Full, Seed, FullBudget, FullQueries);
	const TArray<uint32> Reduced = Run(EMode::Reduced, Seed, ReducedBudget, ReducedQueries);
	// The fake's gameplay traces VerseBolt, VerseHitBody and VerseSight through the gore every tick.
	TestTrue(FString::Printf(TEXT("gameplay queried the world (%d traces per run)"), FullQueries), FullQueries > Ticks * 6);
	if (!TestEqual(TEXT("every run produced every tick"), Full.Num(), Ticks) || Off.Num() != Ticks || Reduced.Num() != Ticks)
	{
		return false;
	}

	int32 FirstFullMismatch = INDEX_NONE, FirstReducedMismatch = INDEX_NONE, FullVsReduced = 0;
	for (int32 Tick = 0; Tick < Ticks; ++Tick)
	{
		if (FirstFullMismatch == INDEX_NONE && Full[Tick] != Off[Tick])
		{
			FirstFullMismatch = Tick;
		}
		if (FirstReducedMismatch == INDEX_NONE && Reduced[Tick] != Off[Tick])
		{
			FirstReducedMismatch = Tick;
		}
		FullVsReduced += Full[Tick] != Reduced[Tick] ? 1 : 0;
	}
	TestEqual(TEXT("Full: state hash equals gore-off on every tick (first mismatch)"), FirstFullMismatch, int32(INDEX_NONE));
	TestEqual(TEXT("Reduced: state hash equals gore-off on every tick (first mismatch)"), FirstReducedMismatch, int32(INDEX_NONE));
	TestEqual(TEXT("Full and Reduced ticks that differ"), FullVsReduced, 0);

	// The run must have exercised gore, or the comparison proves nothing.
	TestTrue(FString::Printf(TEXT("Full drew gore (%d hits, %d decals, %d deaths)"), FullBudget.HitsHandled, FullBudget.DecalsSpawned, FullBudget.DeathsHandled),
		FullBudget.HitsHandled > 500 && FullBudget.DecalsSpawned > 100 && FullBudget.DeathsHandled > 10 && FullBudget.FinisherPhasesHandled > 0);
	TestTrue(TEXT("Reduced drew no blood"), ReducedBudget.HitsHandled == FullBudget.HitsHandled && ReducedBudget.DecalsSpawned == 0 && ReducedBudget.DropletsSpawned == 0);
	if (!UVerseGoreSubsystem::ProcessCanShowGore())
	{
		TestEqual(TEXT("gore off handled nothing"), OffBudget.HitsHandled, 0);
	}

	const FString Dir = ProofDir(TEXT("5.8"));
	IFileManager::Get().MakeDirectory(*Dir, true);
	FString Log = FString::Printf(TEXT("# Verse.Gore.NoGameplayEffect seed=0x%X ticks=%d hz=30 harness=FFakeGoreDuel traces_per_run=%d\n# tick off full reduced\n"), Seed, Ticks, FullQueries);
	for (int32 Tick = 0; Tick < Ticks; Tick += 1)
	{
		Log += FString::Printf(TEXT("%d %08x %08x %08x\n"), Tick, Off[Tick], Full[Tick], Reduced[Tick]);
	}
	Log += FString::Printf(TEXT("# full: hits=%d decals=%d deaths=%d finisher_phases=%d; reduced: hits=%d decals=%d flashes=%d; mismatches full=%d reduced=%d\n"),
		FullBudget.HitsHandled, FullBudget.DecalsSpawned, FullBudget.DeathsHandled, FullBudget.FinisherPhasesHandled,
		ReducedBudget.HitsHandled, ReducedBudget.DecalsSpawned, ReducedBudget.FlashesSpawned,
		FirstFullMismatch == INDEX_NONE ? 0 : 1, FirstReducedMismatch == INDEX_NONE ? 0 : 1);
	FFileHelper::SaveStringToFile(Log, *FPaths::Combine(Dir, TEXT("d6_hash.log")));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

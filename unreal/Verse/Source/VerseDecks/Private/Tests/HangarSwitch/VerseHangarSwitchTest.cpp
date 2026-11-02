#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Combat/VerseCombatTypes.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "HangarSwitch/VerseHangarSwitchSubsystem.h"

// Verse.Decks.HangarSwitch.*: the day/arena switch of work-packages.md WP11.8 (A11.4 timing on
// the switch side; the reset and crew halves are the listeners' tests). The data layers are a
// scripted fake so the state machine runs without LV_Hangar.

namespace VerseHangarSwitchTest
{
	/** Layers that finish `DoneAfterS` seconds after each request on the shared fake clock. */
	class FFakeHangarLayers : public IVerseHangarLayers
	{
	public:
		FFakeHangarLayers(const double* InClock, double InDoneAfterS, bool bInPresent = true)
			: Clock(InClock), DoneAfterS(InDoneAfterS), bPresent(bInPresent)
		{
		}

		virtual bool Request(bool bArena) override
		{
			++Requests;
			Target = bArena;
			RequestedAt = *Clock;
			return bPresent;
		}

		virtual bool IsDone(bool bArena) const override
		{
			return bArena == Target && *Clock - RequestedAt >= DoneAfterS;
		}

		const double* Clock;
		double DoneAfterS;
		bool bPresent;
		bool Target = false;
		double RequestedAt = 0.0;
		int32 Requests = 0;
	};

	struct FSwitchWorld
	{
		UWorld* World = nullptr;
		UVerseHangarSwitchSubsystem* Switch = nullptr;
		FFakeHangarLayers* Layers = nullptr;
		double Clock = 0.0;
		TArray<FVerseArenaSwitchEvent> Events;

		explicit FSwitchWorld(double DoneAfterS, bool bLayersPresent = true)
		{
			World = UWorld::CreateWorld(EWorldType::Game, false);
			FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
			Context.SetCurrentWorld(World);
			Switch = World->GetSubsystem<UVerseHangarSwitchSubsystem>();
			if (Switch)
			{
				TUniquePtr<FFakeHangarLayers> Fake = MakeUnique<FFakeHangarLayers>(&Clock, DoneAfterS, bLayersPresent);
				Layers = Fake.Get();
				Switch->SetLayers(MoveTemp(Fake));
				Switch->SetClock([this]() { return Clock; });
			}
			if (UVerseEventHub* Hub = UVerseEventHub::Get(World))
			{
				Hub->OnArenaSwitch.AddLambda([this](const FVerseArenaSwitchEvent& E) { Events.Add(E); });
			}
		}

		~FSwitchWorld()
		{
			GEngine->DestroyWorldContext(World);
			World->DestroyWorld(false);
		}

		/** Advances the fake clock in 60 Hz frames until `Seconds` passed. */
		void Run(double Seconds)
		{
			const int32 Frames = FMath::CeilToInt(Seconds * 60.0);
			for (int32 i = 0; i < Frames; ++i)
			{
				Clock += 1.0 / 60.0;
				Switch->Step();
			}
		}
	};
}

using namespace VerseHangarSwitchTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHangarSwitchToggleTest, "Verse.Decks.HangarSwitch.Toggle",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseHangarSwitchToggleTest::RunTest(const FString& Parameters)
{
	FSwitchWorld W(0.0);
	if (!TestNotNull(TEXT("switch subsystem exists in a game world"), W.Switch))
	{
		return false;
	}
	TestTrue(TEXT("starts as the day deck"), W.Switch->GetMode() == EVerseHangarMode::Day);
	TestTrue(TEXT("arena on accepted"), W.Switch->RequestArena(true));
	TestTrue(TEXT("arena on"), W.Switch->IsArenaOn());
	TestEqual(TEXT("one event"), W.Events.Num(), 1);
	if (W.Events.Num() == 1)
	{
		TestTrue(TEXT("event says arena on"), W.Events[0].bArenaOn);
		TestTrue(TEXT("event names the hangar"), W.Events[0].Deck == FName(TEXT("hangar")));
	}
	TestFalse(TEXT("arena on again changes nothing"), W.Switch->RequestArena(true));
	TestEqual(TEXT("still one event"), W.Events.Num(), 1);
	TestTrue(TEXT("back to day accepted"), W.Switch->RequestArena(false));
	TestTrue(TEXT("day again"), W.Switch->GetMode() == EVerseHangarMode::Day);
	TestEqual(TEXT("two events"), W.Events.Num(), 2);
	TestTrue(TEXT("second event says arena off"), W.Events.Num() == 2 && !W.Events[1].bArenaOn);
	TestEqual(TEXT("layers asked twice"), W.Layers->Requests, 2);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHangarSwitchStreamingTest, "Verse.Decks.HangarSwitch.WaitsForStreaming",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// The event comes only once the layers are streamed, so the listeners never reset a half-loaded
// arena; a 1.2 s stream gives a switch time of 1.2 s, under the 2.0 s budget of A11.4.
bool FVerseHangarSwitchStreamingTest::RunTest(const FString& Parameters)
{
	FSwitchWorld W(1.2);
	if (!TestNotNull(TEXT("switch subsystem"), W.Switch))
	{
		return false;
	}
	W.Switch->RequestArena(true);
	TestTrue(TEXT("switching while streaming"), W.Switch->IsSwitching());
	W.Run(1.0);
	TestEqual(TEXT("no event before the layers are done"), W.Events.Num(), 0);
	W.Run(0.3);
	TestEqual(TEXT("event once done"), W.Events.Num(), 1);
	TestTrue(TEXT("arena on"), W.Switch->IsArenaOn());
	const float Took = W.Switch->GetLastSwitchSeconds();
	TestTrue(FString::Printf(TEXT("switch took %.3f s, within one frame of the stream"), Took), Took >= 1.2f && Took <= 1.2f + 1.f / 60.f + 1e-3f);
	TestTrue(TEXT("within the 2.0 s budget"), Took <= UVerseHangarSwitchSubsystem::SwitchBudgetS);

	W.Switch->RequestArena(false);
	W.Run(1.3);
	TestTrue(TEXT("day again"), W.Switch->GetMode() == EVerseHangarMode::Day);
	TestTrue(TEXT("back within budget"), W.Switch->GetLastSwitchSeconds() <= UVerseHangarSwitchSubsystem::SwitchBudgetS);

	// A request against a running switch is queued, not dropped.
	W.Switch->RequestArena(true);
	W.Run(0.5);
	TestTrue(TEXT("queued while switching"), W.Switch->RequestArena(false));
	W.Run(1.0);
	TestTrue(TEXT("arena reached first"), W.Events.Num() >= 3 && W.Events[2].bArenaOn);
	W.Run(1.5);
	TestTrue(TEXT("then day"), W.Switch->GetMode() == EVerseHangarMode::Day && W.Events.Num() == 4 && !W.Events[3].bArenaOn);

	// Stuck layers finish after the timeout instead of hanging the duel.
	AddExpectedMessage(TEXT("layers not done after"), EAutomationExpectedMessageFlags::Contains, 1);
	AddExpectedMessage(TEXT("Hangar switch took"), EAutomationExpectedMessageFlags::Contains, 1);
	FSwitchWorld Stuck(1e9);
	Stuck.Switch->RequestArena(true);
	Stuck.Run(UVerseHangarSwitchSubsystem::SwitchTimeoutS + 0.5);
	TestTrue(TEXT("stuck layers time out"), Stuck.Switch->IsArenaOn() && Stuck.Events.Num() == 1);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHangarSwitchQuickStartTest, "Verse.Decks.HangarSwitch.QuickStart",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// lifecycle.show {reason: "quick_start_duel"} goes straight to the arena (bridge-protocol.md 12,
// parity D-03); any other reason leaves the deck as it is.
bool FVerseHangarSwitchQuickStartTest::RunTest(const FString& Parameters)
{
	FSwitchWorld W(0.0);
	if (!TestNotNull(TEXT("switch subsystem"), W.Switch))
	{
		return false;
	}
	TestFalse(TEXT("verse_view keeps the day deck"), W.Switch->HandleLifecycleShow(TEXT("verse_view")));
	TestFalse(TEXT("station keeps the day deck"), W.Switch->HandleLifecycleShow(TEXT("station")));
	TestTrue(TEXT("still day"), W.Switch->GetMode() == EVerseHangarMode::Day);
	TestTrue(TEXT("quick start accepted"), W.Switch->HandleLifecycleShow(UVerseHangarSwitchSubsystem::QuickStartReason));
	TestTrue(TEXT("arena on"), W.Switch->IsArenaOn());
	TestFalse(TEXT("second quick start is a no-op"), W.Switch->HandleLifecycleShow(UVerseHangarSwitchSubsystem::QuickStartReason));
	TestEqual(TEXT("one event"), W.Events.Num(), 1);

	// A world without the hangar layers still switches (and says so in the log).
	FSwitchWorld Bare(0.0, false);
	TestTrue(TEXT("no layers: accepted"), Bare.Switch->RequestArena(true));
	TestTrue(TEXT("no layers: arena on at once"), Bare.Switch->IsArenaOn() && Bare.Events.Num() == 1);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHangarSwitchBoundsTest, "Verse.Decks.HangarSwitch.ArenaBounds",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseHangarSwitchBoundsTest::RunTest(const FString& Parameters)
{
	const FBox Bounds = UVerseHangarSwitchSubsystem::ArenaBoundsCm();
	const FVector Size = Bounds.GetSize();
	TestTrue(TEXT("50 m wide"), FMath::IsNearlyEqual(Size.X, 5000.0));
	TestTrue(TEXT("40 m deep"), FMath::IsNearlyEqual(Size.Y, 4000.0));
	// Inside the 100 x 62 m hall (coordinates.md 3.1).
	TestTrue(TEXT("inside the hall"), Bounds.Min.X >= 0.0 && Bounds.Max.X <= 10000.0 && Bounds.Min.Y >= 0.0 && Bounds.Max.Y <= 6200.0);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

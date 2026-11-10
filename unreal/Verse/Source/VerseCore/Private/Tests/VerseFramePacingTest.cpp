#include "Misc/AutomationTest.h"
#include "VerseFramePacing.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFramePacingResolveTest, "Verse.Core.FramePacing.Resolve",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseFramePacingResolveTest::RunTest(const FString& Parameters)
{
	using FInputs = FVerseFramePacing::FInputs;

	FInputs Duel;
	Duel.bDuelRunning = true;
	TestEqual(TEXT("duel, unlimited, foreground: uncapped"), FVerseFramePacing::Resolve(Duel), 0.f);

	Duel.UserLimit = 144.f;
	TestEqual(TEXT("duel follows the person's limit"), FVerseFramePacing::Resolve(Duel), 144.f);

	FInputs Deck;
	TestEqual(TEXT("decks cap at DeckFps"), FVerseFramePacing::Resolve(Deck), FVerseFramePacing::DeckFps);
	Deck.UserLimit = 30.f;
	TestEqual(TEXT("a lower personal limit wins in decks"), FVerseFramePacing::Resolve(Deck), 30.f);

	FInputs Background = Duel;
	Background.bForeground = false;
	TestEqual(TEXT("background caps a duel"), FVerseFramePacing::Resolve(Background), FVerseFramePacing::BackgroundFps);

	FInputs Dormant = Duel;
	Dormant.LifecycleCap = 2.f;
	TestEqual(TEXT("dormant lifecycle cap wins"), FVerseFramePacing::Resolve(Dormant), 2.f);

	FInputs Stream = Duel;
	Stream.UserLimit = 0.f;
	Stream.StreamCap = 30.f;
	TestEqual(TEXT("panel stream caps"), FVerseFramePacing::Resolve(Stream), 30.f);
	return true;
}

#endif

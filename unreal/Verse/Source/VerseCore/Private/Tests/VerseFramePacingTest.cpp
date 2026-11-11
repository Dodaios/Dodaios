#include "Misc/AutomationTest.h"
#include "VerseFramePacing.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFramePacingResolveTest, "Verse.Core.FramePacing.Resolve",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseFramePacingResolveTest::RunTest(const FString& Parameters)
{
	using FInputs = FVerseFramePacing::FInputs;

	// Default: the display's refresh rate, in a duel and in the deck view alike.
	FInputs Play;
	Play.DisplayHz = 480.f;
	TestEqual(TEXT("foreground follows the display"), FVerseFramePacing::Resolve(Play), 480.f);
	Play.DisplayHz = 0.f;
	TestEqual(TEXT("unknown display: the fallback"), FVerseFramePacing::Resolve(Play), FVerseFramePacing::FallbackDisplayFps);

	FInputs Unlimited;
	Unlimited.User.bMatchDisplay = false;
	Unlimited.DisplayHz = 480.f;
	TestEqual(TEXT("unlimited, foreground: uncapped"), FVerseFramePacing::Resolve(Unlimited), 0.f);

	FInputs Fixed = Unlimited;
	Fixed.User.Fps = 144.f;
	TestEqual(TEXT("a fixed limit wins over the display"), FVerseFramePacing::Resolve(Fixed), 144.f);

	FInputs Background = Unlimited;
	Background.bForeground = false;
	TestEqual(TEXT("background caps"), FVerseFramePacing::Resolve(Background), FVerseFramePacing::BackgroundFps);
	Background.User.Fps = 20.f;
	TestEqual(TEXT("a lower personal limit wins in the background"), FVerseFramePacing::Resolve(Background), 20.f);

	FInputs Dormant = Play;
	Dormant.DisplayHz = 480.f;
	Dormant.LifecycleCap = 2.f;
	TestEqual(TEXT("dormant lifecycle cap wins"), FVerseFramePacing::Resolve(Dormant), 2.f);

	FInputs Panel = Play;
	Panel.DisplayHz = 480.f;
	Panel.LifecycleCap = 30.f;
	TestEqual(TEXT("panel lifecycle cap wins"), FVerseFramePacing::Resolve(Panel), 30.f);

	FInputs Stream = Unlimited;
	Stream.StreamCap = 30.f;
	TestEqual(TEXT("panel stream caps"), FVerseFramePacing::Resolve(Stream), 30.f);
	return true;
}

#endif

#include "Bot/VerseBotTier.h"
#include "Controller/VerseBotController.h"
#include "Misc/AutomationTest.h"
#include "Tests/Controller/Fakes/FakeVersePlayerState.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// 8.1: the controller's frozen surface: match option, player state identity, tier and adaptive.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotControllerIdentityTest, "Verse.Bot.Controller.Identity", VERSE_BOT_TEST_FLAGS)

bool FVerseBotControllerIdentityTest::RunTest(const FString& Parameters)
{
	TestEqual(TEXT("?BotTier=elite"), AVerseBotController::ParseBotTierOption(TEXT("?Listen?BotTier=elite")), FName(TEXT("elite")));
	TestEqual(TEXT("?BotTier=Adaptive (case)"), AVerseBotController::ParseBotTierOption(TEXT("?BotTier=Adaptive")), FName(TEXT("adaptive")));
	TestEqual(TEXT("unknown tier"), AVerseBotController::ParseBotTierOption(TEXT("?BotTier=nightmare")), FName(NAME_None));
	TestEqual(TEXT("no option"), AVerseBotController::ParseBotTierOption(TEXT("?Listen")), FName(NAME_None));

	FFakeVersePlayerStateFields Fields;
	TestTrue(TEXT("identity written"), AVerseBotController::WriteBotIdentity(FFakeVersePlayerStateFields::StaticStruct(), &Fields, TEXT("adaptive"), 0.62f));
	TestEqual(TEXT("BotTier"), Fields.BotTier, FName(TEXT("adaptive")));
	TestEqual(TEXT("BotEffectiveSkill"), Fields.BotEffectiveSkill, 0.62f);
	TestFalse(TEXT("a type without the fields is refused"), AVerseBotController::WriteBotIdentity(TBaseStructure<FVector>::Get(), &Fields, TEXT("hard"), 0.5f));

	// Tier and adaptive mode on a controller object (no world: no tick).
	AVerseBotController* Bot = NewObject<AVerseBotController>();
	UVerseBotTier* Elite = NewObject<UVerseBotTier>();
	UVerseBotTier::ApplyStartValues(TEXT("elite"), *Elite);
	Bot->SetTier(Elite);
	TestEqual(TEXT("elite skill is 1"), Bot->GetEffectiveSkill(), 1.f);
	TestFalse(TEXT("not adaptive"), Bot->IsAdaptive());
	Bot->SetAdaptive(true);
	TestTrue(TEXT("adaptive on"), Bot->IsAdaptive());
	TestEqual(TEXT("adaptive starts at StartSkill"), Bot->GetEffectiveSkill(), 0.5f);
	TestTrue(TEXT("brain ready"), Bot->GetBrain() != nullptr);
	TestEqual(TEXT("presentation starts in Search"), Bot->GetPresentation().State, EVerseBotState::Search);
	TestTrue(TEXT("presentation carries the Bot.State tag"), Bot->GetPresentation().StateTag.IsValid());
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "Misc/AutomationTest.h"
#include "Modules/ModuleManager.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Screens.Smoke: proves the module and every module it depends on are loaded
// (orchestration.md 0.2). "Automation RunTests Verse" runs one of these per module.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensSmokeTest, "Verse.Screens.Smoke",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseScreensSmokeTest::RunTest(const FString& Parameters)
{
	const TCHAR* Modules[] = {
		TEXT("VerseCore"),
		TEXT("VerseBridge"),
		TEXT("VerseDecks"),
		TEXT("VerseScreens"),
	};
	for (const TCHAR* Name : Modules)
	{
		TestTrue(FString::Printf(TEXT("module %s is loaded"), Name), FModuleManager::Get().IsModuleLoaded(Name));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

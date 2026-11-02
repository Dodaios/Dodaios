#include "Misc/AutomationTest.h"
#include "Modules/ModuleManager.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Harness.Smoke: proves the module and every module it depends on are loaded
// (orchestration.md 0.2). "Automation RunTests Verse" runs one of these per module.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessSmokeTest, "Verse.Harness.Smoke",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseHarnessSmokeTest::RunTest(const FString& Parameters)
{
	const TCHAR* Modules[] = {
		TEXT("Verse"),
		TEXT("VerseCore"),
		TEXT("VerseBridge"),
		TEXT("VerseMovement"),
		TEXT("VerseDestruction"),
		TEXT("VerseCombat"),
		TEXT("VerseGore"),
		TEXT("VerseDecks"),
		TEXT("VerseCrew"),
		TEXT("VerseScreens"),
		TEXT("VerseBot"),
		TEXT("VerseUI"),
		TEXT("VerseStream"),
		TEXT("VerseHarness"),
	};
	for (const TCHAR* Name : Modules)
	{
		TestTrue(FString::Printf(TEXT("module %s is loaded"), Name), FModuleManager::Get().IsModuleLoaded(Name));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

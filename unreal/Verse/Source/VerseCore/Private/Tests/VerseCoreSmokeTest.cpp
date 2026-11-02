#include "Misc/AutomationTest.h"
#include "Modules/ModuleManager.h"
#include "Combat/VerseCombatTypes.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Core.Smoke: proves the module and every module it depends on are loaded
// (orchestration.md 0.2). "Automation RunTests Verse" runs one of these per module.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoreSmokeTest, "Verse.Core.Smoke",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseCoreSmokeTest::RunTest(const FString& Parameters)
{
	const TCHAR* Modules[] = {
		TEXT("VerseCore"),
	};
	for (const TCHAR* Name : Modules)
	{
		TestTrue(FString::Printf(TEXT("module %s is loaded"), Name), FModuleManager::Get().IsModuleLoaded(Name));
	}

	// The enums the primary module and the combat stub need keep their frozen order.
	const UEnum* Phase = StaticEnum<EVerseCombatPhase>();
	if (TestNotNull(TEXT("EVerseCombatPhase is reflected"), Phase))
	{
		TestEqual(TEXT("EVerseCombatPhase entries"), Phase->NumEnums() - 1, 4);
		TestEqual(TEXT("EVerseCombatPhase::Alive is 0"), Phase->GetValueByNameString(TEXT("Alive")), int64(0));
	}
	const UEnum* Gore = StaticEnum<EVerseGoreLevel>();
	if (TestNotNull(TEXT("EVerseGoreLevel is reflected"), Gore))
	{
		TestEqual(TEXT("EVerseGoreLevel entries"), Gore->NumEnums() - 1, 2);
		TestEqual(TEXT("EVerseGoreLevel::Full is 0"), Gore->GetValueByNameString(TEXT("Full")), int64(0));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

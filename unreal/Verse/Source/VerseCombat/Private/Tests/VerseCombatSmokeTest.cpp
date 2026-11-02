#include "Misc/AutomationTest.h"
#include "Modules/ModuleManager.h"
#include "Damage/VerseCombatStateComponent.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Smoke: proves the module and every module it depends on are loaded
// (orchestration.md 0.2). "Automation RunTests Verse" runs one of these per module.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCombatSmokeTest, "Verse.Combat.Smoke",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseCombatSmokeTest::RunTest(const FString& Parameters)
{
	const TCHAR* Modules[] = {
		TEXT("VerseCore"),
		TEXT("VerseMovement"),
		TEXT("VerseDestruction"),
		TEXT("VerseCombat"),
	};
	for (const TCHAR* Name : Modules)
	{
		TestTrue(FString::Printf(TEXT("module %s is loaded"), Name), FModuleManager::Get().IsModuleLoaded(Name));
	}

	const UVerseCombatStateComponent* State = GetDefault<UVerseCombatStateComponent>();
	TestEqual(TEXT("combat state starts Alive"), State->Phase, EVerseCombatPhase::Alive);
	TestFalse(TEXT("spawn protection starts off"), State->bSpawnProtected);
	TestEqual(TEXT("spawn protection end starts at 0"), State->SpawnProtectedUntil, 0.f);
	TestTrue(TEXT("combat state replicates"), State->GetIsReplicated());
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

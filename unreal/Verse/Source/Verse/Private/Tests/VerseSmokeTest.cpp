#include "Misc/AutomationTest.h"
#include "Modules/ModuleManager.h"
#include "VerseDefaultCharacter.h"
#include "VerseDefaultGameMode.h"
#include "VerseDefaultPlayerController.h"
#include "VerseGameInstance.h"
#include "VerseSettings.h"
#include "Damage/VerseCombatStateComponent.h"
#include "GameMapsSettings.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Primary.Smoke: proves the module and every module it depends on are loaded
// (orchestration.md 0.2). "Automation RunTests Verse" runs one of these per module.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePrimarySmokeTest, "Verse.Primary.Smoke",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVersePrimarySmokeTest::RunTest(const FString& Parameters)
{
	const TCHAR* Modules[] = {
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
		TEXT("Verse"),
	};
	for (const TCHAR* Name : Modules)
	{
		TestTrue(FString::Printf(TEXT("module %s is loaded"), Name), FModuleManager::Get().IsModuleLoaded(Name));
	}

	const AVerseDefaultGameMode* Mode = GetDefault<AVerseDefaultGameMode>();
	TestTrue(TEXT("default pawn is AVerseDefaultCharacter"), Mode->DefaultPawnClass == AVerseDefaultCharacter::StaticClass());
	TestTrue(TEXT("default controller is AVerseDefaultPlayerController"), Mode->PlayerControllerClass == AVerseDefaultPlayerController::StaticClass());

	const AVerseDefaultCharacter* Pawn = GetDefault<AVerseDefaultCharacter>();
	const UVerseCombatStateComponent* CombatState = Pawn->GetCombatState();
	if (TestNotNull(TEXT("default pawn carries UVerseCombatStateComponent"), CombatState))
	{
		TestTrue(TEXT("pawn combat state replicates"), CombatState->GetIsReplicated());
		TestEqual(TEXT("pawn combat state starts Alive"), CombatState->Phase, EVerseCombatPhase::Alive);
	}

	const UGameMapsSettings* Maps = GetDefault<UGameMapsSettings>();
	TestEqual(TEXT("project game instance"), Maps->GameInstanceClass.GetAssetPathString(), UVerseGameInstance::StaticClass()->GetPathName());
	TestEqual(TEXT("project default game mode"), UGameMapsSettings::GetGlobalDefaultGameMode(), AVerseDefaultGameMode::StaticClass()->GetPathName());

	const UVerseSettings* Settings = GetDefault<UVerseSettings>();
	TestEqual(TEXT("gore defaults to full"), Settings->GoreLevel, EVerseGoreLevel::Full);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

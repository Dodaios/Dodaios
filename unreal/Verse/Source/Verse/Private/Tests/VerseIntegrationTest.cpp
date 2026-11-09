#include "Combat/VerseWeaponDefinition.h"
#include "Core/VerseUiSubsystem.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Damage/VerseHealthSet.h"
#include "Debris/VerseDebrisSubsystem.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "Gore/VerseGoreSubsystem.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Melee/VerseMeleeComponent.h"
#include "Misc/AutomationTest.h"
#include "Misc/ScopeExit.h"
#include "Rules/VerseGameMode.h"
#include "Rules/VersePlayerState.h"
#include "Settings/VerseUiSettings.h"
#include "VerseCharacter.h"
#include "VerseDefaultCharacter.h"
#include "VerseDefaultGameMode.h"
#include "VerseIntegrationSubsystem.h"
#include "VerseSettings.h"
#include "Weapons/VerseWeaponComponent.h"

#if WITH_DEV_AUTOMATION_TESTS

// Integration seams of the primary module (orchestration.md 2.1): the default classes are the
// real movement and combat classes, the loadout reaches a spawned pawn, and the change requests
// #1165 (view settings, live gore switch, kill cam fracture replay) are wired.

namespace VerseIntegrationTest
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	/** A standalone game world without begin play; destroyed with the scope. */
	struct FWorld
	{
		UWorld* World = nullptr;

		FWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseIntegrationTest")));
			FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
			Context.SetCurrentWorld(World);
		}

		~FWorld()
		{
			if (World)
			{
				World->BeginTearingDown();
				GEngine->DestroyWorldContext(World);
				World->DestroyWorld(false);
			}
		}
	};
}

using namespace VerseIntegrationTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePrimaryDefaultClassesTest, "Verse.Primary.DefaultClasses", Flags)
bool FVersePrimaryDefaultClassesTest::RunTest(const FString&)
{
	TestTrue(TEXT("default pawn derives from WP01 AVerseCharacter"), AVerseDefaultCharacter::StaticClass()->IsChildOf(AVerseCharacter::StaticClass()));
	TestTrue(TEXT("default game mode derives from AVerseGameMode"), AVerseDefaultGameMode::StaticClass()->IsChildOf(AVerseGameMode::StaticClass()));

	const AVerseDefaultGameMode* Mode = GetDefault<AVerseDefaultGameMode>();
	TestTrue(TEXT("player state is AVersePlayerState"), Mode->PlayerStateClass == AVersePlayerState::StaticClass());

	const AVerseDefaultCharacter* Pawn = GetDefault<AVerseDefaultCharacter>();
	TestNotNull(TEXT("ability system component"), Pawn->GetAbilitySystemComponent());
	TestNotNull(TEXT("UVerseHealthSet"), Pawn->GetHealthSet());
	TestNotNull(TEXT("combat state"), Pawn->GetCombatState());
	TestNotNull(TEXT("inventory"), Pawn->GetInventory());
	TestNotNull(TEXT("weapon"), Pawn->GetWeapon());
	TestNotNull(TEXT("melee"), Pawn->GetMelee());
	TestNotNull(TEXT("gadgets"), Pawn->GetGadgets());
	TestNotNull(TEXT("first-person camera from AVerseCharacter"), Pawn->GetFirstPersonCamera());
	TestNotNull(TEXT("Verse movement component from AVerseCharacter"), Pawn->GetVerseMovement());
	if (const UVerseHealthSet* Set = Pawn->GetHealthSet())
	{
		TestEqual(TEXT("health starts at 100"), Set->GetHealth(), UVerseHealthSet::StartHealth);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePrimaryLoadoutTest, "Verse.Primary.Loadout", Flags)
bool FVersePrimaryLoadoutTest::RunTest(const FString&)
{
	FWorld W;
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AVerseDefaultGameMode* Mode = W.World->SpawnActor<AVerseDefaultGameMode>(Params);
	AVerseDefaultCharacter* Pawn = W.World->SpawnActor<AVerseDefaultCharacter>(FVector(0, 0, 200), FRotator::ZeroRotator, Params);
	if (!TestNotNull(TEXT("game mode"), Mode) || !TestNotNull(TEXT("pawn"), Pawn))
	{
		return false;
	}
	TestEqual(TEXT("four slots filled (two firearms, two gadgets)"), Mode->GiveLoadout(Pawn), 4);

	const FVerseWeaponSlotState* Primary = Pawn->GetInventory()->GetSlotState(EVerseLoadoutSlot::Primary);
	const FVerseWeaponSlotState* Secondary = Pawn->GetInventory()->GetSlotState(EVerseLoadoutSlot::Secondary);
	TestTrue(TEXT("primary is the Graveline"), Primary && Primary->Definition && Primary->Definition->WeaponId == FName(TEXT("graveline")));
	TestTrue(TEXT("secondary is the Tallow"), Secondary && Secondary->Definition && Secondary->Definition->WeaponId == FName(TEXT("tallow")));
	TestTrue(TEXT("primary magazine is full"), Primary && Primary->Definition && Primary->Magazine > 0);

	const UVerseGadgetComponent* Gadgets = Pawn->GetGadgets();
	TestNotNull(TEXT("Bulwark definition"), Gadgets->Bulwark.Get());
	TestNotNull(TEXT("breach charge definition"), Gadgets->BreachCharge.Get());
	TestTrue(TEXT("Bulwark charges are full"), Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetA) > 0);
	TestTrue(TEXT("breach charges are full"), Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetB) > 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePrimaryKillCamFractureTest, "Verse.Primary.KillCamFracture", Flags)
bool FVersePrimaryKillCamFractureTest::RunTest(const FString&)
{
	FWorld W;
	TestNotNull(TEXT("integration subsystem in a game world"), W.World->GetSubsystem<UVerseIntegrationSubsystem>());
	UVerseUiSubsystem* Ui = W.World->GetSubsystem<UVerseUiSubsystem>();
	UVerseDebrisSubsystem* Debris = W.World->GetSubsystem<UVerseDebrisSubsystem>();
	if (!TestNotNull(TEXT("UI subsystem"), Ui) || !TestNotNull(TEXT("debris subsystem"), Debris))
	{
		return false;
	}
	Ui->OnKillCamFracture = nullptr;
	TestTrue(TEXT("binds when both sides exist"), UVerseIntegrationSubsystem::BindKillCamFracture(*W.World));
	TestTrue(TEXT("UI fracture hook is bound"), bool(Ui->OnKillCamFracture));

	FVerseFractureEvent Break;
	Break.PieceIndex = 3;
	Break.Cause = EVerseFractureCause::Bolt;
	Break.ToState = EVersePieceState::Holed;
	TestTrue(TEXT("a break is replayed"), Debris->ReplayFracture(Break));
	FVerseFractureEvent Reset;
	Reset.PieceIndex = 0xFFFF;
	Reset.Cause = EVerseFractureCause::Reset;
	TestFalse(TEXT("a reset is not replayed"), Debris->ReplayFracture(Reset));
	FVerseFractureEvent Repair = Break;
	Repair.Cause = EVerseFractureCause::Repair;
	TestFalse(TEXT("a repair is not replayed"), Debris->ReplayFracture(Repair));
	// Through the bound hook: no piece manager in this world, so nothing spawns and nothing breaks.
	Ui->OnKillCamFracture(Break);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePrimarySettingsSeamsTest, "Verse.Primary.SettingsSeams", Flags)
bool FVersePrimarySettingsSeamsTest::RunTest(const FString&)
{
	// Live gore switch: VerseUI finds the call by reflection (WP05.7).
	TestNotNull(TEXT("ReloadLevelFromSettings is a UFUNCTION"), UVerseGoreSubsystem::StaticClass()->FindFunctionByName(TEXT("ReloadLevelFromSettings")));

	// VerseUI writes the view settings into the UVerseSettings default object.
	FWorld W;
	UVerseUiSubsystem* Ui = W.World->GetSubsystem<UVerseUiSubsystem>();
	if (!TestNotNull(TEXT("UI subsystem"), Ui))
	{
		return false;
	}
	const FVerseAppSettings Before = Ui->GetAppSettings();
	ON_SCOPE_EXIT { Ui->SetAppSettings(Before); };
	FVerseAppSettings Next = Before;
	Next.Sensitivity = Before.Sensitivity + 0.75f;
	Next.bInvertY = !Before.bInvertY;
	Next.FovThird = 66.f;
	Next.FovFirst = 91.f;
	Next.Volume = 0.25f;
	Next.bReducedMotion = !Before.bReducedMotion;
	Ui->SetAppSettings(Next);
	const UVerseSettings* Settings = GetDefault<UVerseSettings>();
	TestEqual(TEXT("LookSensitivity"), Settings->LookSensitivity, Next.Sensitivity);
	TestEqual(TEXT("bInvertLookY"), Settings->bInvertLookY, Next.bInvertY);
	TestEqual(TEXT("DeckFovThirdDeg"), Settings->DeckFovThirdDeg, 66.f);
	TestEqual(TEXT("DeckFovFirstDeg"), Settings->DeckFovFirstDeg, 91.f);
	TestEqual(TEXT("MasterVolume"), Settings->MasterVolume, 0.25f);
	TestEqual(TEXT("bReducedMotion"), Settings->bReducedMotion, Next.bReducedMotion);
	TestEqual(TEXT("DuelFovDeg follows the UI user setting"), Settings->DuelFovDeg, Ui->GetUserSettings()->DuelFov);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

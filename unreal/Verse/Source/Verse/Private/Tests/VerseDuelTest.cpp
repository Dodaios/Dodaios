#include "Controller/VerseBotController.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Controller.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"
#include "VerseCombatDriverComponent.h"
#include "VerseDefaultCharacter.h"
#include "VerseDefaultGameMode.h"
#include "VerseDuelSubsystem.h"

#if WITH_DEV_AUTOMATION_TESTS

// The hangar duel of the integration (orchestration.md 2.2): the input frame reaches the combat
// components (Verse.Primary.CombatDriver), and the rendered loop runs per tier with the scripted
// player against the bot plus one bot-vs-bot match (Verse.Visual.HangarDuel, through
// scripts/unreal/screenshot.py). Shots and stats land in Saved/Harness/proof/integrate/duel/.

namespace VerseDuelTest
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	struct FWorld
	{
		UWorld* World = nullptr;

		FWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseDuelTest")));
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

	UWorld* GameWorld()
	{
		if (!GEngine)
		{
			return nullptr;
		}
		for (const FWorldContext& Context : GEngine->GetWorldContexts())
		{
			if ((Context.WorldType == EWorldType::Game || Context.WorldType == EWorldType::PIE) && Context.World())
			{
				return Context.World();
			}
		}
		return nullptr;
	}

	FVerseInputFrame Frame(uint32 Buttons, uint32 Pressed = 0)
	{
		FVerseInputFrame F;
		F.Buttons = Buttons;
		F.Pressed = Pressed;
		return F;
	}
}

using namespace VerseDuelTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePrimaryCombatDriverTest, "Verse.Primary.CombatDriver", Flags)
bool FVersePrimaryCombatDriverTest::RunTest(const FString&)
{
	FWorld W;
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AVerseDefaultGameMode* Mode = W.World->SpawnActor<AVerseDefaultGameMode>(Params);
	AVerseDefaultCharacter* Pawn = W.World->SpawnActor<AVerseDefaultCharacter>(FVector(0, 0, 200), FRotator::ZeroRotator, Params);
	// Any concrete controller; the world never begins play, so the bot brain does not run.
	AController* Controller = W.World->SpawnActor<AVerseBotController>(Params);
	if (!TestNotNull(TEXT("game mode"), Mode) || !TestNotNull(TEXT("pawn"), Pawn) || !TestNotNull(TEXT("controller"), Controller))
	{
		return false;
	}
	Controller->Possess(Pawn);
	Mode->GiveLoadout(Pawn);
	UVerseCombatDriverComponent* Driver = Pawn->GetCombatDriver();
	UVerseInventoryComponent* Inventory = Pawn->GetInventory();
	if (!TestNotNull(TEXT("combat driver on the default pawn"), Driver))
	{
		return false;
	}
	const FVerseWeaponSlotState* Primary = Inventory->GetSlotState(EVerseLoadoutSlot::Primary);
	const int32 Before = Primary ? FVerseMagazine::RoundsReady(*Primary, *Primary->Definition) : 0;

	// The primary is ready after its equip time; hold the trigger for a second of ticks.
	constexpr float Dt = 1.f / 60.f;
	for (int32 I = 0; I < 120; ++I)
	{
		W.World->Tick(LEVELTICK_All, Dt);
		Driver->Drive(Frame(uint32(EVerseInputButton::Fire)), Dt);
	}
	TestTrue(TEXT("holding fire shoots"), Driver->GetShotsFired() > 0);
	Primary = Inventory->GetSlotState(EVerseLoadoutSlot::Primary);
	TestTrue(TEXT("shots spend rounds"), Primary && FVerseMagazine::RoundsReady(*Primary, *Primary->Definition) < Before);

	// Reload press starts a reload of the active firearm.
	Driver->Drive(Frame(0), Dt);
	Driver->Drive(Frame(uint32(EVerseInputButton::Reload), uint32(EVerseInputButton::Reload)), Dt);
	Primary = Inventory->GetSlotState(EVerseLoadoutSlot::Primary);
	TestTrue(TEXT("reload key reloads"), Primary && FVerseMagazine::IsReloading(*Primary));

	// Slot keys switch weapons; the knife slot is a slot too.
	Driver->Drive(Frame(uint32(EVerseInputButton::SlotSecondary)), Dt);
	TestEqual(TEXT("slot 2 draws the secondary"), Inventory->ActiveSlot, EVerseLoadoutSlot::Secondary);
	Driver->Drive(Frame(uint32(EVerseInputButton::SlotMelee)), Dt);
	TestEqual(TEXT("slot 3 draws the knife"), Inventory->ActiveSlot, EVerseLoadoutSlot::Melee);
	return true;
}

namespace VerseDuelTest
{
	struct FRun
	{
		FName Tier;
		bool bBots = false;
		double Seconds = 90.0;
	};

	struct FState
	{
		FString OutDir;
		double PhaseStartS = 0.0;
		int32 ShotsTaken = 0;
		int32 Stage = 0;
		bool bDeathShotPending = false;
		double DeathShotAtS = 0.0;
		bool bFireShotTaken = false;
		double LastFireAtS = -1.0;
		FDelegateHandle DeathHandle;
		FDelegateHandle FireHandle;
		TArray<FString> Summary;
	};

	void Shot(FState& State, const FString& Name)
	{
		FScreenshotRequest::RequestScreenshot(FPaths::Combine(State.OutDir, Name + TEXT(".png")), true, false);
		++State.ShotsTaken;
	}

	bool ShadersDone()
	{
		return GShaderCompilingManager == nullptr || GShaderCompilingManager->GetNumRemainingJobs() == 0;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualHangarDuelTest, "Verse.Visual.HangarDuel", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualHangarDuelTest::RunTest(const FString&)
{
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.HangarDuel needs a GPU (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> State = MakeShared<FState>();
	State->OutDir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/integrate/duel")));
	IFileManager::Get().MakeDirectory(*State->OutDir, true);

	double RunSeconds = 90.0;
	FParse::Value(FCommandLine::Get(), TEXT("VerseDuelTestSeconds="), RunSeconds);
	TArray<FRun> Runs = {{TEXT("normal"), false, RunSeconds}, {TEXT("hard"), false, RunSeconds}, {TEXT("elite"), false, RunSeconds}, {TEXT("hard"), true, RunSeconds}};

	// The hangar is the default map; wait for it and for shaders.
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
		{
			UWorld* World = GameWorld();
			const bool bReady = World && World->HasBegunPlay() && UVerseDuelSubsystem::Get(World) && ShadersDone();
			if (bReady)
			{
				if (UVerseEventHub* Hub = UVerseEventHub::Get(World))
				{
					TWeakPtr<FState> Weak = State;
					State->DeathHandle = Hub->OnDeath.AddLambda([Weak, World](const FVerseDeathEvent&)
						{
							if (TSharedPtr<FState> S = Weak.Pin())
							{
								if (!S->bDeathShotPending)
								{
									S->bDeathShotPending = true;
									S->DeathShotAtS = World->GetTimeSeconds() + 0.9;
								}
							}
						});
					State->FireHandle = Hub->OnFire.AddLambda([Weak, World](const FVerseFireEvent&)
						{
							if (TSharedPtr<FState> S = Weak.Pin())
							{
								S->LastFireAtS = World->GetTimeSeconds();
							}
						});
				}
				Shot(*State, TEXT("00_hangar_day"));
				return true;
			}
			return false;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.0));

	for (const FRun& Run : Runs)
	{
		const FString Tag = FString::Printf(TEXT("%s_%s"), Run.bBots ? TEXT("botvbot") : TEXT("player"), *Run.Tier.ToString());
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Run, Tag]() -> bool
			{
				UWorld* World = GameWorld();
				UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World);
				if (!Duel)
				{
					AddError(TEXT("no duel subsystem"));
					return true;
				}
				Duel->LeaveDuel();
				Duel->SetBotVsBot(Run.bBots);
				Duel->SetAutoplay(!Run.bBots);
				if (!Duel->StartDuel(Run.Tier))
				{
					AddError(FString::Printf(TEXT("%s: the duel did not start"), *Tag));
				}
				State->PhaseStartS = World->GetTimeSeconds();
				State->bDeathShotPending = false;
				State->bFireShotTaken = false;
				State->Stage = 0;
				return true;
			}));
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Run, Tag]() -> bool
			{
				UWorld* World = GameWorld();
				UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World);
				if (!World || !Duel)
				{
					return true;
				}
				const double T = World->GetTimeSeconds() - State->PhaseStartS;
				if (State->Stage == 0 && T > 4.0)
				{
					Shot(*State, Tag + TEXT("_01_spawn"));
					State->Stage = 1;
				}
				if (!State->bFireShotTaken && T > 6.0 && State->LastFireAtS > 0.0 && World->GetTimeSeconds() - State->LastFireAtS < 0.05)
				{
					Shot(*State, Tag + TEXT("_02_firefight"));
					State->bFireShotTaken = true;
				}
				if (State->bDeathShotPending && World->GetTimeSeconds() >= State->DeathShotAtS && State->Stage < 2)
				{
					Shot(*State, Tag + TEXT("_03_after_death"));
					State->Stage = 2;
				}
				if (State->Stage == 2 && T > Run.Seconds * 0.6)
				{
					Shot(*State, Tag + TEXT("_04_late"));
					State->Stage = 3;
				}
				if (T < Run.Seconds)
				{
					return false;
				}
				const FString Json = Duel->StatsJson();
				FFileHelper::SaveStringToFile(Json, *FPaths::Combine(State->OutDir, Tag + TEXT("_stats.json")), FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
				AddInfo(FString::Printf(TEXT("%s: %s"), *Tag, *Json));
				int32 Kills = 0;
				int32 Shots = 0;
				for (const TPair<int32, FVerseDuelPlayerStats>& Pair : Duel->GetPlayerStats())
				{
					Kills += Pair.Value.Kills;
					Shots += Pair.Value.Shots;
				}
				// Bot vs bot is reported, not gated: two bots in Search do not always find each other
				// in the graybox arena yet (WP08 search over the runtime nav mesh).
				if (Shots == 0 || Kills == 0)
				{
					const FString Problem = FString::Printf(TEXT("%s: %d shots, %d kills in %.0f s"), *Tag, Shots, Kills, Run.Seconds);
					if (Run.bBots)
					{
						AddWarning(Problem);
					}
					else
					{
						AddError(Problem);
					}
				}
				return true;
			}));
	}
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([State]() -> bool
		{
			UWorld* World = GameWorld();
			if (UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World))
			{
				Duel->LeaveDuel();
			}
			if (UVerseEventHub* Hub = UVerseEventHub::Get(World))
			{
				Hub->OnDeath.Remove(State->DeathHandle);
				Hub->OnFire.Remove(State->FireHandle);
			}
			return true;
		}));
	return true;
}

#endif

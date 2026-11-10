#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"
#include "VerseArenaGraybox.h"
#include "VerseDefaultCharacter.h"
#include "VerseDuelSubsystem.h"

#if WITH_DEV_AUTOMATION_TESTS

// The hangar arena's art (rendered lane, scripts/unreal/screenshot.py --suite Verse.Visual.HangarArt):
// a fixed tour through the duel arena from a player's eye, both spawns, mid, cover, looking up, aiming
// down sights and a high overview. Shots land in Saved/Harness/proof/art/.

namespace VerseHangarArtTest
{
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

	/** One view of the tour: floor point (world cm), eye yaw and pitch (degrees), ADS held. */
	struct FView
	{
		const TCHAR* Name;
		FVector Floor;
		double Yaw;
		double Pitch;
		bool bAds;
	};

	const FView Views[] = {
		{TEXT("01_spawn_nw"), FVector(2600.0, 500.0, 0.0), 45.0, -2.0, false},
		{TEXT("02_spawn_e_canyon"), FVector(7100.0, 4000.0, 0.0), 250.0, -2.0, false},
		{TEXT("03_mid_shuttle"), FVector(3900.0, 2300.0, 0.0), 5.0, 0.0, false},
		{TEXT("04_cover_canyon"), FVector(6360.0, 1200.0, 0.0), 90.0, 0.0, false},
		{TEXT("05_look_up"), FVector(4300.0, 1000.0, 0.0), 30.0, 55.0, false},
		{TEXT("06_ads_south"), FVector(4850.0, 4250.0, 0.0), 260.0, -1.0, true},
		{TEXT("07_booth_l1"), FVector(3150.0, 4050.0, 300.0), 330.0, -6.0, false},
		{TEXT("08_catwalk_l2"), FVector(2620.0, 1800.0, 600.0), 70.0, -12.0, false},
	};

	bool ShadersDone()
	{
		return GShaderCompilingManager == nullptr || GShaderCompilingManager->GetNumRemainingJobs() == 0;
	}

	struct FState
	{
		FString OutDir;
		double StartS = 0.0;
		int32 View = 0;
		int32 Phase = 0;
		double PhaseS = 0.0;
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualHangarArtTest, "Verse.Visual.HangarArt", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualHangarArtTest::RunTest(const FString&)
{
	using namespace VerseHangarArtTest;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.HangarArt needs a GPU (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> State = MakeShared<FState>();
	State->OutDir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/art")));
	IFileManager::Get().MakeDirectory(*State->OutDir, true);

	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
		{
			UWorld* World = GameWorld();
			if (!World || !World->HasBegunPlay() || !UVerseDuelSubsystem::Get(World) || !ShadersDone())
			{
				return false;
			}
			UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World);
			Duel->LeaveDuel();
			Duel->SetBotVsBot(false);
			Duel->SetAutoplay(false);
			if (!Duel->StartDuel(TEXT("easy")))
			{
				AddError(TEXT("the duel did not start"));
			}
			State->StartS = World->GetTimeSeconds();
			return true;
		}));

	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
		{
			UWorld* World = GameWorld();
			if (!World)
			{
				return true;
			}
			const double Now = World->GetTimeSeconds();
			if (Now - State->StartS < 20.0 || !ShadersDone())
			{
				return false;  // nav, shaders, distance fields and Lumen cards settle first
			}
			APlayerController* PC = World->GetFirstPlayerController();
			AVerseDefaultCharacter* Pawn = PC ? Cast<AVerseDefaultCharacter>(PC->GetPawn()) : nullptr;
			if (!Pawn)
			{
				return false;  // respawning
			}
			if (State->View >= int32(UE_ARRAY_COUNT(Views)))
			{
				return true;
			}
			const FView& View = Views[State->View];
			switch (State->Phase)
			{
			case 0:
				Pawn->TeleportTo(View.Floor + FVector(0.0, 0.0, 100.0), FRotator(0.0, View.Yaw, 0.0));
				PC->SetControlRotation(FRotator(View.Pitch, View.Yaw, 0.0));
				Pawn->GetPersonInput().SetButton(EVerseInputButton::Ads, View.bAds);
				State->PhaseS = Now;
				State->Phase = 1;
				break;
			case 1:
				// Lumen and the virtual shadow maps catch up after a teleport.
				PC->SetControlRotation(FRotator(View.Pitch, View.Yaw, 0.0));
				if (Now - State->PhaseS > 3.0 && ShadersDone())
				{
					FScreenshotRequest::RequestScreenshot(FPaths::Combine(State->OutDir, FString(View.Name) + TEXT(".png")), true, false);
					State->PhaseS = Now;
					State->Phase = 2;
				}
				break;
			default:
				if (Now - State->PhaseS > 0.3)
				{
					Pawn->GetPersonInput().SetButton(EVerseInputButton::Ads, false);
					State->Phase = 0;
					++State->View;
				}
				break;
			}
			return false;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.5));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([]() -> bool
		{
			if (UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(GameWorld()))
			{
				Duel->LeaveDuel();
			}
			return true;
		}));
	return true;
}

#endif

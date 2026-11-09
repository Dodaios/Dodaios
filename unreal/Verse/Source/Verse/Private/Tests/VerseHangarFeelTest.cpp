#include "Controller/VerseBotController.h"
#include "Core/VerseUiSubsystem.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "HAL/FileManager.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VerseDestructionManager.h"
#include "Projectiles/VerseBoltPresentation.h"
#include "Repair/VerseRepairDrone.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"
#include "VerseArenaGraybox.h"
#include "VerseDefaultCharacter.h"
#include "VerseDuelSubsystem.h"
#include "VerseViewmodelComponent.h"

#if WITH_DEV_AUTOMATION_TESTS

// The hangar duel's look and feel (rendered lane, scripts/unreal/screenshot.py --suite
// Verse.Visual.HangarFeel): the first-person weapon at hip, firing, aiming, reloading and with the
// knife; shots and impacts; a breach with debris and the repair drones; a live firefight against
// the bot. Shots land in Saved/Harness/proof/<branch>/feel/; the checks are on state the shots show.

namespace VerseHangarFeelTest
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

	struct FState
	{
		FString OutDir;
		double StepStartS = 0.0;
		int32 Step = 0;
		bool bFoeFireSeen = false;
		bool bFoeShotTaken = false;
		bool bDeathShotTaken = false;
		double DeathAtS = -1.0;
		double FoeFireAtS = -1.0;
		int32 OwnId = INDEX_NONE;
		FDelegateHandle FireHandle;
		FDelegateHandle DeathHandle;
		TArray<FString> Shots;
	};

	void Shot(FState& State, const FString& Name)
	{
		FScreenshotRequest::RequestScreenshot(FPaths::Combine(State.OutDir, Name + TEXT(".png")), true, false);
		State.Shots.Add(Name);
	}

	AVerseDefaultCharacter* Person(UWorld* World)
	{
		APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
		return PC ? Cast<AVerseDefaultCharacter>(PC->GetPawn()) : nullptr;
	}

	void Hold(UWorld* World, EVerseInputButton Button, bool bDown)
	{
		if (AVerseDefaultCharacter* Pawn = Person(World))
		{
			Pawn->GetPersonInput().SetButton(Button, bDown);
		}
	}

	/** Turns the person's view to a point. */
	void LookAt(UWorld* World, const FVector& Target)
	{
		APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
		APawn* Pawn = PC ? PC->GetPawn() : nullptr;
		if (Pawn)
		{
			PC->SetControlRotation((Target - Pawn->GetPawnViewLocation()).Rotation());
		}
	}

	/** The breakable piece nearest the person that it can see, in front of it. */
	AVerseDestructible* PieceInView(UWorld* World)
	{
		APawn* Pawn = Person(World);
		if (!Pawn)
		{
			return nullptr;
		}
		const FVector Eye = Pawn->GetPawnViewLocation();
		AVerseDestructible* Best = nullptr;
		double BestDist = 1.0e12;
		for (TActorIterator<AVerseDestructible> It(World); It; ++It)
		{
			if (It->PieceClass == EVersePieceClass::CeilingPanel || It->PieceClass == EVersePieceClass::CatwalkSegment)
			{
				continue;
			}
			const double Dist = FVector::Dist(It->GetActorLocation(), Eye);
			if (Dist < 500.0 || Dist > 2500.0 || Dist >= BestDist)
			{
				continue;
			}
			FHitResult Hit;
			FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseFeelSight), false, Pawn);
			if (World->LineTraceSingleByChannel(Hit, Eye, It->GetActorLocation(), ECC_Visibility, Params) && Hit.GetActor() != *It)
			{
				continue;
			}
			Best = *It;
			BestDist = Dist;
		}
		return Best;
	}

	/**
	 * Puts the person 7 m in front of a container wall of the arena, facing it: the breach and
	 * debris shots need a breakable wall in view whatever spawn the match picked.
	 */
	AVerseDestructible* StandBeforeWall(UWorld* World)
	{
		AVerseDefaultCharacter* Pawn = Person(World);
		if (!Pawn)
		{
			return nullptr;
		}
		const FVector ArenaCentre(5000.0, 2400.0, 0.0);
		AVerseDestructible* Best = nullptr;
		double BestScore = 1.0e12;
		for (TActorIterator<AVerseDestructible> It(World); It; ++It)
		{
			if (It->PieceClass != EVersePieceClass::ContainerWall && It->PieceClass != EVersePieceClass::WallPanel)
			{
				continue;
			}
			const FVector Size = It->GetActorScale3D() * 100.0;
			if (Size.Z < 200.0 || It->GetActorLocation().Z - Size.Z * 0.5 > 60.0)
			{
				continue; // ground-floor walls only
			}
			const double Score = FVector::Dist2D(It->GetActorLocation(), ArenaCentre);
			if (Score < BestScore)
			{
				Best = *It;
				BestScore = Score;
			}
		}
		if (!Best)
		{
			return nullptr;
		}
		const FVector Size = Best->GetActorScale3D() * 100.0;
		const FVector Centre = Best->GetActorLocation();
		FVector Normal = Size.X < Size.Y ? FVector(1.0, 0.0, 0.0) : FVector(0.0, 1.0, 0.0);
		if (FVector::DotProduct(ArenaCentre - Centre, Normal) < 0.0)
		{
			Normal = -Normal;
		}
		const FVector Floor(Centre.X, Centre.Y, Centre.Z - Size.Z * 0.5);
		const FVector Stand = Floor + Normal * 700.0 + FVector(0.0, 0.0, 100.0);
		Pawn->TeleportTo(Stand, (-Normal).Rotation());
		LookAt(World, Centre);
		return Best;
	}

	bool ShadersDone()
	{
		return GShaderCompilingManager == nullptr || GShaderCompilingManager->GetNumRemainingJobs() == 0;
	}

	void KeepHud(UWorld* World)
	{
		// The scripted run never wants a menu over the arena (a lost window focus opens none either).
		if (UVerseUiSubsystem* Ui = World ? World->GetSubsystem<UVerseUiSubsystem>() : nullptr)
		{
			if (Ui->GetScreen() == EVerseUiScreen::EscMenu || Ui->GetScreen() == EVerseUiScreen::Settings)
			{
				Ui->ShowScreen(EVerseUiScreen::None);
			}
		}
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualHangarFeelTest, "Verse.Visual.HangarFeel", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualHangarFeelTest::RunTest(const FString&)
{
	using namespace VerseHangarFeelTest;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.HangarFeel needs a GPU (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> State = MakeShared<FState>();
	State->OutDir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/feel")));
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
			if (!Duel->StartDuel(TEXT("hard")))
			{
				AddError(TEXT("the duel did not start"));
			}
			if (UVerseEventHub* Hub = UVerseEventHub::Get(World))
			{
				TWeakPtr<FState> Weak = State;
				State->FireHandle = Hub->OnFire.AddLambda([Weak, World](const FVerseFireEvent& E)
					{
						if (TSharedPtr<FState> S = Weak.Pin(); S && E.ShooterId != S->OwnId && S->OwnId != INDEX_NONE && !S->bFoeFireSeen)
						{
							S->bFoeFireSeen = true;
							S->FoeFireAtS = World->GetTimeSeconds();
						}
					});
				State->DeathHandle = Hub->OnDeath.AddLambda([Weak, World](const FVerseDeathEvent&)
					{
						if (TSharedPtr<FState> S = Weak.Pin(); S && S->DeathAtS < 0.0)
						{
							S->DeathAtS = World->GetTimeSeconds();
						}
					});
			}
			State->StepStartS = World->GetTimeSeconds();
			return true;
		}));

	// The scripted part: one step per frame until its time has come.
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
		{
			UWorld* World = GameWorld();
			if (!World)
			{
				return true;
			}
			KeepHud(World);
			AVerseDefaultCharacter* Pawn = Person(World);
			const double T = World->GetTimeSeconds() - State->StepStartS;
			if (Pawn)
			{
				State->OwnId = Pawn->GetPlayerState() ? Pawn->GetPlayerState()->GetPlayerId() : INDEX_NONE;
			}
			AVerseArenaGraybox* Graybox = AVerseArenaGraybox::Find(*World);
			AVerseDestructible* Target = nullptr;
			switch (State->Step)
			{
			case 0:
				// Spawned and nav built: in front of a breakable wall, then an exposure sweep.
				if (T > 4.0 && Pawn)
				{
					StandBeforeWall(World);
					State->Step = 20;
				}
				break;
			case 20:
			case 21:
			case 22:
			case 23:
			{
				const float Sweep[] = {1.5f, 2.f, 3.f, 3.5f};
				const int32 I = State->Step - 20;
				if (T > 4.4 + 0.3 * I && Graybox)
				{
					Graybox->SetExposureEV100(Sweep[I]);
				}
				if (T > 4.55 + 0.3 * I)
				{
					Shot(*State, FString::Printf(TEXT("00_ev%02.0f"), Sweep[I] * 10.f));
					State->Step = I == 3 ? 24 : State->Step + 1;
				}
				break;
			}
			case 24:
				if (T > 5.4)
				{
					if (Graybox)
					{
						Graybox->SetExposureEV100(AVerseArenaGraybox::ArenaExposureEV100);
					}
					State->Step = 1;
				}
				break;
			case 1:
				if (T > 5.6)
				{
					Shot(*State, TEXT("01_hip"));
					TestTrue(TEXT("the person holds a weapon in view"), Pawn && Pawn->GetViewmodel() && Pawn->GetViewmodel()->IsShowing());
					TestTrue(TEXT("the arena has breakable pieces"), Graybox && Graybox->NumPieces() > 100);
					Hold(World, EVerseInputButton::Fire, true);
					State->Step = 2;
				}
				break;
			case 2:
				if (T > 5.85)
				{
					Shot(*State, TEXT("02_fire"));
					State->Step = 3;
				}
				break;
			case 3:
				if (T > 6.6)
				{
					Hold(World, EVerseInputButton::Fire, false);
					Hold(World, EVerseInputButton::Ads, true);
					State->Step = 4;
				}
				break;
			case 4:
				if (T > 7.3)
				{
					Shot(*State, TEXT("03_ads"));
					Hold(World, EVerseInputButton::Fire, true);
					State->Step = 5;
				}
				break;
			case 5:
				if (T > 7.5)
				{
					Shot(*State, TEXT("04_ads_fire"));
					State->Step = 6;
				}
				break;
			case 6:
				if (T > 8.2)
				{
					Hold(World, EVerseInputButton::Fire, false);
					Hold(World, EVerseInputButton::Ads, false);
					Hold(World, EVerseInputButton::Reload, true);
					State->Step = 7;
				}
				break;
			case 7:
				if (T > 8.25)
				{
					Hold(World, EVerseInputButton::Reload, false);
				}
				if (T > 8.9)
				{
					Shot(*State, TEXT("05_reload"));
					State->Step = 8;
				}
				break;
			case 8:
				if (T > 11.5)
				{
					Hold(World, EVerseInputButton::Melee, true);
					State->Step = 9;
				}
				break;
			case 9:
				if (T > 11.55)
				{
					Hold(World, EVerseInputButton::Melee, false);
				}
				if (T > 11.64)
				{
					Shot(*State, TEXT("06_knife"));
					State->Step = 10;
				}
				break;
			case 10:
				// A breach on the wall in view: the frame, the chunks, then the drones coming.
				if (T > 12.5)
				{
					Target = StandBeforeWall(World);
					AVerseDestructionManager* Manager = Graybox ? Graybox->GetDestructionManager() : nullptr;
					TestNotNull(TEXT("a breakable piece in view"), Target);
					TestNotNull(TEXT("the arena's destruction manager"), Manager);
					if (Target && Manager && Target->GetPieceIndex() != INDEX_NONE)
					{
						LookAt(World, Target->GetActorLocation());
						FVersePieceDamage Damage;
						Damage.PieceIndex = uint16(Target->GetPieceIndex());
						Damage.Cause = EVerseFractureCause::Breach;
						Damage.Location = Target->GetActorLocation();
						Damage.Direction = (Target->GetActorLocation() - Pawn->GetPawnViewLocation()).GetSafeNormal();
						Damage.BreachRadiusCm = 150.f;
						Manager->ApplyPieceDamage(Damage);
					}
					State->Step = 11;
				}
				break;
			case 11:
				if (T > 12.75)
				{
					Shot(*State, TEXT("07_breach"));
					State->Step = 12;
				}
				break;
			case 12:
				if (T > 14.5)
				{
					Shot(*State, TEXT("08_breach_settled"));
					TestTrue(TEXT("the breach threw chunks"), Graybox && Graybox->NumDebris() > 0);
					int32 Drones = 0;
					for (TActorIterator<AVerseRepairDrone> It(World); It; ++It)
					{
						++Drones;
					}
					TestTrue(TEXT("repair drones in the arena"), Drones > 0);
					// The live part: the scripted player plays the bot.
					UVerseDuelSubsystem::Get(World)->SetAutoplay(true);
					State->Step = 13;
				}
				break;
			case 13:
				if (State->bFoeFireSeen && !State->bFoeShotTaken && World->GetTimeSeconds() - State->FoeFireAtS > 0.06)
				{
					Shot(*State, TEXT("09_foe_fire"));
					State->bFoeShotTaken = true;
				}
				if (State->DeathAtS > 0.0 && !State->bDeathShotTaken && World->GetTimeSeconds() - State->DeathAtS > 0.5)
				{
					Shot(*State, TEXT("10_after_kill"));
					State->bDeathShotTaken = true;
				}
				if (T > 75.0 || (State->bFoeShotTaken && State->bDeathShotTaken))
				{
					Shot(*State, TEXT("11_late"));
					State->Step = 14;
				}
				break;
			default:
				break;
			}
			if (State->Step != 14)
			{
				return false;
			}
			if (!State->bFoeShotTaken)
			{
				AddWarning(TEXT("the bot did not fire within 60 s of live play"));
			}
			FFileHelper::SaveStringToFile(FString::Join(State->Shots, TEXT("\n")), *FPaths::Combine(State->OutDir, TEXT("shots.txt")));
			if (UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World))
			{
				FFileHelper::SaveStringToFile(Duel->StatsJson(), *FPaths::Combine(State->OutDir, TEXT("stats.json")));
			}
			return true;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.5));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([State]() -> bool
		{
			UWorld* World = GameWorld();
			if (UVerseEventHub* Hub = UVerseEventHub::Get(World))
			{
				Hub->OnFire.Remove(State->FireHandle);
				Hub->OnDeath.Remove(State->DeathHandle);
			}
			if (UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World))
			{
				Duel->LeaveDuel();
			}
			return true;
		}));
	return true;
}

#endif

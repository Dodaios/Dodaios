#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Camera/VerseDeckCamera.h"
#include "Camera/VerseDeckView.h"
#include "Commander/VerseDeckCommander.h"
#include "Components/PointLightComponent.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/PointLight.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "Input/VerseDeckControlComponent.h"
#include "Life/VerseDeckDrone.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "Misc/Paths.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.DeckDrones: the drones on the ops deck in the game renderer. The companion at the
// commander's heel, then following the commander's walk; a utility drone on its corridor round,
// twice a few seconds apart. Shots land in Saved/Harness/proof/S7/deck_drones/ (never committed).

namespace VerseDeckDronesVisual
{
	UWorld* GameWorld()
	{
		for (const FWorldContext& Context : GEngine->GetWorldContexts())
		{
			if ((Context.WorldType == EWorldType::Game || Context.WorldType == EWorldType::PIE) && Context.World())
			{
				return Context.World();
			}
		}
		return nullptr;
	}

	UVerseDeckSubsystem* Decks()
	{
		UWorld* World = GameWorld();
		UGameInstance* Instance = World ? World->GetGameInstance() : nullptr;
		return Instance ? Instance->GetSubsystem<UVerseDeckSubsystem>() : nullptr;
	}

	UVerseDeckControlComponent* Control()
	{
		return UVerseDeckControlComponent::Get(GameWorld());
	}

	AVerseDeckDrone* FindDrone(EVerseDroneKind Kind)
	{
		UWorld* World = GameWorld();
		for (TActorIterator<AVerseDeckDrone> It(World); World && It; ++It)
		{
			if (It->GetKind() == Kind)
			{
				return *It;
			}
		}
		return nullptr;
	}

	struct FState
	{
		FString OutDir;
		double StartedAt = 0.0;
		TWeakObjectPtr<ACameraActor> Camera;
	};

	APointLight* KeyLight(UWorld* World, AActor* Parent, const FVector& Offset, float Lumen)
	{
		FActorSpawnParameters Params;
		Params.ObjectFlags |= RF_Transient;
		APointLight* Key = World->SpawnActor<APointLight>(Params);
		if (Key)
		{
			Key->SetMobility(EComponentMobility::Movable);
			UPointLightComponent* Light = Key->PointLightComponent;
			Light->SetIntensityUnits(ELightUnits::Lumens);
			Light->SetIntensity(Lumen);
			Light->SetAttenuationRadius(1500.f);
			Light->SetLightColor(FLinearColor(1.0f, 0.92f, 0.82f));
			Light->SetCastShadows(true);
			Key->AttachToActor(Parent, FAttachmentTransformRules::KeepRelativeTransform);
			Key->SetActorRelativeLocation(Offset);
		}
		return Key;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualDeckDronesTest, "Verse.Visual.DeckDrones", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualDeckDronesTest::RunTest(const FString&)
{
	using namespace VerseDeckDronesVisual;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.DeckDrones needs a GPU (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	const FName Deck(TEXT("ops"));
	TSharedRef<FState> State = MakeShared<FState>();
	State->OutDir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/S7/deck_drones")));
	IFileManager::Get().MakeDirectory(*State->OutDir, true);

	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Deck]() -> bool
		{
			UVerseDeckSubsystem* Subsystem = Decks();
			State->StartedAt = FPlatformTime::Seconds();
			if (Subsystem == nullptr || !Subsystem->LoadDeckDirect(Deck))
			{
				AddError(TEXT("the ops deck did not start loading"));
			}
			return true;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Deck]() -> bool
		{
			UVerseDeckSubsystem* Subsystem = Decks();
			UVerseDeckControlComponent* C = Control();
			if (Subsystem && Subsystem->GetCurrentDeck() == Deck && C && C->GetCommander())
			{
				C->WindowFocused = []() { return true; };
				C->MousePosition = []() { return TOptional<FVector2D>(); };
				C->CompleteNav();
				int32 Drones = 0;
				for (TActorIterator<AVerseDeckDrone> It(C->GetWorld()); It; ++It)
				{
					++Drones;
					KeyLight(C->GetWorld(), *It, FVector(120.0, 120.0, 140.0), 900.f);
				}
				AddInfo(FString::Printf(TEXT("%d drones on the deck"), Drones));
				TestNotNull(TEXT("the companion is on the deck"), FindDrone(EVerseDroneKind::Companion));
				TestNotNull(TEXT("a utility drone is on the deck"), FindDrone(EVerseDroneKind::Utility));
				KeyLight(C->GetWorld(), C->GetCommander(), FVector(180.0, 140.0, 180.0), 2200.f);
				return true;
			}
			if (FPlatformTime::Seconds() - State->StartedAt > 60.0)
			{
				AddError(TEXT("no commander on the ops deck within 60 s"));
				return true;
			}
			return false;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([]() -> bool
		{
			static double Since = 0.0;
			const bool bDone = GShaderCompilingManager == nullptr || GShaderCompilingManager->GetNumRemainingJobs() == 0;
			if (!bDone)
			{
				Since = 0.0;
				return false;
			}
			Since = Since == 0.0 ? FPlatformTime::Seconds() : Since;
			if (FPlatformTime::Seconds() - Since > 4.0)
			{
				Since = 0.0;
				return true;
			}
			return false;
		}));

	auto Shot = [State](const TCHAR* Name, float SettleS)
	{
		ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(SettleS));
		const FString Path = FPaths::Combine(State->OutDir, FString(Name) + TEXT(".png"));
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([Path]() -> bool
			{
				FScreenshotRequest::RequestScreenshot(Path, false, false);
				return true;
			}));
		ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.8f));
	};
	auto Do = [](TFunction<void(UVerseDeckControlComponent&)> Fn)
	{
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([Fn]() -> bool
			{
				if (UVerseDeckControlComponent* C = Control())
				{
					Fn(*C);
				}
				return true;
			}));
	};

	// 1. Third person from the front-left: the commander and the companion at its heel.
	Do([](UVerseDeckControlComponent& C)
		{
			C.PickView(EVerseDeckView::Third);
			C.SetMouseLook(false);
			C.GetCamera()->Rig.YawDeg = C.GetCommander()->GetActorRotation().Yaw + 150.0;
			C.GetCamera()->Rig.PitchDeg = -8.0;
		});
	Shot(TEXT("companion_heel"), 3.0f);
	// 2. The commander walks off: the companion follows with A_Follow.
	Do([](UVerseDeckControlComponent& C)
		{
			C.GetCamera()->Rig.YawDeg = C.GetCommander()->GetActorRotation().Yaw + 120.0;
			C.SetMoveAxes(FVector2D(0.0, 1.0));
		});
	Shot(TEXT("companion_follow"), 1.6f);
	Do([](UVerseDeckControlComponent& C) { C.SetMoveAxes(FVector2D::ZeroVector); });
	Shot(TEXT("companion_settled"), 2.5f);
	// 3. A utility drone on its round, seen from 2.5 m.
	auto UtilityShot = [this, State, Shot](const TCHAR* Name, float SettleS)
	{
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
			{
				UWorld* World = GameWorld();
				AVerseDeckDrone* Drone = FindDrone(EVerseDroneKind::Utility);
				APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
				if (!Drone || !PC)
				{
					AddError(TEXT("no utility drone to frame"));
					return true;
				}
				ACameraActor* Camera = State->Camera.Get();
				if (Camera == nullptr)
				{
					FActorSpawnParameters Params;
					Params.ObjectFlags |= RF_Transient;
					Camera = World->SpawnActor<ACameraActor>(Params);
					Camera->GetCameraComponent()->SetFieldOfView(60.f);
					Camera->GetCameraComponent()->SetConstraintAspectRatio(false);
					State->Camera = Camera;
				}
				const FVector Feet = Drone->GetFeet();
				const FVector Side = FRotator(0.0, Drone->GetYaw() + 60.0, 0.0).Vector();
				const FVector Eye = Feet + Side * 250.0 + FVector(0.0, 0.0, 120.0);
				Camera->SetActorLocationAndRotation(Eye, (Feet + FVector(0.0, 0.0, 15.0) - Eye).Rotation());
				Camera->AttachToActor(Drone, FAttachmentTransformRules::KeepWorldTransform);
				PC->SetViewTarget(Camera);
				AddInfo(FString::Printf(TEXT("utility drone at %s, clip %s"), *Feet.ToString(), *Drone->GetClip().ToString()));
				return true;
			}));
		Shot(Name, SettleS);
	};
	UtilityShot(TEXT("utility_route_a"), 1.0f);
	Shot(TEXT("utility_route_b"), 3.0f);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

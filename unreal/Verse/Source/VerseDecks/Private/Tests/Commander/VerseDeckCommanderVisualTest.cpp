#include "Camera/VerseDeckCamera.h"
#include "Commander/VerseDeckCommander.h"
#include "Decks/VerseDeckManifest.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Engine/Engine.h"
#include "Components/PointLightComponent.h"
#include "Engine/GameInstance.h"
#include "Engine/PointLight.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "Input/VerseDeckControlComponent.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "Misc/Paths.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.DeckCommander: rendered evidence of the deck commander (stream S5) on the hangar:
// third person walking with the "click to look" hint, the salute, the overview with a station's
// hover label and a walk order, first person with the reticle marked on a station, and a
// uniform change. Runs only on the GPU through scripts/unreal/screenshot.py; shots land in
// Saved/Harness/proof/S5/visual/ (never committed).

namespace VerseDeckCommanderVisual
{
	UWorld* GameWorld()
	{
		if (GEngine == nullptr)
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

	struct FState
	{
		FString OutDir;
		double StartedAt = 0.0;
		TOptional<FVector2D> Mouse;
	};

	/** The station nearest to the commander's arrival, for the walk and the label. */
	const FVerseDeckStation* NearStation(const UVerseDeckControlComponent& C, const FVerseDeckManifest& Manifest)
	{
		const AVerseDeckCommander* Body = C.GetCommander();
		const FVerseDeckStation* Best = nullptr;
		double BestD = TNumericLimits<double>::Max();
		for (const FVerseDeckStation& Station : Manifest.Stations)
		{
			const double D = Body ? FVector::Dist2D(Station.Transform.GetLocation(), Body->GetFeet()) : 0.0;
			// The lift's station sits inside the closed car; any other station shows its label in the open.
			if (Station.Kind != TEXT("lift") && D > 300.0 && D < BestD)
			{
				BestD = D;
				Best = &Station;
			}
		}
		return Best;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualDeckCommanderTest, "Verse.Visual.DeckCommander", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualDeckCommanderTest::RunTest(const FString&)
{
	using namespace VerseDeckCommanderVisual;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.DeckCommander needs a GPU (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	const FName Deck(TEXT("hangar"));
	TSharedRef<FState> State = MakeShared<FState>();
	State->OutDir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/S5/visual")));
	IFileManager::Get().MakeDirectory(*State->OutDir, true);
	TSharedRef<FVerseDeckManifest> Manifest = MakeShared<FVerseDeckManifest>();
	FString Error;
	if (!FVerseDeckManifest::Load(Deck, Verse::Decks::PlacementsDir(), *Manifest, Error))
	{
		AddError(Error);
		return false;
	}

	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Deck]() -> bool
		{
			UVerseDeckSubsystem* Subsystem = Decks();
			State->StartedAt = FPlatformTime::Seconds();
			if (Subsystem == nullptr || !Subsystem->LoadDeckDirect(Deck))
			{
				AddError(TEXT("the hangar did not start loading"));
			}
			return true;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Deck]() -> bool
		{
			UVerseDeckSubsystem* Subsystem = Decks();
			UVerseDeckControlComponent* C = Control();
			if (Subsystem && Subsystem->GetCurrentDeck() == Deck && C && C->GetCommander())
			{
				// The offscreen test window has no real focus or mouse.
				C->WindowFocused = []() { return true; };
				C->MousePosition = [State]() { return State->Mouse; };
				C->CompleteNav();
				// The decks are still unlit greybox (stream S9 lights them): an evidence key light
				// rides with the commander so the body, the salute and the uniform read in the shots.
				FActorSpawnParameters Params;
				Params.ObjectFlags |= RF_Transient;
				if (APointLight* Key = C->GetWorld()->SpawnActor<APointLight>(Params))
				{
					Key->SetMobility(EComponentMobility::Movable);
					UPointLightComponent* Light = Key->PointLightComponent;
					Light->SetIntensityUnits(ELightUnits::Lumens);
					Light->SetIntensity(2200.f);
					Light->SetAttenuationRadius(2200.f);
					Light->SetLightColor(FLinearColor(1.0f, 0.80f, 0.60f));
					Light->SetCastShadows(true);
					Key->AttachToActor(C->GetCommander(), FAttachmentTransformRules::KeepRelativeTransform);
					Key->SetActorRelativeLocation(FVector(180.0, 140.0, 160.0));
				}
				AddInfo(C->StateJson());
				return true;
			}
			if (FPlatformTime::Seconds() - State->StartedAt > 60.0)
			{
				AddError(TEXT("no commander on the hangar within 60 s"));
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

	auto Shot = [this, State](const TCHAR* Name)
	{
		ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.2f));
		const FString Label(Name);
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, Label]() -> bool
			{
				if (const UVerseDeckControlComponent* C = Control())
				{
					AddInfo(FString::Printf(TEXT("%s: camera %s at %s, body visible %d, %s"), *Label, *C->GetCamera()->StateJson(),
						*C->GetCamera()->GetActorLocation().ToString(), C->GetCommander()->IsBodyVisible(), *C->StateJson()));
				}
				return true;
			}));
		const FString Path = FPaths::Combine(State->OutDir, FString(Name) + TEXT(".png"));
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([Path]() -> bool
			{
				// With the UI: the deck overlay (reticle, hint, label) is drawn on the debug canvas.
				FScreenshotRequest::RequestScreenshot(Path, true, false);
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

	// 0. Out of the lift lobby onto the open floor: 5 m in front of the nearest open station.
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([Manifest]() -> bool
		{
			UVerseDeckControlComponent* C = Control();
			const FVerseDeckStation* Station = C ? NearStation(*C, *Manifest) : nullptr;
			if (Station)
			{
				// The station's own spot, then 4 m back from it into the open on the same floor.
				const FVector At = Station->Transform.GetLocation();
				const FVector Spot = C->GetNav().NearestWalkable(FVector2D(At), 300.0).Get(At);
				const FVector Back = (Spot - At).GetSafeNormal2D();
				const FVector Feet = C->GetNav().NearestWalkable(FVector2D(Spot + Back * 400.0), 150.0).Get(Spot);
				// Facing the station, so the camera behind stands in the open hangar.
				C->GetCommander()->PlaceAt(Feet, (At - Feet).Rotation().Yaw);
			}
			return true;
		}));
	// 1. Third person, mouse free: the commander walks forward, "click to look" below.
	Do([](UVerseDeckControlComponent& C)
		{
			C.PickView(EVerseDeckView::Third);
			C.SetMouseLook(false);
			C.GetCamera()->Rig.YawDeg = C.GetCommander()->GetActorRotation().Yaw;
			C.SetMoveAxes(FVector2D(0.0, 1.0));
		});
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.6f));
	Shot(TEXT("commander_third_walk"));
	// 2. Strafing right: the body leans 45 degrees into it.
	Do([](UVerseDeckControlComponent& C) { C.SetMoveAxes(FVector2D(1.0, 0.0)); });
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.3f));
	Do([](UVerseDeckControlComponent& C) { C.SetMoveAxes(FVector2D::ZeroVector); });
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.5f));
	Shot(TEXT("commander_third_strafe"));
	// 3. The salute, seen from the front.
	Do([](UVerseDeckControlComponent& C)
		{
			C.SetMoveAxes(FVector2D::ZeroVector);
			C.GetCamera()->Rig.YawDeg = C.GetCommander()->GetActorRotation().Yaw + 165.0;
			C.GetCamera()->Rig.PitchDeg = -4.0;
			C.Salute();
		});
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.1f));
	Shot(TEXT("commander_salute"));
	// 4. Dress uniform.
	Do([](UVerseDeckControlComponent& C) { C.WearUniform(TEXT("dress"), FLinearColor(0.20f, 0.035f, 0.025f, 1.f)); });
	Shot(TEXT("commander_uniform_dress"));
	// 5. Overview: hover a station (its label), the commander walking to a clicked floor point.
	TSharedRef<FName> Target = MakeShared<FName>();
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Manifest, Target]() -> bool
		{
			UVerseDeckControlComponent* C = Control();
			const FVerseDeckStation* Station = C ? NearStation(*C, *Manifest) : nullptr;
			if (C == nullptr || Station == nullptr)
			{
				AddError(TEXT("no station on the hangar for the hover label"));
				return true;
			}
			*Target = Station->Id;
			C->PickView(EVerseDeckView::Overview);
			const FVector Feet = C->GetCommander()->GetFeet();
			const FVector At = Station->Transform.GetLocation();
			C->GetCamera()->Overview.CentreCm = At;
			C->GetCamera()->Overview.DistanceCm = 2600.0;
			C->WalkTo(Feet + (At - Feet) * 0.5 + FVector(0.0, 300.0, 0.0));
			AddInfo(FString::Printf(TEXT("hover station %s (%s)"), *Station->Id.ToString(), *Station->Kind.ToString()));
			return true;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.6f));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Manifest, Target]() -> bool
		{
			UVerseDeckControlComponent* C = Control();
			const FVerseDeckStation* Station = Manifest->FindStation(*Target);
			if (C && Station)
			{
				// Find the station on screen by sampling picks around its projected point.
				const FVector2D Size = C->GetViewportSize();
				for (int32 Y = 0; Y < 108 && !State->Mouse.IsSet(); ++Y)
				{
					for (int32 X = 0; X < 192; ++X)
					{
						const FVector2D P(X * Size.X / 192.0, Y * Size.Y / 108.0);
						const FVerseDeckPick Pick = C->PickAt(P);
						// Any station on screen will do (the nearest one first gave the framing).
						if (Pick.Kind == FVerseDeckPick::EKind::Station)
						{
							*Target = Pick.Station;
							State->Mouse = P;
							break;
						}
					}
				}
				if (!State->Mouse.IsSet())
				{
					AddError(TEXT("the station is not under any screen point of the overview"));
				}
			}
			return true;
		}));
	Shot(TEXT("commander_overview_hover"));
	// 6. First person near the station, looking at it: the reticle marks it.
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Manifest, Target]() -> bool
		{
			UVerseDeckControlComponent* C = Control();
			const FVerseDeckStation* Station = Manifest->FindStation(*Target);
			State->Mouse.Reset();
			if (C == nullptr || Station == nullptr)
			{
				return true;
			}
			const FVector At = Station->Transform.GetLocation();
			const FVector Toward = Station->Transform.GetRotation().GetForwardVector();
			const TOptional<FVector> Spot = C->GetNav().NearestWalkable(FVector2D(At + Toward * 160.0), 200.0);
			const FVector Feet = Spot.Get(At + Toward * 160.0);
			C->GetCommander()->PlaceAt(Feet, (At - Feet).Rotation().Yaw);
			C->PickView(EVerseDeckView::First);
			C->GetCamera()->Rig.YawDeg = (At - Feet).Rotation().Yaw;
			C->GetCamera()->Rig.PitchDeg = -20.0;
			return true;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.6f));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this]() -> bool
		{
			if (const UVerseDeckControlComponent* C = Control())
			{
				AddInfo(FString::Printf(TEXT("reticle %d marked %d"), C->GetPointer().bReticle, C->GetPointer().bReticleMarked));
				if (!C->GetPointer().bReticle)
				{
					AddError(TEXT("no reticle in first person with mouse look"));
				}
			}
			return true;
		}));
	Shot(TEXT("commander_first_reticle"));
	Do([](UVerseDeckControlComponent& C) { C.PickView(EVerseDeckView::Third); });
	Shot(TEXT("commander_third_station"));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

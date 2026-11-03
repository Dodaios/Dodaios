#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Decks/VerseDeckManifest.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "EngineUtils.h"
#include "ShaderCompiler.h"
#include "Space/VerseSpaceView.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.Decks: the rendered evidence of WP12 (A12.2, A12.3; work-packages.md 0.4). Runs only
// on the GPU through scripts/unreal/screenshot.py. For every deck it cold-loads the level through
// the deck subsystem, waits for shaders and streaming, and takes eye-level reference shots in the
// largest rooms plus one overview; then it rides the lift once. Shots and `load_times.json` land
// in Saved/Harness/proof/WP12/visual/ (never committed); scripts measure the palette from them.

namespace VerseDecksVisual
{
	struct FView
	{
		FString Name;
		FVector Location;
		FRotator Rotation;
	};

	struct FState
	{
		FString OutDir;
		TSharedRef<FJsonObject> Timings = MakeShared<FJsonObject>();
		/** Every shot's camera, for today's reference renders of the same spots (`views.json`). */
		TArray<TSharedPtr<FJsonValue>> Views;
		double StartedAt = 0.0;
		TWeakObjectPtr<ACameraActor> Camera;
	};

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

	/** Eye-level views in the largest rooms (by polygon area), looking along each room's long axis; plus an overview. */
	TArray<FView> ViewsFor(const FVerseDeckManifest& Deck, int32 Count)
	{
		struct FScored
		{
			const FVerseDeckRoom* Room;
			double Area;
		};
		TArray<FScored> Rooms;
		for (const FVerseDeckRoom& Room : Deck.Rooms)
		{
			double Area = 0.0;
			for (int32 I = 0, J = Room.PolygonCm.Num() - 1; I < Room.PolygonCm.Num(); J = I++)
			{
				Area += Room.PolygonCm[J].X * Room.PolygonCm[I].Y - Room.PolygonCm[I].X * Room.PolygonCm[J].Y;
			}
			Rooms.Add({ &Room, FMath::Abs(Area) / 2.0 });
		}
		Rooms.Sort([](const FScored& A, const FScored& B) { return A.Area > B.Area; });

		TArray<FView> Views;
		for (int32 Index = 0; Views.Num() < Count && Rooms.Num() > 0; ++Index)
		{
			const FVerseDeckRoom& Room = *Rooms[Index % Rooms.Num()].Room;
			FBox2D Box(ForceInit);
			for (const FVector2D& Point : Room.PolygonCm)
			{
				Box += Point;
			}
			const FVector2D Size = Box.GetSize();
			const bool bAlongX = Size.X >= Size.Y;
			// A second pass over the rooms looks the other way.
			const double Yaw = (bAlongX ? 0.0 : 90.0) + (Index >= Rooms.Num() ? 180.0 : 0.0);
			const FVector2D Back = FVector2D(bAlongX ? -Size.X * 0.35 : 0.0, bAlongX ? 0.0 : -Size.Y * 0.35) * (Index >= Rooms.Num() ? -1.0 : 1.0);
			const FVector2D Eye = Box.GetCenter() + Back;
			Views.Add({ FString::Printf(TEXT("%s_eye_%d_%s"), *Deck.Deck.ToString(), Views.Num() + 1, *Room.Id.ToString()),
				FVector(Eye.X, Eye.Y, Room.ZCm + 165.0), FRotator(-5.0, Yaw, 0.0) });
		}
		FBox Bounds(ForceInit);
		for (const FVerseDeckRoom& Room : Deck.Rooms)
		{
			for (const FVector2D& Point : Room.PolygonCm)
			{
				Bounds += FVector(Point.X, Point.Y, Room.ZCm);
			}
		}
		const FRotator Down(-60.0, 90.0, 0.0);
		const double Distance = FMath::Max(Bounds.GetSize().X, Bounds.GetSize().Y) * 0.9;
		Views.Add({ Deck.Deck.ToString() + TEXT("_overview"), Bounds.GetCenter() - Down.Vector() * Distance, Down });
		return Views;
	}

	bool ShadersDone()
	{
		return GShaderCompilingManager == nullptr || GShaderCompilingManager->GetNumRemainingJobs() == 0;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualDecksTest, "Verse.Visual.Decks", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualDecksTest::RunTest(const FString&)
{
	using namespace VerseDecksVisual;

	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.Decks needs a GPU (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> State = MakeShared<FState>();
	State->OutDir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/WP12/visual")));
	IFileManager::Get().MakeDirectory(*State->OutDir, true);

	for (const FVerseDeckInfo& Info : Verse::Decks::All())
	{
		FVerseDeckManifest Manifest;
		FString Error;
		if (!FVerseDeckManifest::Load(Info.Id, Verse::Decks::PlacementsDir(), Manifest, Error))
		{
			AddError(Error);
			continue;
		}
		const FName Deck = Info.Id;
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Deck]() -> bool
			{
				UVerseDeckSubsystem* Subsystem = Decks();
				if (Subsystem == nullptr)
				{
					AddError(TEXT("no deck subsystem in the game world"));
					return true;
				}
				State->StartedAt = FPlatformTime::Seconds();
				if (!Subsystem->LoadDeckDirect(Deck))
				{
					AddError(FString::Printf(TEXT("deck %s did not start loading"), *Deck.ToString()));
				}
				return true;
			}));
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, Deck]() -> bool
			{
				UVerseDeckSubsystem* Subsystem = Decks();
				UWorld* World = GameWorld();
				const bool bThere = Subsystem && Subsystem->GetCurrentDeck() == Deck && World && World->HasBegunPlay();
				if (bThere)
				{
					State->Timings->SetNumberField(Deck.ToString() + TEXT("_cold_load_s"), Subsystem->GetLastColdLoadS());
					State->Timings->SetNumberField(Deck.ToString() + TEXT("_ceiling_actors"), Subsystem->NumCeilingActors());
					if (Subsystem->NumCeilingActors() == 0)
					{
						AddError(FString::Printf(TEXT("deck %s has no ceiling actors for the overview cutaway"), *Deck.ToString()));
					}
					return true;
				}
				if (FPlatformTime::Seconds() - State->StartedAt > 60.0)
				{
					AddError(FString::Printf(TEXT("deck %s did not arrive within 60 s"), *Deck.ToString()));
					return true;
				}
				return false;
			}));
		// Shaders and streaming settle before the first shot (orchestration.md 5.3).
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([State]() -> bool
			{
				static double Since = 0.0;
				if (!ShadersDone())
				{
					Since = 0.0;
					return false;
				}
				if (Since == 0.0)
				{
					Since = FPlatformTime::Seconds();
				}
				if (FPlatformTime::Seconds() - Since > 4.0)
				{
					Since = 0.0;
					return true;
				}
				return false;
			}));
		for (const FView& View : ViewsFor(Manifest, 4))
		{
			{
				const TSharedRef<FJsonObject> Shot = MakeShared<FJsonObject>();
				Shot->SetStringField(TEXT("name"), View.Name);
				Shot->SetStringField(TEXT("deck"), Deck.ToString());
				const FVector Forward = View.Rotation.Vector();
				TArray<TSharedPtr<FJsonValue>> Location;
				TArray<TSharedPtr<FJsonValue>> Direction;
				for (int32 Axis = 0; Axis < 3; ++Axis)
				{
					Location.Add(MakeShared<FJsonValueNumber>(View.Location[Axis]));
					Direction.Add(MakeShared<FJsonValueNumber>(Forward[Axis]));
				}
				Shot->SetArrayField(TEXT("location_cm"), Location);
				Shot->SetArrayField(TEXT("forward"), Direction);
				Shot->SetNumberField(TEXT("hfov_deg"), 85.0);
				State->Views.Add(MakeShared<FJsonValueObject>(Shot));
			}
			ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([State, View]() -> bool
				{
					UWorld* World = GameWorld();
					if (World == nullptr)
					{
						return true;
					}
					ACameraActor* Camera = State->Camera.Get();
					if (Camera == nullptr || Camera->GetWorld() != World)
					{
						FActorSpawnParameters Params;
						Params.ObjectFlags |= RF_Transient;
						Camera = World->SpawnActor<ACameraActor>(Params);
						Camera->GetCameraComponent()->SetFieldOfView(85.f);
						Camera->GetCameraComponent()->SetConstraintAspectRatio(false);
						State->Camera = Camera;
					}
					Camera->SetActorLocationAndRotation(View.Location, View.Rotation);
					// The overview is a cutaway (no ceilings); eye-level views keep them.
					if (UVerseDeckSubsystem* Subsystem = Decks())
					{
						Subsystem->SetCutawayOverride(View.Name.EndsWith(TEXT("_overview")));
					}
					if (APlayerController* Controller = World->GetFirstPlayerController())
					{
						Controller->SetViewTarget(Camera);
					}
					return true;
				}));
			ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.5f));
			ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([State, View]() -> bool
				{
					FScreenshotRequest::RequestScreenshot(FPaths::Combine(State->OutDir, View.Name + TEXT(".png")), false, false);
					return true;
				}));
			ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.0f));
		}
	}

	// The space backdrop on its own (WP12.9): every other actor hidden, the camera at the space
	// view looking at the Earth and up at the stars. `kit/space_check.py` fails a black frame.
	for (const FView& View : { FView{ TEXT("space_earth"), FVector::ZeroVector, FRotator(-56.0, 0.0, 0.0) }, FView{ TEXT("space_stars"), FVector::ZeroVector, FRotator(50.0, 180.0, 0.0) } })
	{
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State, View]() -> bool
			{
				UWorld* World = GameWorld();
				AVerseSpaceView* Space = nullptr;
				for (TActorIterator<AVerseSpaceView> It(World); It; ++It)
				{
					Space = *It;
				}
				if (World == nullptr || Space == nullptr)
				{
					AddError(TEXT("no space view on the deck"));
					return true;
				}
				AddInfo(FString::Printf(TEXT("space view: %d of 4 backdrop assets"), Space->LoadBackdrop()));
				for (TActorIterator<AActor> It(World); It; ++It)
				{
					if (*It != Space && *It != State->Camera.Get() && !It->IsA<APlayerController>())
					{
						It->SetActorHiddenInGame(true);
					}
				}
				if (ACameraActor* Camera = State->Camera.Get())
				{
					Camera->SetActorLocationAndRotation(Space->GetActorLocation(), View.Rotation);
					if (APlayerController* Controller = World->GetFirstPlayerController())
					{
						Controller->SetViewTarget(Camera);
					}
				}
				return true;
			}));
		ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.5f));
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([State, View]() -> bool
			{
				FScreenshotRequest::RequestScreenshot(FPaths::Combine(State->OutDir, View.Name + TEXT(".png")), false, false);
				return true;
			}));
		ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.0f));
	}

	// One lift ride, measured by the lift itself (A12.2).
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
		{
			UVerseDeckSubsystem* Subsystem = Decks();
			if (Subsystem != nullptr)
			{
				Subsystem->SetCutawayOverride(TOptional<bool>());
			}
			if (Subsystem == nullptr || !Subsystem->RequestDeck(TEXT("ops")))
			{
				AddError(TEXT("lift ride to ops did not start"));
			}
			State->StartedAt = FPlatformTime::Seconds();
			return true;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
		{
			UVerseDeckSubsystem* Subsystem = Decks();
			if (Subsystem && !Subsystem->GetLift().IsBusy() && Subsystem->GetCurrentDeck() == FName(TEXT("ops")))
			{
				State->Timings->SetNumberField(TEXT("lift_hangar_to_ops_s"), Subsystem->GetLift().LastRideS());
				State->Timings->SetNumberField(TEXT("lift_hangar_to_ops_load_s"), Subsystem->GetLift().LastLoadS());
				State->Timings->SetBoolField(TEXT("lift_deck_missing"), Subsystem->GetLift().DeckMissing());
				return true;
			}
			if (FPlatformTime::Seconds() - State->StartedAt > 30.0)
			{
				AddError(TEXT("lift ride did not finish within 30 s"));
				return true;
			}
			return false;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([State]() -> bool
		{
			FString Json;
			const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Json);
			FJsonSerializer::Serialize(State->Timings, Writer);
			FFileHelper::SaveStringToFile(Json, *FPaths::Combine(State->OutDir, TEXT("load_times.json")));
			FString ViewsJson;
			const TSharedRef<TJsonWriter<>> ViewsWriter = TJsonWriterFactory<>::Create(&ViewsJson);
			FJsonSerializer::Serialize(State->Views, ViewsWriter);
			FFileHelper::SaveStringToFile(ViewsJson, *FPaths::Combine(State->OutDir, TEXT("views.json")));
			return true;
		}));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

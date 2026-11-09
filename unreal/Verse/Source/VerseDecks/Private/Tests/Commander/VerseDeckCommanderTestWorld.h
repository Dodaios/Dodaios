#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Camera/CameraComponent.h"
#include "Camera/VerseDeckCamera.h"
#include "Commander/VerseDeckCommander.h"
#include "Components/CapsuleComponent.h"
#include "Components/StaticMeshComponent.h"
#include "CoreMinimal.h"
#include "Decks/VerseDeckManifest.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/WorldSettings.h"
#include "Input/VerseDeckControlComponent.h"
#include "Misc/App.h"

/**
 * A transient game world with a 40 x 40 m test deck for the commander's parity tests: a floor
 * at Z 0, one wall across the middle (X 0, Y -8 m .. 8 m, 3 m high), one room covering the floor,
 * a service-record station at (10 m, 0) and the commander's spawn at (-15 m, 0) facing +X. A
 * player controller (no local player) carries the deck control; seams pin focus, chords, the
 * viewport and the mouse. Ticks at 60 Hz.
 */
struct FVerseDeckCommanderTestWorld
{
	static constexpr double Tick = 1.0 / 60.0;
	static inline const FName DeckId = TEXT("testdeck");
	static inline const FName StationId = TEXT("station_record");

	UWorld* World = nullptr;
	APlayerController* Controller = nullptr;
	AVerseDeckCamera* Camera = nullptr;
	UVerseDeckControlComponent* Control = nullptr;
	FVerseDeckManifest Manifest;
	FTransform Arrival;
	bool bFocused = true;
	bool bChord = false;
	TOptional<FVector2D> Mouse;
	FVector2D Viewport = FVector2D(1920.0, 1080.0);

	FVerseDeckCommanderTestWorld()
	{
		World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseDeckCommanderTest")));
		FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
		Context.SetCurrentWorld(World);
		World->InitializeActorsForPlay(FURL());
		World->BeginPlay();
		if (!World->GetBegunPlay())
		{
			World->GetWorldSettings()->NotifyBeginPlay();
		}
		Block(FVector(0.0, 0.0, -10.0), FVector(4000.0, 4000.0, 20.0));
		Block(FVector(0.0, 0.0, 150.0), FVector(40.0, 1600.0, 300.0));

		Manifest.Deck = DeckId;
		FVerseDeckRoom Room;
		Room.Id = TEXT("room_main");
		Room.Name = TEXT("Main");
		Room.PolygonCm = { FVector2D(-2000.0, -2000.0), FVector2D(2000.0, -2000.0), FVector2D(2000.0, 2000.0), FVector2D(-2000.0, 2000.0) };
		Room.bMain = true;
		Manifest.Rooms.Add(Room);
		FVerseDeckStation Station;
		Station.Id = StationId;
		Station.Kind = TEXT("service_record");
		Station.Room = Room.Id;
		Station.Transform = FTransform(FRotator(0.0, 180.0, 0.0), FVector(1000.0, 0.0, 0.0));
		Manifest.Stations.Add(Station);
		Arrival = FTransform(FRotator(0.0, 0.0, 0.0), FVector(-1500.0, 0.0, 0.0));

		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		Controller = World->SpawnActor<APlayerController>(APlayerController::StaticClass(), Params);
		Camera = World->SpawnActor<AVerseDeckCamera>(Params);
		Control = UVerseDeckControlComponent::Ensure(Controller);
		Control->WindowFocused = [this]() { return bFocused; };
		Control->ChordProbe = [this]() { return bChord; };
		Control->ViewportSize = [this]() { return Viewport; };
		Control->MousePosition = [this]() { return Mouse; };
		Camera->FrameArrival(Arrival);
		Control->OnDeckArrived(DeckId, Manifest, Arrival, Camera);
		Step(2);
	}

	~FVerseDeckCommanderTestWorld()
	{
		World->EndPlay(EEndPlayReason::Quit);
		GEngine->DestroyWorldContext(World);
		World->DestroyWorld(false);
	}

	AStaticMeshActor* Block(const FVector& Centre, const FVector& SizeCm)
	{
		UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), FTransform(FRotator::ZeroRotator, Centre, SizeCm / 100.0), Params);
		UStaticMeshComponent* Mesh = Actor->GetStaticMeshComponent();
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->SetStaticMesh(Cube);
		Mesh->SetCollisionProfileName(TEXT("BlockAll"));
		Actor->SetActorTransform(FTransform(FRotator::ZeroRotator, Centre, SizeCm / 100.0));
		return Actor;
	}

	/** A plain character standing at `Feet` (a crew member for the picks). */
	ACharacter* Person(const FVector& Feet)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		ACharacter* Character = World->SpawnActor<ACharacter>(ACharacter::StaticClass(), Feet + FVector(0.0, 0.0, 90.0), FRotator::ZeroRotator, Params);
		Character->GetCharacterMovement()->SetMovementMode(MOVE_None);
		return Character;
	}

	AVerseDeckCommander* Commander() const { return Control->GetCommander(); }

	void Step(int32 Ticks = 1)
	{
		for (int32 I = 0; I < Ticks; ++I)
		{
			++GFrameCounter;
			World->Tick(LEVELTICK_All, float(Tick));
		}
	}

	/** Ticks until `Done` or `MaxSeconds` pass; true when it came true. */
	bool StepUntil(TFunctionRef<bool()> Done, double MaxSeconds)
	{
		for (int32 I = 0; I < int32(MaxSeconds / Tick); ++I)
		{
			if (Done())
			{
				return true;
			}
			Step();
		}
		return Done();
	}

	/** The overview centred on `Centre`, looking straight down from `HeightCm`, applied to the camera. */
	void Overview(const FVector& Centre, double DistanceCm = 2500.0)
	{
		Control->PickView(EVerseDeckView::Overview);
		Camera->Overview.CentreCm = Centre;
		Camera->Overview.DistanceCm = DistanceCm;
		Camera->Overview.PitchDeg = -89.0;
		Camera->Tick(0.f);
	}

	/** The screen point of a world point in the deck camera (pixels). */
	FVector2D ToScreen(const FVector& Point) const
	{
		const FRotationMatrix Basis(Camera->GetActorRotation());
		const FVector D = Point - Camera->GetActorLocation();
		const double Fwd = FVector::DotProduct(D, Basis.GetUnitAxis(EAxis::X));
		const double TanH = FMath::Tan(FMath::DegreesToRadians(Camera->Camera->FieldOfView * 0.5));
		const double TanV = TanH * Viewport.Y / Viewport.X;
		const double X = FVector::DotProduct(D, Basis.GetUnitAxis(EAxis::Y)) / (Fwd * TanH);
		const double Y = FVector::DotProduct(D, Basis.GetUnitAxis(EAxis::Z)) / (Fwd * TanV);
		return FVector2D((X + 1.0) * 0.5 * Viewport.X, (1.0 - Y) * 0.5 * Viewport.Y);
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS

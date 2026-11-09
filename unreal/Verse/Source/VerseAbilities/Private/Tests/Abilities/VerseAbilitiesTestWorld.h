#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/StaticMeshComponent.h"
#include "CoreMinimal.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Components/CapsuleComponent.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/WorldSettings.h"

namespace VerseAbilitiesTest
{
	inline const TCHAR* CubePath = TEXT("/Engine/BasicShapes/Cube.Cube");

	/** A transient game world that has begun play (components get BeginPlay), with a floor at z = 0 on demand. */
	struct FWorld
	{
		UWorld* World = nullptr;

		explicit FWorld(const TCHAR* Name = TEXT("VerseAbilitiesTestWorld"))
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(nullptr, UWorld::StaticClass(), Name));
			FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
			Context.SetCurrentWorld(World);
			World->InitializeActorsForPlay(FURL());
			World->BeginPlay();
			if (!World->GetBegunPlay())
			{
				World->GetWorldSettings()->NotifyBeginPlay();
			}
		}

		~FWorld()
		{
			World->EndPlay(EEndPlayReason::Quit);
			GEngine->DestroyWorldContext(World);
			World->DestroyWorld(false);
		}

		AStaticMeshActor* AddBox(const FVector& Centre, const FVector& SizeCm)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), FTransform(Centre), Params);
			UStaticMeshComponent* Mesh = Actor->GetStaticMeshComponent();
			Mesh->SetMobility(EComponentMobility::Movable);
			Mesh->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, CubePath));
			Mesh->SetWorldScale3D(SizeCm / 100.0);
			Mesh->SetCollisionProfileName(TEXT("BlockAll"));
			Mesh->RecreatePhysicsState();
			World->Tick(LEVELTICK_All, 1.f / 60.f);
			return Actor;
		}

		/** Floor top at z = 0. */
		void AddFloor() { AddBox(FVector(0.0, 0.0, -10.0), FVector(4000.0, 4000.0, 20.0)); }

		/** A bare pawn (a scene root) at `At` facing `YawDeg`. */
		APawn* AddPawn(const FVector& At, double YawDeg)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			APawn* Pawn = World->SpawnActor<APawn>(APawn::StaticClass(), At, FRotator(0.0, YawDeg, 0.0), Params);
			USceneComponent* Root = NewObject<USceneComponent>(Pawn, TEXT("Root"));
			Root->SetMobility(EComponentMobility::Movable);
			Pawn->SetRootComponent(Root);
			Root->RegisterComponent();
			Pawn->SetActorLocationAndRotation(At, FRotator(0.0, YawDeg, 0.0));
			return Pawn;
		}

		/** A plain character whose feet stand on `Feet`, facing `YawDeg`, walking. */
		ACharacter* AddCharacter(const FVector& Feet, double YawDeg)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			ACharacter* Character = World->SpawnActor<ACharacter>(ACharacter::StaticClass(), Feet, FRotator(0.0, YawDeg, 0.0), Params);
			const double Half = Character->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
			Character->SetActorLocation(Feet + FVector(0.0, 0.0, Half));
			Character->GetCharacterMovement()->SetMovementMode(MOVE_Walking);
			return Character;
		}

		/** A player controller (no local player) possessing `Pawn`. */
		APlayerController* Possess(APawn* Pawn)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			APlayerController* Controller = World->SpawnActor<APlayerController>(APlayerController::StaticClass(), Params);
			Controller->Possess(Pawn);
			return Controller;
		}
	};
}

#endif // WITH_DEV_AUTOMATION_TESTS

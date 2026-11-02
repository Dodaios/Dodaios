#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "CoreMinimal.h"
#include "Engine/Engine.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Pawn.h"
#include "Gore/VerseGoreSubsystem.h"
#include "Materials/MaterialInterface.h"
#include "Misc/Paths.h"

#define VERSE_GORE_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseGoreTest
{
	/** Placeholder art: the G0 test human and the engine's unit cube (referenced, never committed). */
	inline const TCHAR* TestHumanPath = TEXT("/Game/Verse/Test/G0/SK_Test_Human.SK_Test_Human");
	inline const TCHAR* CubePath = TEXT("/Engine/BasicShapes/Cube.Cube");
	/** The WP13 fake: a body material with the wound mask parameters (built by art/verse/gore). */
	inline const TCHAR* WoundMaterialPath = TEXT("/Game/Verse/Test/WP05/M_Gore_TestBody.M_Gore_TestBody");

	/** Proof folder of work-packages.md 0.4 for one sub-task. */
	inline FString ProofDir(const TCHAR* SubTask)
	{
		return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/WP05"), SubTask);
	}

	/**
	 * A bare game world with its subsystems and a physics scene, gore forced on (tests run under
	 * -nullrhi). Bodies are pawns with a skeletal mesh; the resolver maps ids to them.
	 */
	struct FWorld
	{
		UWorld* World = nullptr;
		UVerseGoreSubsystem* Gore = nullptr;
		UVerseEventHub* Hub = nullptr;
		TMap<int32, TWeakObjectPtr<USkeletalMeshComponent>> Bodies;

		explicit FWorld(bool bForceGore = true, const TCHAR* Name = TEXT("VerseGoreTestWorld"))
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(nullptr, UWorld::StaticClass(), Name));
			Gore = World ? World->GetSubsystem<UVerseGoreSubsystem>() : nullptr;
			Hub = World ? World->GetSubsystem<UVerseEventHub>() : nullptr;
			if (Gore)
			{
				Gore->SetForceActive(bForceGore);
				Gore->SetGoreLevel(EVerseGoreLevel::Full);
				Gore->SetVictimResolver([this](int32 Id) -> USkeletalMeshComponent*
				{
					const TWeakObjectPtr<USkeletalMeshComponent>* Found = Bodies.Find(Id);
					return Found ? Found->Get() : nullptr;
				});
			}
		}

		~FWorld()
		{
			if (Gore)
			{
				Gore->SetVictimResolver(nullptr);
			}
			if (World)
			{
				World->DestroyWorld(false);
			}
		}

		bool IsValid() const { return World && Gore && Hub; }

		/** A blocking box: centre and size in cm. */
		AStaticMeshActor* AddBox(const FVector& Centre, const FVector& SizeCm)
		{
			UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, CubePath);
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), FTransform(Centre), Params);
			UStaticMeshComponent* Component = Actor->GetStaticMeshComponent();
			Component->SetMobility(EComponentMobility::Movable);
			Component->SetStaticMesh(Cube);
			Component->SetWorldScale3D(SizeCm / 100.0);
			Component->SetCollisionProfileName(TEXT("BlockAll"));
			Component->RecreatePhysicsState();
			return Actor;
		}

		/** Floor top at z = 0 and a wall whose face looks down -X at x = WallX. */
		void AddRoom(double WallX = 150.0)
		{
			AddBox(FVector(0.0, 0.0, -10.0), FVector(2000.0, 2000.0, 20.0));
			AddBox(FVector(WallX + 10.0, 0.0, 200.0), FVector(20.0, 2000.0, 400.0));
		}

		/** A body standing on the floor point `Feet`; its id resolves to its mesh. */
		USkeletalMeshComponent* AddBody(int32 Id, const FVector& Feet, UMaterialInterface* Override = nullptr)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			APawn* Pawn = World->SpawnActor<APawn>(APawn::StaticClass(), FTransform(Feet), Params);
			USkeletalMeshComponent* Mesh = NewObject<USkeletalMeshComponent>(Pawn, TEXT("Body"));
			Mesh->SetMobility(EComponentMobility::Movable);
			Mesh->SetSkeletalMeshAsset(LoadObject<USkeletalMesh>(nullptr, TestHumanPath));
			Pawn->SetRootComponent(Mesh);
			Mesh->RegisterComponent();
			Mesh->SetWorldLocation(Feet);
			if (Override)
			{
				for (int32 Slot = 0; Slot < FMath::Max(1, Mesh->GetNumMaterials()); ++Slot)
				{
					Mesh->SetMaterial(Slot, Override);
				}
			}
			Bodies.Add(Id, Mesh);
			return Mesh;
		}

		/** Steps gore time in fixed frames. */
		void Advance(double Seconds, double Step = 1.0 / 60.0)
		{
			for (double T = 0.0; T < Seconds - 1e-9; T += Step)
			{
				Gore->AdvanceTime(float(FMath::Min(Step, Seconds - T)));
			}
		}
	};
}

#endif // WITH_DEV_AUTOMATION_TESTS

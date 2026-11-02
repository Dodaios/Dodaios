#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/AutomationTest.h"
#include "Projectiles/VerseBoltPresentation.h"
#include "Tests/AutomationCommon.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"
#include "UnrealClient.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.Combat.Bolts (WP02.11 evidence, rendered lane only: scripts/unreal/screenshot.py):
// a first-person view with the viewer's own bolts in amber and the opponent's in red, frozen mid
// flight. Synthetic scene (dark floor, one work light); the PNG goes to the proof folder.

namespace VerseBoltVisual
{
	struct FState
	{
		TWeakObjectPtr<UWorld> World;
		TArray<TWeakObjectPtr<AActor>> Spawned;
		FString Path;
	};

	UWorld* GameWorld()
	{
		for (const FWorldContext& C : GEngine->GetWorldContexts())
		{
			if (C.WorldType == EWorldType::Game && C.World())
			{
				return C.World();
			}
		}
		return nullptr;
	}

	void Setup(const TSharedRef<FState>& S)
	{
		UWorld* World = GameWorld();
		S->World = World;
		if (!World)
		{
			return;
		}
		FActorSpawnParameters P;
		P.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

		UStaticMesh* Plane = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Plane.Plane"));
		UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
		if (AStaticMeshActor* Floor = World->SpawnActor<AStaticMeshActor>(FVector(3000, 0, 0), FRotator::ZeroRotator, P))
		{
			Floor->SetMobility(EComponentMobility::Movable);
			Floor->GetStaticMeshComponent()->SetStaticMesh(Plane);
			Floor->SetActorScale3D(FVector(100, 100, 1));
			if (UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, Floor))
			{
				Mid->SetVectorParameterValue(TEXT("Color"), FLinearColor(0.02f, 0.02f, 0.022f));
				Floor->GetStaticMeshComponent()->SetMaterial(0, Mid);
			}
			S->Spawned.Add(Floor);
		}
		if (ADirectionalLight* Light = World->SpawnActor<ADirectionalLight>(FVector::ZeroVector, FRotator(-35, 30, 0), P))
		{
			Light->SetMobility(EComponentMobility::Movable);
			Light->GetComponent()->SetIntensity(4.f);
			S->Spawned.Add(Light);
		}
		if (ACameraActor* Camera = World->SpawnActor<ACameraActor>(FVector(0, 0, 160), FRotator(-2, 0, 0), P))
		{
			Camera->GetCameraComponent()->SetFieldOfView(90.f);
			if (APlayerController* Pc = World->GetFirstPlayerController())
			{
				Pc->SetViewTarget(Camera);
			}
			S->Spawned.Add(Camera);
		}

		UVerseBoltPresentation* Present = UVerseBoltPresentation::Get(World);
		if (!Present)
		{
			return;
		}
		Present->LocalPlayerIdOverride = 1;
		double Clock = 100.0;
		Present->ClockOverride = [&Clock]() { return Clock; };
		UVerseEventHub* Hub = UVerseEventHub::Get(World);
		// Own volley from the muzzle (right of the eye), staggered in time like a spray.
		for (int32 I = 0; I < 6; ++I)
		{
			FVerseFireEvent E;
			E.ShooterId = 1;
			E.WeaponId = TEXT("graveline");
			E.ShotCounter = uint16(I + 1);
			E.Origin = FVector(30, 18, 148);
			E.Direction = FRotator(0.3f * I, -1.5f + 0.5f * I, 0).Vector();
			Clock = 100.0 - 0.012 * I;
			Hub->OnFire.Broadcast(E);
		}
		// The opponent's bolts coming in from the far side.
		for (int32 I = 0; I < 4; ++I)
		{
			FVerseFireEvent E;
			E.ShooterId = 2;
			E.WeaponId = TEXT("graveline");
			E.ShotCounter = uint16(I + 1);
			E.Origin = FVector(4500, -900 + 120 * I, 170);
			E.Direction = (FVector(0, 200 - 60 * I, 150) - FVector(E.Origin)).GetSafeNormal();
			Clock = 100.0 - 0.02 * I;
			Hub->OnFire.Broadcast(E);
		}
		// Freeze the flight mid-way so the shot holds still while shaders and streaming settle.
		Present->ClockOverride = []() { return 100.0 + 0.06; };
		Present->Advance(100.06);
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualBolts, "Verse.Visual.Combat.Bolts",
	EAutomationTestFlags::ClientContext | EAutomationTestFlags::EngineFilter)
bool FVerseVisualBolts::RunTest(const FString&)
{
	TSharedRef<VerseBoltVisual::FState> S = MakeShared<VerseBoltVisual::FState>();
	S->Path = VerseWp02Test::ProofPath(TEXT("2.11"), TEXT("bolts_first_person.png"));
	IFileManager::Get().Delete(*S->Path, false, true, true);
	IFileManager::Get().MakeDirectory(*FPaths::GetPath(S->Path), true);

	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, S]()
	{
		VerseBoltVisual::Setup(S);
		TestTrue(TEXT("a game world to draw in"), S->World.IsValid());
		const UVerseBoltPresentation* P = UVerseBoltPresentation::Get(S->World.Get());
		TestTrue(TEXT("own bolts in flight"), P && P->NumOwn() == 6);
		TestTrue(TEXT("opponent bolts in flight"), P && P->NumFoe() == 4);
		return true;
	}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(3.0f));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([S]()
	{
		FScreenshotRequest::RequestScreenshot(S->Path, false, false);
		return true;
	}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.5f));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, S]()
	{
		TestTrue(FString::Printf(TEXT("screenshot written to %s"), *S->Path), IFileManager::Get().FileExists(*S->Path));
		for (const TWeakObjectPtr<AActor>& A : S->Spawned)
		{
			if (A.IsValid())
			{
				A->Destroy();
			}
		}
		return true;
	}));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

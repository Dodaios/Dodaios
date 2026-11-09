#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS && WITH_EDITOR

#include "Abilities/VerseHoverboardComponent.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/PointLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "GameFramework/Character.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Misc/App.h"
#include "Misc/Paths.h"
#include "ShaderCompiler.h"
#include "UnrealClient.h"

// Verse.Visual.Abilities.Hoverboard: the board folded out under a stand-in commander (a capsule; the
// Sovereign mesh arrives with WP13), at rest and gliding, in a dim bay. Rendered `-game` run only
// (scripts/unreal/screenshot.py --suite Verse.Visual.Abilities); shots in Saved/Harness/proof/S7/visual/.

namespace VerseBoardVisual
{
	const FVector Base(0.0, -36000.0, 0.0);

	struct FState
	{
		UWorld* World = nullptr;
		ACameraActor* Camera = nullptr;
		ACharacter* Rider = nullptr;
		UVerseHoverboardComponent* Board = nullptr;
		TArray<AActor*> Spawned;
		FString Dir;
		int32 Shots = 0;
	};

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

	template <typename T>
	T* Spawn(FState& S, const FTransform& At)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		T* Actor = S.World->SpawnActor<T>(T::StaticClass(), At, Params);
		S.Spawned.Add(Actor);
		return Actor;
	}

	void Box(FState& S, const FVector& Centre, const FVector& Size)
	{
		AStaticMeshActor* Actor = Spawn<AStaticMeshActor>(S, FTransform(Base + Centre));
		UStaticMeshComponent* Mesh = Actor->GetStaticMeshComponent();
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube")));
		Mesh->SetWorldScale3D(Size / 100.0);
		Mesh->SetCollisionProfileName(TEXT("BlockAll"));
	}

	void Look(FState& S, const FVector& From, const FVector& At)
	{
		S.Camera->SetActorLocationAndRotation(From, (At - From).Rotation());
		if (APlayerController* Controller = S.World->GetFirstPlayerController())
		{
			Controller->SetViewTarget(S.Camera);
		}
	}

	void Setup(FState& S)
	{
		S.World = GameWorld();
		if (!S.World)
		{
			return;
		}
		Box(S, FVector(0.0, 0.0, -10.0), FVector(6000.0, 6000.0, 20.0));
		Box(S, FVector(0.0, 600.0, 300.0), FVector(6000.0, 20.0, 600.0));
		APointLight* Lamp = Spawn<APointLight>(S, FTransform(Base + FVector(-150.0, -250.0, 350.0)));
		Lamp->PointLightComponent->SetMobility(EComponentMobility::Movable);
		Lamp->PointLightComponent->SetIntensity(2500.f);
		Lamp->PointLightComponent->SetAttenuationRadius(1600.f);
		Lamp->PointLightComponent->SetLightColor(FLinearColor(1.f, 0.88f, 0.72f));
		S.Rider = Spawn<ACharacter>(S, FTransform(Base + FVector(0.0, 0.0, 100.0)));
		// A stand-in body: a 40 cm column from the feet to 1.75 m.
		UStaticMeshComponent* Body = NewObject<UStaticMeshComponent>(S.Rider, TEXT("StandIn"));
		Body->SetupAttachment(S.Rider->GetRootComponent());
		Body->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cylinder.Cylinder")));
		Body->SetRelativeLocation(FVector(0.0, 0.0, 87.5 - S.Rider->GetCapsuleComponent()->GetScaledCapsuleHalfHeight()));
		Body->SetRelativeScale3D(FVector(0.4, 0.4, 1.75));
		Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Body->RegisterComponent();
		S.Board = NewObject<UVerseHoverboardComponent>(S.Rider, TEXT("Hoverboard"));
		S.Board->SetupAttachment(S.Rider->GetRootComponent());
		S.Board->RegisterComponent();
		S.Camera = Spawn<ACameraActor>(S, FTransform(Base));
		UCameraComponent* Cam = S.Camera->GetCameraComponent();
		Cam->SetFieldOfView(50.f);
		Cam->PostProcessSettings.bOverride_AutoExposureMethod = true;
		Cam->PostProcessSettings.AutoExposureMethod = AEM_Manual;
		Cam->PostProcessSettings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
		Cam->PostProcessSettings.AutoExposureApplyPhysicalCameraExposure = 0;
		Cam->PostProcessSettings.bOverride_AutoExposureBias = true;
		Cam->PostProcessSettings.AutoExposureBias = 0.5f;
		Cam->PostProcessBlendWeight = 1.f;
		S.Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/S7/visual"));
		IFileManager::Get().MakeDirectory(*S.Dir, true);
	}

	void Shoot(FState& S, const TCHAR* Name)
	{
		FScreenshotRequest::RequestScreenshot(FPaths::Combine(S.Dir, FString::Printf(TEXT("%s.png"), Name)), false, false);
		++S.Shots;
	}

	/** Feet of the rider, world. */
	FVector Feet(const FState& S)
	{
		return S.Rider->GetActorLocation() - FVector(0.0, 0.0, S.Rider->GetCapsuleComponent()->GetScaledCapsuleHalfHeight());
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAbilitiesVisualHoverboard, "Verse.Visual.Abilities.Hoverboard",
	EAutomationTestFlags::ClientContext | EAutomationTestFlags::EngineFilter)
bool FVerseAbilitiesVisualHoverboard::RunTest(const FString&)
{
	using namespace VerseBoardVisual;
	if (!FApp::CanEverRender())
	{
		AddInfo(TEXT("no RHI: the hoverboard shots need a rendered -game run (screenshot.py)"));
		return true;
	}
	TSharedRef<FState> S = MakeShared<FState>();
	Setup(*S);
	if (!TestNotNull(TEXT("game world"), S->World))
	{
		return false;
	}
	auto Wait = [this](int32 Frames)
	{
		TSharedRef<int32> Count = MakeShared<int32>(0);
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([Count, Frames]() { return ++(*Count) >= Frames; }));
	};
	auto Do = [this](TFunction<void()> Step)
	{
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([Step]() { Step(); return true; }));
	};
	Do([S]() { S->Board->SetOn(true); });
	Wait(30);
	Do([]() { if (GShaderCompilingManager) { GShaderCompilingManager->FinishAllCompilation(); } });
	Wait(60);
	Do([S]() { Look(*S, Feet(*S) + FVector(-110.0, -150.0, 70.0), Feet(*S)); });
	Wait(5);
	Do([S]() { Shoot(*S, TEXT("board_rest")); });
	Wait(5);
	Do([S]() { Look(*S, Feet(*S) + FVector(0.0, -90.0, -2.0), Feet(*S) + FVector(0.0, 0.0, -6.0)); });
	Wait(5);
	Do([S]() { Shoot(*S, TEXT("board_low")); });
	Wait(5);
	// Glide along +X for a second and a half, the camera keeping pace beside the rider.
	TSharedRef<int32> Frames = MakeShared<int32>(0);
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([S, Frames]()
	{
		S->Board->SetMoveInput(FVector2D(1.0, 0.0), false);
		Look(*S, Feet(*S) + FVector(-60.0, -260.0, 110.0), Feet(*S) + FVector(40.0, 0.0, 30.0));
		return ++(*Frames) >= 45;
	}));
	Do([S]() { S->Board->SetMoveInput(FVector2D(1.0, 0.0), false); Shoot(*S, TEXT("board_glide")); });
	Wait(5);
	Do([this, S]()
	{
		TestEqual(TEXT("three screenshots requested"), S->Shots, 3);
		TestTrue(TEXT("gliding"), S->Board->GetSpeed() > 200.f);
		TestTrue(TEXT("board shown"), S->Board->IsBoardVisible());
		for (AActor* Actor : S->Spawned)
		{
			if (IsValid(Actor))
			{
				Actor->Destroy();
			}
		}
	});
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS && WITH_EDITOR

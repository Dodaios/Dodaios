#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS && WITH_EDITOR

#include "Abilities/VerseArcStormComponent.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/PointLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Misc/App.h"
#include "Misc/Paths.h"
#include "ShaderCompiler.h"
#include "UnrealClient.h"

// Verse.Visual.Abilities.ArcStorm: Arc Storm in a dark hangar bay from three cameras (side, behind
// the caster, the caster's eye). Runs only in a rendered `-game` process of the editor binary
// (scripts/unreal/screenshot.py --suite Verse.Visual.Abilities). Shots land in
// Saved/Harness/proof/S7/visual/ (never committed); the palette check reads them (Z-08).

namespace VerseAbilitiesVisual
{
	const FVector Base(0.0, -30000.0, 0.0);
	const TCHAR* CubePath = TEXT("/Engine/BasicShapes/Cube.Cube");
	const TCHAR* CylinderPath = TEXT("/Engine/BasicShapes/Cylinder.Cylinder");

	struct FState
	{
		UWorld* World = nullptr;
		ACameraActor* Camera = nullptr;
		APawn* Caster = nullptr;
		UVerseArcStormComponent* Arc = nullptr;
		TArray<AActor*> Spawned;
		FString Dir;
		int32 Shots = 0;
	};
	using FStateRef = TSharedRef<FState>;

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

	AStaticMeshActor* Shape(FState& S, const TCHAR* Mesh, const FVector& Centre, const FVector& Size)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		AStaticMeshActor* Actor = S.World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), FTransform(Base + Centre), Params);
		UStaticMeshComponent* Component = Actor->GetStaticMeshComponent();
		Component->SetMobility(EComponentMobility::Movable);
		Component->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, Mesh));
		Component->SetWorldScale3D(Size / 100.0);
		Component->SetCollisionProfileName(TEXT("BlockAll"));
		S.Spawned.Add(Actor);
		return Actor;
	}

	void Look(FState& S, const FVector& From, const FVector& At, float Fov = 60.f)
	{
		S.Camera->SetActorLocationAndRotation(Base + From, (At - From).Rotation());
		S.Camera->GetCameraComponent()->SetFieldOfView(Fov);
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
		// Floor, a back wall 8 m ahead, a side wall; a stand-in body (the Sovereign mesh arrives with WP13).
		Shape(S, CubePath, FVector(0.0, 0.0, -10.0), FVector(4000.0, 4000.0, 20.0));
		Shape(S, CubePath, FVector(820.0, 0.0, 300.0), FVector(20.0, 4000.0, 600.0));
		Shape(S, CubePath, FVector(300.0, 420.0, 300.0), FVector(1200.0, 20.0, 600.0));
		Shape(S, CylinderPath, FVector(0.0, 0.0, 85.0), FVector(45.0, 45.0, 170.0));
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		APointLight* Lamp = S.World->SpawnActor<APointLight>(APointLight::StaticClass(), FTransform(Base + FVector(-200.0, -300.0, 450.0)), Params);
		Lamp->PointLightComponent->SetMobility(EComponentMobility::Movable);
		Lamp->PointLightComponent->SetIntensity(1500.f);
		Lamp->PointLightComponent->SetAttenuationRadius(2000.f);
		Lamp->PointLightComponent->SetLightColor(FLinearColor(1.f, 0.85f, 0.65f));
		S.Spawned.Add(Lamp);
		S.Caster = S.World->SpawnActor<APawn>(APawn::StaticClass(), FTransform(Base + FVector(0.0, 0.0, 90.0)), Params);
		USceneComponent* Root = NewObject<USceneComponent>(S.Caster, TEXT("Root"));
		Root->SetMobility(EComponentMobility::Movable);
		S.Caster->SetRootComponent(Root);
		Root->RegisterComponent();
		S.Caster->SetActorLocation(Base + FVector(0.0, 0.0, 90.0));
		S.Spawned.Add(S.Caster);
		S.Arc = NewObject<UVerseArcStormComponent>(S.Caster, TEXT("ArcStorm"));
		S.Arc->SetupAttachment(Root);
		S.Arc->RegisterComponent();
		S.Arc->SetAimMode(EVerseArcAim::Facing);
		S.Arc->SetHandsOverride({Base + FVector(30.0, -32.0, 135.0), Base + FVector(30.0, 32.0, 135.0)});
		S.Camera = S.World->SpawnActor<ACameraActor>(ACameraActor::StaticClass(), FTransform(Base), Params);
		UCameraComponent* Cam = S.Camera->GetCameraComponent();
		Cam->PostProcessSettings.bOverride_AutoExposureMethod = true;
		Cam->PostProcessSettings.AutoExposureMethod = AEM_Manual;
		Cam->PostProcessSettings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
		Cam->PostProcessSettings.AutoExposureApplyPhysicalCameraExposure = 0;
		Cam->PostProcessSettings.bOverride_AutoExposureBias = true;
		Cam->PostProcessSettings.AutoExposureBias = 0.f;
		Cam->PostProcessBlendWeight = 1.f;
		S.Spawned.Add(S.Camera);
		S.Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/S7/visual"));
		IFileManager::Get().MakeDirectory(*S.Dir, true);
	}

	void Shoot(FState& S, const TCHAR* Name)
	{
		FScreenshotRequest::RequestScreenshot(FPaths::Combine(S.Dir, FString::Printf(TEXT("%s.png"), Name)), false, false);
		++S.Shots;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAbilitiesVisualArcStorm, "Verse.Visual.Abilities.ArcStorm",
	EAutomationTestFlags::ClientContext | EAutomationTestFlags::EngineFilter)
bool FVerseAbilitiesVisualArcStorm::RunTest(const FString&)
{
	using namespace VerseAbilitiesVisual;
	if (!FApp::CanEverRender())
	{
		AddInfo(TEXT("no RHI: the Arc Storm shots need a rendered -game run (screenshot.py)"));
		return true;
	}
	FStateRef S = MakeShared<FState>();
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
	Do([S]() { Look(*S, FVector(250.0, -560.0, 190.0), FVector(330.0, 0.0, 110.0)); S->Arc->SetHeld(true); });
	Wait(40);
	Do([]() { if (GShaderCompilingManager) { GShaderCompilingManager->FinishAllCompilation(); } });
	Wait(60);
	Do([S]() { Shoot(*S, TEXT("arc_side")); });
	Wait(13);
	Do([S]() { Shoot(*S, TEXT("arc_side_b")); });
	Wait(10);
	Do([S]() { Look(*S, FVector(-260.0, 90.0, 230.0), FVector(400.0, 0.0, 100.0)); });
	Wait(20);
	Do([S]() { Shoot(*S, TEXT("arc_behind")); });
	Wait(10);
	Do([S]() { Look(*S, FVector(10.0, 0.0, 165.0), FVector(500.0, 0.0, 120.0), 90.f); });
	Wait(20);
	Do([S]() { Shoot(*S, TEXT("arc_eye")); });
	Wait(10);
	Do([S]() { S->Arc->SetHeld(false); Look(*S, FVector(250.0, -560.0, 190.0), FVector(330.0, 0.0, 110.0)); });
	Wait(30);
	Do([S]() { Shoot(*S, TEXT("arc_released")); });
	Wait(10);
	Do([this, S]()
	{
		TestEqual(TEXT("five screenshots requested"), S->Shots, 5);
		TestTrue(TEXT("struck while held"), S->Arc->GetStrikeCount() > 20);
		TestEqual(TEXT("nothing drawn after release"), S->Arc->GetDrawnSegments(), 0);
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

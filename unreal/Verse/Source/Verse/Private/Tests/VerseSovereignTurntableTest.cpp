#include "Animation/SkeletalMeshActor.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/Engine.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"
#include "VerseDuelSubsystem.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.SovereignTurntable: SK_Sovereign in the running game renderer (Lumen, virtual
// shadow maps), framed like the three.js reference render (`art/verse/characters/sovereign`,
// turntable): 30 degree field of view, 4.2 m away, eye 1.15 m, aimed at 0.93 m, from the front,
// 45 degrees to its left, its left side and its back. A grey dome behind it, a warm key from front
// right, a cool rim from behind left and a soft fill. Shots land in
// Saved/Harness/proof/S7/game_turntable/. `-VerseSovEV=<bias>` sets the exposure bias.

namespace VerseSovereignTurntableTest
{
	const TCHAR* MeshPath = TEXT("/Game/Verse/Characters/Sovereign/SK_Sovereign.SK_Sovereign");
	const TCHAR* SpherePath = TEXT("/Engine/BasicShapes/Sphere.Sphere");
	const TCHAR* CylinderPath = TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
	const TCHAR* EmissivePath = TEXT("/Game/Verse/Materials/Master/M_Verse_Emissive.M_Verse_Emissive");
	const TCHAR* SurfacePath = TEXT("/Game/Verse/Materials/Master/M_Verse_Surface.M_Verse_Surface");
	/** Open floor of the hangar hall, far from the deck's own lights. */
	const FVector Spot(5000.0, 2400.0, 0.0);
	const int32 Yaws[] = {0, 45, 90, 180};

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

	bool ShadersDone()
	{
		return GShaderCompilingManager == nullptr || GShaderCompilingManager->GetNumRemainingJobs() == 0;
	}

	FRotator LightFrom(const FVector& Towards)
	{
		return (-Towards).Rotation();
	}

	struct FState
	{
		int32 Shot = 0;
		int32 Phase = 0;
		double PhaseS = 0.0;
		FString OutDir;
		TWeakObjectPtr<ACameraActor> Camera;
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualSovereignTurntableTest, "Verse.Visual.SovereignTurntable", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualSovereignTurntableTest::RunTest(const FString&)
{
	using namespace VerseSovereignTurntableTest;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.SovereignTurntable needs a GPU (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> State = MakeShared<FState>();
	State->OutDir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/S7/game_turntable")));
	IFileManager::Get().MakeDirectory(*State->OutDir, true);

	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
		{
			UWorld* World = GameWorld();
			APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
			if (!PC || !World->HasBegunPlay() || !UVerseDuelSubsystem::Get(World) || !ShadersDone())
			{
				return false;
			}
			USkeletalMesh* Mesh = LoadObject<USkeletalMesh>(nullptr, MeshPath);
			if (!TestNotNull(TEXT("SK_Sovereign"), Mesh))
			{
				return true;
			}
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			// The mesh faces +Y in its own space (coordinates.md 3.3); the cameras go round it.
			ASkeletalMeshActor* Body = World->SpawnActor<ASkeletalMeshActor>(Spot, FRotator::ZeroRotator, Params);
			Body->GetSkeletalMeshComponent()->SetSkeletalMeshAsset(Mesh);
			Body->GetSkeletalMeshComponent()->SetMobility(EComponentMobility::Movable);

			auto Shape = [World, &Params](const TCHAR* Path, const FVector& At, const FVector& Scale, UMaterialInterface* Material, bool bShadow)
			{
				AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(At, FRotator::ZeroRotator, Params);
				UStaticMeshComponent* C = Actor->GetStaticMeshComponent();
				C->SetMobility(EComponentMobility::Movable);
				C->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, Path));
				C->SetMaterial(0, Material);
				C->SetCastShadow(bShadow);
				Actor->SetActorScale3D(Scale);
				return Actor;
			};
			UMaterialInstanceDynamic* Dome = UMaterialInstanceDynamic::Create(LoadObject<UMaterialInterface>(nullptr, EmissivePath), World);
			Dome->SetVectorParameterValue(TEXT("EmissiveColor"), FLinearColor(0.35f, 0.35f, 0.35f));
			Dome->SetScalarParameterValue(TEXT("EmissiveNits"), 1.f);
			Shape(SpherePath, Spot + FVector(0.0, 0.0, 100.0), FVector(-12.0), Dome, false);
			UMaterialInstanceDynamic* Floor = UMaterialInstanceDynamic::Create(LoadObject<UMaterialInterface>(nullptr, SurfacePath), World);
			Floor->SetVectorParameterValue(TEXT("BaseTint"), FLinearColor(0.045f, 0.045f, 0.045f));
			Shape(CylinderPath, Spot + FVector(0.0, 0.0, 0.5), FVector(2.8, 2.8, 0.01), Floor, true);

			// The reference's lights in Unreal axes: three.js +X (the figure's left) = +X, +Y up = +Z,
			// +Z (toward the front camera) = +Y.
			auto Light = [World, &Params](const FVector& Towards, float Lux, const FLinearColor& Colour, bool bShadow)
			{
				ADirectionalLight* L = World->SpawnActor<ADirectionalLight>(Spot + FVector(0.0, 0.0, 300.0), LightFrom(Towards), Params);
				UDirectionalLightComponent* C = CastChecked<UDirectionalLightComponent>(L->GetLightComponent());
				C->SetMobility(EComponentMobility::Movable);
				C->SetIntensity(Lux);
				C->SetLightColor(Colour);
				C->SetCastShadows(bShadow);
				C->SetForwardShadingPriority(0);
			};
			Light(FVector(2.0, 3.0, 3.5), 4.f, FLinearColor(1.f, 0.92f, 0.82f), true);
			Light(FVector(-2.5, -3.0, 2.5), 2.5f, FLinearColor(0.85f, 0.9f, 1.f), false);
			for (const FVector& Fill : {FVector(4.0, 0.0, 1.0), FVector(-4.0, 0.0, 1.0), FVector(0.0, 4.0, 1.0), FVector(0.0, -4.0, 1.0), FVector(0.0, 0.0, -1.0)})
			{
				Light(Fill, 0.9f, FLinearColor::White, false);
			}

			ACameraActor* Camera = World->SpawnActor<ACameraActor>(Spot, FRotator::ZeroRotator, Params);
			UCameraComponent* C = Camera->GetCameraComponent();
			// The reference's 30 degrees are vertical; Unreal's field of view is horizontal (16:9 shots).
			C->SetFieldOfView(FMath::RadiansToDegrees(2.f * FMath::Atan(FMath::Tan(FMath::DegreesToRadians(15.f)) * 16.f / 9.f)));
			C->SetConstraintAspectRatio(false);
			float Bias = 1.f;
			FParse::Value(FCommandLine::Get(), TEXT("VerseSovEV="), Bias);
			C->PostProcessSettings.bOverride_AutoExposureMethod = true;
			C->PostProcessSettings.AutoExposureMethod = AEM_Manual;
			C->PostProcessSettings.bOverride_AutoExposureBias = true;
			C->PostProcessSettings.AutoExposureBias = Bias;
			C->PostProcessSettings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
			C->PostProcessSettings.AutoExposureApplyPhysicalCameraExposure = false;
			C->PostProcessBlendWeight = 1.f;
			State->Camera = Camera;
			PC->SetViewTarget(Camera);
			State->PhaseS = World->GetTimeSeconds();
			return true;
		}));

	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
		{
			UWorld* World = GameWorld();
			ACameraActor* Camera = State->Camera.Get();
			APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
			if (!World || !Camera || !PC || State->Shot >= int32(UE_ARRAY_COUNT(Yaws)))
			{
				return true;
			}
			const double Now = World->GetTimeSeconds();
			const double Yaw = FMath::DegreesToRadians(double(Yaws[State->Shot]));
			// Yaw 0 = in front of the Sovereign (its front is +Y); positive turns round to its left.
			const FVector Eye = Spot + FVector(420.0 * FMath::Sin(Yaw), 420.0 * FMath::Cos(Yaw), 115.0);
			Camera->SetActorLocationAndRotation(Eye, (Spot + FVector(0.0, 0.0, 93.0) - Eye).Rotation());
			PC->SetViewTarget(Camera);
			switch (State->Phase)
			{
			case 0:
				State->PhaseS = Now;
				State->Phase = 1;
				break;
			case 1:
				// Lumen, the virtual shadow maps and the eye adaptation settle after a cut.
				if (Now - State->PhaseS > 4.0 && ShadersDone())
				{
					FScreenshotRequest::RequestScreenshot(FPaths::Combine(State->OutDir, FString::Printf(TEXT("game_yaw%d.png"), Yaws[State->Shot])), false, false);
					State->PhaseS = Now;
					State->Phase = 2;
				}
				break;
			default:
				if (Now - State->PhaseS > 0.5)
				{
					State->Phase = 0;
					++State->Shot;
				}
				break;
			}
			return false;
		}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(0.5));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

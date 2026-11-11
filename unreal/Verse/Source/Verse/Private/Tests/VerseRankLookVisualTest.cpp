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
#include "Ranks/VerseRankLook.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"
#include "VerseDuelSubsystem.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.RankLook: four officers (SK_Commander_M, the three.js SK_Officer_M) in a row, one per
// rank tier, dressed by VerseRanks::ApplyLevel the way actors/look.ts dresses them: senior
// technician (deck), captain (line), commodore (command), fleet admiral (flag). Lit like
// Verse.Visual.SovereignTurntable; the three.js reference uses the same rig. Shots land in
// Saved/Harness/proof/S7/rank_look/ (`lineup` full figures, `plates` the chests).

namespace VerseRankLookVisualTest
{
	const TCHAR* MeshPath = TEXT("/Game/Verse/Characters/Commander/SK_Commander_M.SK_Commander_M");
	const TCHAR* SpherePath = TEXT("/Engine/BasicShapes/Sphere.Sphere");
	const TCHAR* CylinderPath = TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
	const TCHAR* EmissivePath = TEXT("/Game/Verse/Materials/Master/M_Verse_Emissive.M_Verse_Emissive");
	const TCHAR* SurfacePath = TEXT("/Game/Verse/Materials/Master/M_Verse_Surface.M_Verse_Surface");
	const FVector Spot(5000.0, 2400.0, 0.0);
	const int32 Levels[] = { 8, 25, 33, 50 };
	const double SpacingCm = 70.0;

	struct FShot
	{
		const TCHAR* Name;
		double DistanceCm;
		double EyeCm;
		double AimCm;
		double VerticalFovDeg;
	};
	const FShot Shots[] = { { TEXT("lineup"), 620.0, 115.0, 93.0, 30.0 }, { TEXT("plates"), 300.0, 140.0, 138.0, 14.0 } };

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

	struct FState
	{
		int32 Shot = 0;
		int32 Phase = 0;
		double PhaseS = 0.0;
		FString OutDir;
		TWeakObjectPtr<ACameraActor> Camera;
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualRankLookTest, "Verse.Visual.RankLook", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualRankLookTest::RunTest(const FString&)
{
	using namespace VerseRankLookVisualTest;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.RankLook needs a GPU (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> State = MakeShared<FState>();
	State->OutDir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/S7/rank_look")));
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
			if (!TestNotNull(TEXT("SK_Commander_M"), Mesh))
			{
				return true;
			}
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			for (int32 I = 0; I < int32(UE_ARRAY_COUNT(Levels)); ++I)
			{
				// Left to right as the camera (at +Y, facing the bodies) sees them: its right is +X.
				const FVector At = Spot + FVector((I - 1.5) * SpacingCm, 0.0, 0.0);
				ASkeletalMeshActor* Body = World->SpawnActor<ASkeletalMeshActor>(At, FRotator::ZeroRotator, Params);
				USkeletalMeshComponent* C = Body->GetSkeletalMeshComponent();
				C->SetSkeletalMeshAsset(Mesh);
				C->SetMobility(EComponentMobility::Movable);
				TestTrue(FString::Printf(TEXT("level %d dressed"), Levels[I]), VerseRanks::ApplyLevel(C, Levels[I]) >= 9);
			}

			auto Shape = [World, &Params](const TCHAR* Path, const FVector& At, const FVector& Scale, UMaterialInterface* Material, bool bShadow)
			{
				AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(At, FRotator::ZeroRotator, Params);
				UStaticMeshComponent* C = Actor->GetStaticMeshComponent();
				C->SetMobility(EComponentMobility::Movable);
				C->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, Path));
				C->SetMaterial(0, Material);
				C->SetCastShadow(bShadow);
				Actor->SetActorScale3D(Scale);
			};
			UMaterialInstanceDynamic* Dome = UMaterialInstanceDynamic::Create(LoadObject<UMaterialInterface>(nullptr, EmissivePath), World);
			Dome->SetVectorParameterValue(TEXT("EmissiveColor"), FLinearColor(0.35f, 0.35f, 0.35f));
			Dome->SetScalarParameterValue(TEXT("EmissiveNits"), 1.f);
			Shape(SpherePath, Spot + FVector(0.0, 0.0, 100.0), FVector(-40.0), Dome, false);
			UMaterialInstanceDynamic* Floor = UMaterialInstanceDynamic::Create(LoadObject<UMaterialInterface>(nullptr, SurfacePath), World);
			Floor->SetVectorParameterValue(TEXT("BaseTint"), FLinearColor(0.045f, 0.045f, 0.045f));
			Shape(CylinderPath, Spot + FVector(0.0, 0.0, 0.5), FVector(4.0, 4.0, 0.01), Floor, true);

			auto Light = [World, &Params](const FVector& Towards, float Lux, const FLinearColor& Colour, bool bShadow)
			{
				ADirectionalLight* L = World->SpawnActor<ADirectionalLight>(Spot + FVector(0.0, 0.0, 300.0), (-Towards).Rotation(), Params);
				UDirectionalLightComponent* C = CastChecked<UDirectionalLightComponent>(L->GetLightComponent());
				C->SetMobility(EComponentMobility::Movable);
				C->SetIntensity(Lux);
				C->SetLightColor(Colour);
				C->SetCastShadows(bShadow);
				C->SetForwardShadingPriority(0);
			};
			Light(FVector(2.0, 3.0, 3.5), 4.f, FLinearColor(1.f, 0.92f, 0.82f), true);
			Light(FVector(-2.5, -3.0, 2.5), 2.5f, FLinearColor(0.85f, 0.9f, 1.f), false);
			for (const FVector& Fill : { FVector(4.0, 0.0, 1.0), FVector(-4.0, 0.0, 1.0), FVector(0.0, 4.0, 1.0), FVector(0.0, -4.0, 1.0), FVector(0.0, 0.0, -1.0) })
			{
				Light(Fill, 0.9f, FLinearColor::White, false);
			}

			ACameraActor* Camera = World->SpawnActor<ACameraActor>(Spot, FRotator::ZeroRotator, Params);
			UCameraComponent* C = Camera->GetCameraComponent();
			C->SetConstraintAspectRatio(false);
			// The light rig of the turntables is about 2.3 stops brighter than the three.js reference
			// rig (measured on the drones' white shells); -VerseRankEV= overrides.
			float Bias = -1.3f;
			FParse::Value(FCommandLine::Get(), TEXT("VerseRankEV="), Bias);
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
			if (!World || !Camera || !PC || State->Shot >= int32(UE_ARRAY_COUNT(Shots)))
			{
				return true;
			}
			const FShot& Shot = Shots[State->Shot];
			const FVector Eye = Spot + FVector(0.0, Shot.DistanceCm, Shot.EyeCm);
			Camera->SetActorLocationAndRotation(Eye, (Spot + FVector(0.0, 0.0, Shot.AimCm) - Eye).Rotation());
			Camera->GetCameraComponent()->SetFieldOfView(FMath::RadiansToDegrees(2.f * FMath::Atan(FMath::Tan(FMath::DegreesToRadians(float(Shot.VerticalFovDeg) * 0.5f)) * 16.f / 9.f)));
			PC->SetViewTarget(Camera);
			const double Now = World->GetTimeSeconds();
			switch (State->Phase)
			{
			case 0:
				State->PhaseS = Now;
				State->Phase = 1;
				break;
			case 1:
				if (Now - State->PhaseS > 4.0 && ShadersDone())
				{
					FScreenshotRequest::RequestScreenshot(FPaths::Combine(State->OutDir, FString::Printf(TEXT("ue_%s.png"), Shot.Name)), false, false);
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

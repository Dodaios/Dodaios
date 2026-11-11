#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Engine/Engine.h"
#include "Engine/PostProcessVolume.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "Misc/Paths.h"
#include "ShaderCompiler.h"
#include "Space/VerseSpaceView.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.SpaceView: the space view in the running game renderer, framed like the three.js
// reference (`SpaceView` of engine/realtime/spaceView.ts at time 0, windows looking along
// three.js -Z, a 50 degree vertical field of view): straight out, 30 degrees down, and 20 degrees
// right and up towards the sun. Every other actor but the post-process volumes is hidden, so the
// game's tonemapper applies. First `calib`: the dome draws a ramp of known scene values
// (M_Verse_Space `Calibrate`), which `kit/props/space/space_calibrate.py` turns into the inverse
// of that tonemapper. Shots land in Saved/Harness/proof/S7/space/ue_<view>.png.

namespace VerseSpaceViewVisualTest
{
	struct FShot
	{
		const TCHAR* Name;
		double YawDeg;
		double PitchDeg;
	};
	const FShot Shots[] = { { TEXT("calib"), 0.0, 0.0 }, { TEXT("p0"), 0.0, 0.0 }, { TEXT("pm30"), 0.0, -30.0 }, { TEXT("y20p20"), 20.0, 20.0 } };
	/** three.js -Z in Unreal axes (Y and Z swap). */
	const FVector Outward(0.0, -1.0, 0.0);

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
		TWeakObjectPtr<AVerseSpaceView> Space;
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualSpaceViewTest, "Verse.Visual.SpaceView", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualSpaceViewTest::RunTest(const FString&)
{
	using namespace VerseSpaceViewVisualTest;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.SpaceView needs a GPU (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> State = MakeShared<FState>();
	State->OutDir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/S7/space")));
	IFileManager::Get().MakeDirectory(*State->OutDir, true);

	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, State]() -> bool
		{
			UWorld* World = GameWorld();
			APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
			if (!PC || !World->HasBegunPlay() || !ShadersDone())
			{
				return false;
			}
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			AVerseSpaceView* Space = nullptr;
			for (TActorIterator<AVerseSpaceView> It(World); It; ++It)
			{
				Space = *It;
			}
			if (Space == nullptr)
			{
				Space = World->SpawnActor<AVerseSpaceView>(Params);
			}
			if (!TestNotNull(TEXT("space view"), Space))
			{
				return true;
			}
			TestEqual(TEXT("dome, both instances and the collection load"), Space->LoadBackdrop(), 4);
			Space->SetOutward(Outward);
			Space->Look.OrbitSpeed = 0.0;
			Space->ElapsedS = 0.0;
			ACameraActor* Camera = World->SpawnActor<ACameraActor>(FVector(0.0, 0.0, 100000.0), FRotator::ZeroRotator, Params);
			UCameraComponent* C = Camera->GetCameraComponent();
			// The reference's 50 degrees are vertical; Unreal's field of view is horizontal (16:9).
			C->SetFieldOfView(FMath::RadiansToDegrees(2.f * FMath::Atan(FMath::Tan(FMath::DegreesToRadians(25.f)) * 16.f / 9.f)));
			C->SetConstraintAspectRatio(false);
			for (TActorIterator<AActor> It(World); It; ++It)
			{
				if (*It != Space && *It != Camera && !It->IsA<APlayerController>() && !It->IsA<APostProcessVolume>())
				{
					It->SetActorHiddenInGame(true);
				}
			}
			if (UMaterialInterface* View = LoadObject<UMaterialInterface>(nullptr, AVerseSpaceView::EarthMaterialPath))
			{
				UMaterialInstanceDynamic* Ramp = UMaterialInstanceDynamic::Create(View, Space);
				Ramp->SetScalarParameterValue(TEXT("Calibrate"), 1.f);
				Space->DomeOverride = Ramp;
			}
			State->Camera = Camera;
			State->Space = Space;
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
			// Facing the windows is yaw -90 (three.js -Z); turning right adds yaw.
			Camera->SetActorRotation(FRotator(Shot.PitchDeg, -90.0 + Shot.YawDeg, 0.0));
			PC->SetViewTarget(Camera);
			if (AVerseSpaceView* Space = State->Space.Get())
			{
				Space->ElapsedS = 0.0;
				if (State->Shot > 0)
				{
					Space->DomeOverride = nullptr;
				}
			}
			const double Now = World->GetTimeSeconds();
			switch (State->Phase)
			{
			case 0:
				State->PhaseS = Now;
				State->Phase = 1;
				break;
			case 1:
				if (Now - State->PhaseS > 3.0 && ShadersDone())
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

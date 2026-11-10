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
#include "Projectiles/VersePlaceholderArt.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"
#include "UnrealClient.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.Combat.Bolts (WP02.11 evidence, rendered lane only: scripts/unreal/screenshot.py):
// a first-person view of gunfire with real rounds: the viewer's own tracer rounds and casings, the
// opponent's tracers, muzzle flashes and smoke, impacts with sparks and bullet holes on the floor,
// frozen mid flight. Synthetic scene (dark floor, one work light); the PNG goes to the proof folder.

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

		UStaticMesh* Plane = VersePlaceholderArt::Mesh(VersePlaceholderArt::EShape::Plane);
		UMaterialInterface* Base = VersePlaceholderArt::Material();
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
			Light->GetLightComponent()->SetIntensity(6.f);
			S->Spawned.Add(Light);
		}
		if (ACameraActor* Camera = World->SpawnActor<ACameraActor>(FVector(0, 0, 160), FRotator(-4, 0, 0), P))
		{
			UCameraComponent* Cam = Camera->GetCameraComponent();
			Cam->SetFieldOfView(90.f);
			// Fixed exposure, so the frame does not depend on eye adaptation timing.
			Cam->PostProcessSettings.bOverride_AutoExposureMinBrightness = true;
			Cam->PostProcessSettings.bOverride_AutoExposureMaxBrightness = true;
			Cam->PostProcessSettings.AutoExposureMinBrightness = 1.f;
			Cam->PostProcessSettings.AutoExposureMaxBrightness = 1.f;
			Cam->PostProcessBlendWeight = 1.f;
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
		// The last rounds of a magazine: every round below is a tracer, so the streaks show.
		Present->RoundsLeftOverride = [](int32, FName) { return 0; };
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
			E.Direction = FRotator(1.f + 0.8f * I, -12.f + 4.5f * I, 0).Vector();
			Clock = 100.0 - 0.008 * I;
			Hub->OnFire.Broadcast(E);
		}
		// The opponent's bolts coming in from the far side.
		for (int32 I = 0; I < 4; ++I)
		{
			FVerseFireEvent E;
			E.ShooterId = 2;
			E.WeaponId = TEXT("graveline");
			E.ShotCounter = uint16(I + 1);
			// Crossing the view from the left at 12-18 m, aimed past the viewer.
			E.Origin = FVector(1500 + 150 * I, -2200, 140 + 25 * I);
			E.Direction = (FVector(900 + 100 * I, 1200, 170) - FVector(E.Origin)).GetSafeNormal();
			Clock = 100.0 - 0.02 * I;
			Hub->OnFire.Broadcast(E);
		}
		// Rounds of the opponent's that already landed on the floor ahead: sparks and holes.
		for (int32 I = 0; I < 3; ++I)
		{
			FVerseHitEvent Hit;
			Hit.InstigatorId = 2;
			Hit.VictimId = -1;
			Hit.ShotCounter = uint16(40 + I);
			Hit.ImpactWorld = FVector(700 + 120 * I, -90 + 110 * I, 0);
			Hit.Direction = FVector(0.3, 0.5, -0.8).GetSafeNormal();
			Clock = 100.02;
			Hub->OnHit.Broadcast(Hit);
		}
		// Let the casings fly a few frames, then freeze mid-way so the shot holds still while shaders
		// and streaming settle.
		for (double T = 100.0; T <= 100.0301; T += 1.0 / 120.0)
		{
			Present->ClockOverride = [T]() { return T; };
			Present->Advance(T);
		}
		Present->ClockOverride = []() { return 100.03; };
		Present->Advance(100.03);
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
		TestTrue(TEXT("own rounds in flight"), P && P->NumOwn() == 6);
		TestTrue(TEXT("opponent rounds in flight"), P && P->NumFoe() == 4);
		TestTrue(TEXT("all tracer rounds (end of magazine)"), P && P->NumTracers() == 10);
		TestTrue(TEXT("casings in the air"), P && P->GetCasings().Num() == 10);
		return true;
	}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(2.0f));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([]()
	{
		// An uncooked run compiles the placeholder material on first use; until then it draws the
		// default material. Wait for it, then give the renderer a moment.
		if (GShaderCompilingManager)
		{
			GShaderCompilingManager->FinishAllCompilation();
		}
		return true;
	}));
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.0f));
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

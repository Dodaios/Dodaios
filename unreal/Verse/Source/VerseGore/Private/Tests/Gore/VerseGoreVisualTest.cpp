#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/PointLightComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/GameViewportClient.h"
#include "Engine/PointLight.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "Misc/App.h"
#include "Misc/FileHelper.h"
#include "Tests/Gore/VerseGoreTestWorld.h"
#include "UnrealClient.h"

// Verse.Visual.Gore.Pairs: Full vs Reduced screenshot pairs of a body hit, a wall spatter, a pool
// and a finisher (WP05 evidence), and the GPU cost of gore_storm at 1440p (A5.4). Runs only in a
// rendered `-game` process (scripts/unreal/screenshot.py --suite Verse.Visual.Gore).

namespace VerseGoreVisual
{
	using namespace VerseGoreTest;

	/** Scene far from the default pawn and the entry map's origin. */
	const FVector Base(0.0, 20000.0, 0.0);

	struct FState
	{
		UWorld* World = nullptr;
		UVerseGoreSubsystem* Gore = nullptr;
		UVerseEventHub* Hub = nullptr;
		ACameraActor* Camera = nullptr;
		TMap<int32, TWeakObjectPtr<USkeletalMeshComponent>> Bodies;
		TArray<AActor*> Spawned;
		FString Dir;
		int32 Frames = 0;
		TArray<double> GpuMs;
		double BaselineMs = 0.0;
		double LoadedMs = 0.0;
		double StormClock = 0.0;
		uint16 Shot = 1;
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

	template <typename T>
	T* Spawn(FState& S, const FTransform& Transform)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		T* Actor = S.World->SpawnActor<T>(T::StaticClass(), Transform, Params);
		S.Spawned.Add(Actor);
		return Actor;
	}

	void Box(FState& S, const FVector& Centre, const FVector& Size)
	{
		AStaticMeshActor* Actor = Spawn<AStaticMeshActor>(S, FTransform(Base + Centre));
		UStaticMeshComponent* Component = Actor->GetStaticMeshComponent();
		Component->SetMobility(EComponentMobility::Movable);
		Component->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, CubePath));
		Component->SetWorldScale3D(Size / 100.0);
		Component->SetCollisionProfileName(TEXT("BlockAll"));
	}

	USkeletalMeshComponent* Body(FState& S, int32 Id, const FVector& Feet, float Yaw)
	{
		APawn* Pawn = Spawn<APawn>(S, FTransform(FRotator(0.f, Yaw, 0.f), Base + Feet));
		USkeletalMeshComponent* Mesh = NewObject<USkeletalMeshComponent>(Pawn, TEXT("Body"));
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->SetSkeletalMeshAsset(LoadObject<USkeletalMesh>(nullptr, TestHumanPath));
		Pawn->SetRootComponent(Mesh);
		Mesh->RegisterComponent();
		Mesh->SetWorldLocationAndRotation(Base + Feet, FRotator(0.f, Yaw, 0.f));
		if (UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, WoundMaterialPath))
		{
			for (int32 Slot = 0; Slot < FMath::Max(1, Mesh->GetNumMaterials()); ++Slot)
			{
				Mesh->SetMaterial(Slot, Material);
			}
		}
		S.Bodies.Add(Id, Mesh);
		return Mesh;
	}

	void Look(FState& S, const FVector& From, const FVector& At)
	{
		S.Camera->SetActorLocationAndRotation(Base + From, (At - From).Rotation());
		if (APlayerController* Controller = S.World->GetFirstPlayerController())
		{
			Controller->SetViewTarget(S.Camera);
		}
	}

	void Setup(FState& S)
	{
		S.World = GameWorld();
		S.Gore = UVerseGoreSubsystem::Get(S.World);
		S.Hub = UVerseEventHub::Get(S.World);
		if (!S.Gore || !S.Hub)
		{
			return;
		}
		// Floor, back wall at x = 150, a side wall for the finisher.
		Box(S, FVector(0.0, 0.0, -10.0), FVector(3000.0, 3000.0, 20.0));
		Box(S, FVector(160.0, 0.0, 200.0), FVector(20.0, 3000.0, 400.0));
		ADirectionalLight* Sun = Spawn<ADirectionalLight>(S, FTransform(FRotator(-55.f, 35.f, 0.f), Base));
		Sun->GetComponent()->SetMobility(EComponentMobility::Movable);
		Sun->GetComponent()->SetIntensity(5.f);
		APointLight* Lamp = Spawn<APointLight>(S, FTransform(Base + FVector(-150.0, -120.0, 260.0)));
		Lamp->PointLightComponent->SetMobility(EComponentMobility::Movable);
		Lamp->PointLightComponent->SetIntensity(9000.f);
		Lamp->PointLightComponent->SetAttenuationRadius(1500.f);
		Lamp->PointLightComponent->SetLightColor(FLinearColor(1.f, 0.82f, 0.6f));
		S.Camera = Spawn<ACameraActor>(S, FTransform(Base));
		UCameraComponent* Cam = S.Camera->GetCameraComponent();
		Cam->SetFieldOfView(60.f);
		Cam->PostProcessSettings.bOverride_AutoExposureMethod = true;
		Cam->PostProcessSettings.AutoExposureMethod = AEM_Manual;
		Cam->PostProcessSettings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
		Cam->PostProcessSettings.AutoExposureApplyPhysicalCameraExposure = 0;
		Cam->PostProcessSettings.bOverride_AutoExposureBias = true;
		Cam->PostProcessSettings.AutoExposureBias = 0.5f;
		Cam->PostProcessBlendWeight = 1.f;
		Body(S, 2, FVector::ZeroVector, 180.f);
		S.Gore->SetVictimResolver([&Bodies = S.Bodies](int32 Id) -> USkeletalMeshComponent*
		{
			const TWeakObjectPtr<USkeletalMeshComponent>* Found = Bodies.Find(Id);
			return Found ? Found->Get() : nullptr;
		});
		S.Gore->SetGoreLevel(EVerseGoreLevel::Full);
		S.Gore->Purge();
		S.Dir = ProofDir(TEXT("visual"));
		IFileManager::Get().MakeDirectory(*S.Dir, true);
	}

	FVerseHitEvent HitOn(FState& S, EVerseHitZone Zone, float Damage, bool bKill = false)
	{
		FVerseHitEvent Hit = FVerseGoreSyntheticStream::MakeHit(Zone, Base, Base + FVector(-900.0, -60.0, 160.0), 1, 2, Damage, S.Shot, 0.f, bKill);
		++S.Shot;
		return Hit;
	}

	/** Raw GPU frame time of the last frame, ms ("stat unit" keeps it updated; no RHI link needed). */
	double GpuFrameMs()
	{
		const FStatUnitData* Data = GEngine->GameViewport ? GEngine->GameViewport->GetStatUnitData() : nullptr;
		return Data ? double(Data->RawGPUFrameTime[0]) : 0.0;
	}

	void Shoot(FState& S, const TCHAR* Name)
	{
		const FString Path = FPaths::Combine(S.Dir, FString::Printf(TEXT("%s_%s.png"), Name,
			S.Gore->GetGoreLevel() == EVerseGoreLevel::Full ? TEXT("full") : TEXT("reduced")));
		FScreenshotRequest::RequestScreenshot(Path, false, false);
		++S.Shots;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreVisualPairs, "Verse.Visual.Gore.Pairs",
	EAutomationTestFlags::ClientContext | EAutomationTestFlags::EngineFilter)
bool FVerseGoreVisualPairs::RunTest(const FString&)
{
	using namespace VerseGoreVisual;
	if (!FApp::CanEverRender())
	{
		AddInfo(TEXT("no RHI: visual gore pairs need a rendered -game run (screenshot.py)"));
		return true;
	}
	FStateRef S = MakeShared<FState>();
	Setup(*S);
	if (!TestNotNull(TEXT("gore in the game world"), S->Gore) || !S->Hub)
	{
		return false;
	}
	TestTrue(TEXT("gore active in a rendered process"), S->Gore->IsActive());

	auto Wait = [this](int32 Frames)
	{
		TSharedRef<int32> Count = MakeShared<int32>(0);
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([Count, Frames]() { return ++(*Count) >= Frames; }));
	};
	auto Do = [this](TFunction<void()> Step)
	{
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([Step]() { Step(); return true; }));
	};

	// Shaders and streaming settle first.
	Wait(90);
	for (const EVerseGoreLevel Level : {EVerseGoreLevel::Full, EVerseGoreLevel::Reduced})
	{
		Do([S, Level]() { S->Gore->Purge(); S->Gore->SetGoreLevel(Level); Look(*S, FVector(-260.0, -170.0, 150.0), FVector(0.0, 0.0, 120.0)); });
		Wait(10);
		// Body hit: droplets in the air.
		Do([S]() { S->Gore->HandleHit(HitOn(*S, EVerseHitZone::UpperTorso, 45.f)); S->Gore->HandleHit(HitOn(*S, EVerseHitZone::Head, 60.f)); });
		Wait(2);
		Do([S]() { Shoot(*S, TEXT("body_hit")); });
		Wait(6);
		// Wall spatter after the droplets settle.
		Do([S]()
		{
			for (int32 I = 0; I < 6; ++I)
			{
				S->Gore->HandleHit(HitOn(*S, I % 2 ? EVerseHitZone::Head : EVerseHitZone::UpperTorso, 55.f));
			}
			Look(*S, FVector(-180.0, 60.0, 150.0), FVector(150.0, 0.0, 150.0));
		});
		Wait(40);
		Do([S]() { Shoot(*S, TEXT("wall_spatter")); });
		Wait(6);
		// Pool after 4 s of growth.
		Do([S]()
		{
			FVerseDeathEvent Death;
			Death.VictimId = 2;
			S->Hub->OnDeath.Broadcast(Death);
			Look(*S, FVector(-220.0, -120.0, 230.0), FVector(0.0, 0.0, 0.0));
		});
		Wait(130);
		Do([S]() { Shoot(*S, TEXT("pool")); });
		Wait(6);
		// Finisher: shot just after Kill (Full) / inside the cut to black (Reduced).
		Do([S]()
		{
			S->Gore->Purge();
			FVerseGoreSyntheticParams Params;
			Params.Kind = EVerseGoreSyntheticKind::Finisher;
			Params.VictimId = 2;
			Params.VictimLocation = Base;
			S->Gore->PlaySynthetic(Params);
			Look(*S, FVector(-150.0, -200.0, 170.0), FVector(0.0, 0.0, 110.0));
		});
		Wait(57);
		Do([S]() { Shoot(*S, TEXT("finisher")); });
		Wait(30);
	}
	Do([this, S]()
	{
		TestEqual(TEXT("eight screenshots requested"), S->Shots, 8);
		TestFalse(TEXT("cut to black released after Recover"), S->Gore->GetCutToBlack().bActive);
		TestTrue(TEXT("Reduced finisher cut to black once"), S->Gore->GetCutToBlack().Count >= 1);
	});

	// GPU cost of gore_storm at 1440p: frame GPU time with gore at its caps minus without.
	Do([S]()
	{
		if (IConsoleVariable* VSync = IConsoleManager::Get().FindConsoleVariable(TEXT("r.VSync")))
		{
			VSync->Set(0);
		}
		GEngine->Exec(S->World, TEXT("r.SetRes 2560x1440w"));
		GEngine->Exec(S->World, TEXT("stat unit"));
		S->Gore->Purge();
		S->Gore->SetGoreLevel(EVerseGoreLevel::Full);
		Look(*S, FVector(-300.0, -40.0, 160.0), FVector(150.0, 0.0, 100.0));
		S->GpuMs.Reset();
	});
	Wait(60);
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([S]()
	{
		S->GpuMs.Add(GpuFrameMs());
		if (S->GpuMs.Num() < 150)
		{
			return false;
		}
		S->GpuMs.Sort();
		S->BaselineMs = S->GpuMs[S->GpuMs.Num() / 2];
		S->GpuMs.Reset();
		// Fill to the caps: 256 spatter decals in view, 16 pools, 16 wounds.
		for (int32 I = 0; I < 220; ++I)
		{
			S->Gore->HandleHit(HitOn(*S, EVerseHitZone(1 + I % 6), 55.f));
		}
		for (int32 Id = 10; Id < 26; ++Id)
		{
			Body(*S, Id, FVector(-60.0 - 25.0 * (Id - 10), -200.0 + 25.0 * (Id - 10), 0.0), 0.f);
			FVerseDeathEvent Death;
			Death.VictimId = Id;
			S->Hub->OnDeath.Broadcast(Death);
		}
		return true;
	}));
	Wait(30);
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([S]()
	{
		// Storm continues at 30 hits/s (one hit per frame at the 30 fps benchmark step).
		S->Gore->HandleHit(HitOn(*S, EVerseHitZone(1 + S->Shot % 6), 40.f));
		S->GpuMs.Add(GpuFrameMs());
		if (S->GpuMs.Num() < 300)
		{
			return false;
		}
		S->GpuMs.Sort();
		S->LoadedMs = S->GpuMs[S->GpuMs.Num() / 2];
		return true;
	}));
	Do([this, S]()
	{
		const double Delta = S->LoadedMs - S->BaselineMs;
		const FVerseGoreBudget& B = S->Gore->GetBudget();
		const FIntPoint Size = GEngine->GameViewport && GEngine->GameViewport->Viewport ? GEngine->GameViewport->Viewport->GetSizeXY() : FIntPoint::ZeroValue;
		const FString Json = FString::Printf(
			TEXT("{\n  \"schema\": \"verse.gore.gpu/1\",\n  \"resolution\": [%d, %d],\n  \"baseline_gpu_ms_median\": %.4f,\n")
			TEXT("  \"storm_gpu_ms_median\": %.4f,\n  \"gore_gpu_ms\": %.4f,\n  \"limit_gpu_ms\": 0.3,\n")
			TEXT("  \"live\": {\"spatter_decals\": %d, \"pools\": %d, \"droplets\": %d, \"max_wounds_on_one_character\": %d},\n")
			TEXT("  \"game_thread_hit_mean_ms\": %.5f\n}\n"),
			Size.X, Size.Y, S->BaselineMs, S->LoadedMs, Delta, B.SpatterDecals, B.Pools, B.Droplets, B.MaxWoundsOnOneCharacter, B.HitMeanMs);
		FFileHelper::SaveStringToFile(Json, *FPaths::Combine(ProofDir(TEXT("5.8")), TEXT("gpu_gore_storm_1440p.json")));
		S->Gore->WriteBudgetJson(FPaths::Combine(ProofDir(TEXT("5.8")), TEXT("budget_gore_storm_rendered.json")));
		AddInfo(FString::Printf(TEXT("gore_storm GPU %.3f ms (baseline %.3f, storm %.3f) at %dx%d"), Delta, S->BaselineMs, S->LoadedMs, Size.X, Size.Y));
		TestTrue(FString::Printf(TEXT("gore_storm GPU cost %.3f ms <= 0.3 ms at 1440p"), Delta), Delta <= 0.3);
		TestTrue(TEXT("measured at 1440p"), Size.Y >= 1440);
		TestTrue(TEXT("GPU frame timing available"), S->BaselineMs > 0.0);
		S->Gore->Purge();
		S->Gore->SetVictimResolver(nullptr);
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

#endif // WITH_DEV_AUTOMATION_TESTS

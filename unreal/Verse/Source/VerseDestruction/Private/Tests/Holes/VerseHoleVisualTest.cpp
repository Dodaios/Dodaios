#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "AssetCompilingManager.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/FileManager.h"
#include "Holes/VerseBoltHoleComponent.h"
#include "Holes/VerseHoleGlow.h"
#include "Holes/VerseHoleRenderComponent.h"
#include "ImageUtils.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Penetration/VersePenetrationSubsystem.h"
#include "Tests/Penetration/Fakes/VerseWP03Fakes.h"
#include "TextureResource.h"
#include "VerseCollision.h"

namespace
{
	constexpr EAutomationTestFlags WP03VisualFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;
	constexpr int32 ShotSize = 512;
	// Engine primitive (100 cm, box collision), not a sample content pack.
	const TCHAR* const BoxPath = TEXT("/Engine/BasicShapes/Cube.Cube");
	const TCHAR* const SurfacePath = TEXT("/Game/Verse/Test/WP03/M_WP03_HoleSurface.M_WP03_HoleSurface");

	struct FShot
	{
		TArray<FColor> Pixels;
		int32 Banned = 0;
		int32 Hot = 0;
		FColor Centre;
		FColor Wall;
	};

	FLinearColor Hsv(const FColor& Pixel)
	{
		return FLinearColor(Pixel.R / 255.f, Pixel.G / 255.f, Pixel.B / 255.f).LinearRGBToHSV();
	}

	/** The visible rim glow: brighter than any lit surface here, white or a warm hue (a fresh rim clips to near white). */
	bool IsHot(const FColor& Pixel)
	{
		const FLinearColor C = Hsv(Pixel);
		return C.B >= 0.92f && (C.G < 0.2f || C.R <= 60.f || C.R >= 340.f);
	}

	AActor* SpawnMesh(FVerseWP03World& W, UStaticMesh* Box, UMaterialInterface* Surface, const FVector& Location, const FVector& SizeCm,
		const FLinearColor& Tint, FName Profile, UStaticMeshComponent*& OutMesh)
	{
		FActorSpawnParameters Params;
		Params.ObjectFlags = RF_Transient;
		AActor* Actor = W.World()->SpawnActor<AActor>(AActor::StaticClass(), FTransform(Location), Params);
		// An unscaled root is the piece frame; the scaled mesh hangs under it.
		USceneComponent* Root = NewObject<USceneComponent>(Actor, TEXT("Frame"));
		Actor->SetRootComponent(Root);
		Root->RegisterComponent();
		UStaticMeshComponent* Mesh = NewObject<UStaticMeshComponent>(Actor, TEXT("Mesh"));
		Mesh->SetStaticMesh(Box);
		Mesh->SetupAttachment(Root);
		Mesh->SetRelativeScale3D(SizeCm / 100.0);
		Mesh->SetCollisionProfileName(Profile);
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Surface, Actor);
		Mid->SetVectorParameterValue(TEXT("Tint"), Tint);
		Mesh->SetMaterial(0, Mid);
		Mesh->RegisterComponent();
		Actor->SetActorLocation(Location);
		OutMesh = Mesh;
		return Actor;
	}

	void SavePng(FAutomationTestBase& Test, const FString& Name, const TArray<FColor>& Pixels)
	{
		const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness"), TEXT("proof"), TEXT("WP03"), TEXT("holes"));
		IFileManager::Get().MakeDirectory(*Dir, true);
		TArray64<uint8> Png;
		FImageUtils::PNGCompressImageArray(ShotSize, ShotSize, TArrayView64<const FColor>(Pixels.GetData(), Pixels.Num()), Png);
		const FString Path = FPaths::ConvertRelativePathToFull(FPaths::Combine(Dir, Name + TEXT(".png")));
		if (FFileHelper::SaveArrayToFile(Png, *Path))
		{
			Test.AddInfo(FString::Printf(TEXT("shot %s"), *Path));
		}
	}
}

// A3.6 (WP03.6) on the GPU: a bolt hole in a container wall, rendered through the real hole
// mask and rim decal at 0, 1, 2.5 and 4 s after the impact. 0 banned pixels by the rendered-
// pixel rule of art-pipeline.md 8.3 in every frame; the rim glows at impact and is out at 4 s;
// the hole is open from both sides (the backdrop shows through, and TestSight agrees).
// Run: python scripts/unreal/screenshot.py --suite Verse.Visual.Holes
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHoleVisualTest, "Verse.Visual.Holes", WP03VisualFlags)

bool FVerseHoleVisualTest::RunTest(const FString& Parameters)
{
	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	if (!UVerseHoleRenderComponent::CanRender(W.World()))
	{
		AddInfo(TEXT("needs a GPU: python scripts/unreal/screenshot.py --suite Verse.Visual.Holes"));
		return true;
	}
	UStaticMesh* Box = LoadObject<UStaticMesh>(nullptr, BoxPath);
	UMaterialInterface* Surface = LoadObject<UMaterialInterface>(nullptr, SurfacePath);
	if (!TestNotNull(TEXT("engine cube"), Box) || !TestNotNull(TEXT("M_WP03_HoleSurface"), Surface))
	{
		return false;
	}

	// A 1.2 cm container wall (3x reference) at x = 300, a warm backdrop behind it, an olive one in front.
	const double WallX = 300.0;
	const double Thickness = 1.2;
	UStaticMeshComponent* WallMesh = nullptr;
	AActor* Wall = SpawnMesh(W, Box, Surface, FVector(WallX, 0, 0), FVector(Thickness, 100, 100), FLinearColor(0.3f, 0.3f, 0.3f),
		VerseCollision::Profile::Destructible, WallMesh);
	UStaticMeshComponent* Unused = nullptr;
	SpawnMesh(W, Box, Surface, FVector(WallX + 400, 0, 0), FVector(10, 300, 300), FLinearColor(0.6f, 0.45f, 0.25f),
		VerseCollision::Profile::NoCollision, Unused);
	SpawnMesh(W, Box, Surface, FVector(WallX - 400, 0, 0), FVector(10, 300, 300), FLinearColor(0.35f, 0.4f, 0.15f),
		VerseCollision::Profile::NoCollision, Unused);
	W.Penetration->RegisterPieceProxy(WallMesh, 1, EVersePenetrationMaterial::ContainerWall, Wall->GetRootComponent());
	W.Query.Materials.Add(1, EVersePenetrationMaterial::ContainerWall);

	uint32 Now = 10000;
	UVerseHoleRenderComponent* Render = NewObject<UVerseHoleRenderComponent>(W.Manager, TEXT("HoleRender"));
	Render->RegisterComponent();
	Render->SetServerTimeSource([&Now]() { return Now; });
	Render->SetHoleSource(W.Holes);
	const FVector Half(Thickness * 0.5, 50.0, 50.0);
	Render->RegisterPieceVisual(1, WallMesh, FBox(-Half, Half), Wall->GetRootComponent());
	// An uncooked game process compiles the mesh asynchronously, and a compiling mesh gets its
	// body only once the build is done: finish it, then tick until the wall blocks a probe ray.
	const FVector ProbeA(WallX - 50.0, 20.0, 0.0);
	const FVector ProbeB(WallX + 50.0, 20.0, 0.0);
	int32 Frames = 0;
	for (; Frames < 60 && W.Penetration->TestSight(ProbeA, ProbeB); ++Frames)
	{
		FAssetCompilingManager::Get().FinishAllCompilation();
		W.World()->SendAllEndOfFrameUpdates();
		W.Settle();
	}
	if (!TestFalse(*FString::Printf(TEXT("the wall collides after %d settles"), Frames), W.Penetration->TestSight(ProbeA, ProbeB)))
	{
		return false;
	}

	const FVector BoltOrigin(WallX - 250.0, 0, 0);
	const TArray<FVersePenetrationHit> Hits = W.Penetration->TraceBolt(BoltOrigin, FVector::ForwardVector, 400.f, 100.f, 30.f, 15, 3);
	for (const FVersePenetrationHit& Hit : Hits)
	{
		AddInfo(FString::Printf(TEXT("bolt hit piece %d material %d entry %s exit %s thickness %.4f cm passed %d power left %.2f"),
			int32(Hit.PieceIndex), int32(Hit.MaterialWireId), *Hit.Entry.ToString(), *Hit.Exit.ToString(), Hit.TracedThicknessCm,
			Hit.bPassed ? 1 : 0, Hit.PowerLeft));
	}
	TestEqual(TEXT("the bolt passes the wall"), Hits.Num() == 1 && Hits[0].bPassed, true);
	TestEqual(TEXT("one hole recorded"), W.Penetration->RecordBoltHoles(Hits, FVector::ForwardVector, 15, Now), 1);

	FActorSpawnParameters Params;
	Params.ObjectFlags = RF_Transient;
	AActor* CameraActor = W.World()->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
	UTextureRenderTarget2D* Target = NewObject<UTextureRenderTarget2D>(CameraActor);
	Target->RenderTargetFormat = RTF_RGBA8_SRGB;
	Target->ClearColor = FLinearColor::Black;
	Target->InitAutoFormat(ShotSize, ShotSize);
	Target->UpdateResourceImmediate(true);
	USceneCaptureComponent2D* Capture = NewObject<USceneCaptureComponent2D>(CameraActor, TEXT("Capture"));
	Capture->TextureTarget = Target;
	Capture->CaptureSource = SCS_FinalColorLDR;
	Capture->bCaptureEveryFrame = false;
	Capture->bCaptureOnMovement = false;
	Capture->FOVAngle = 30.f;
	Capture->ShowFlags.SetEyeAdaptation(false);
	Capture->ShowFlags.SetMotionBlur(false);
	Capture->ShowFlags.SetAntiAliasing(false);
	Capture->PostProcessSettings.bOverride_AutoExposureMethod = true;
	Capture->PostProcessSettings.AutoExposureMethod = AEM_Manual;
	Capture->PostProcessSettings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
	Capture->PostProcessSettings.AutoExposureApplyPhysicalCameraExposure = false;
	Capture->PostProcessSettings.bOverride_AutoExposureBias = true;
	Capture->PostProcessSettings.AutoExposureBias = 0.f;
	Capture->PostProcessSettings.bOverride_VignetteIntensity = true;
	Capture->PostProcessSettings.VignetteIntensity = 0.f;
	Capture->PostProcessBlendWeight = 1.f;
	CameraActor->SetRootComponent(Capture);
	Capture->RegisterComponent();

	auto Shoot = [&](const FVector& Eye, const FVector& LookAt) {
		FShot Shot;
		Render->Sync();
		FAssetCompilingManager::Get().FinishAllCompilation();
		W.World()->SendAllEndOfFrameUpdates();
		Capture->SetWorldLocationAndRotation(Eye, (LookAt - Eye).Rotation());
		// The first capture after a change can still miss compiled shaders or the mask draw.
		// ReadPixels flushes the render thread (VerseDestruction does not link RenderCore).
		TArray<FColor> Warmup;
		for (int32 Pass = 0; Pass < 3; ++Pass)
		{
			Capture->CaptureScene();
			Target->GameThread_GetRenderTargetResource()->ReadPixels(Warmup);
		}
		Target->GameThread_GetRenderTargetResource()->ReadPixels(Shot.Pixels);
		for (const FColor& Pixel : Shot.Pixels)
		{
			Shot.Banned += VerseHoleGlow::IsBannedPixel(Pixel) ? 1 : 0;
			Shot.Hot += IsHot(Pixel) ? 1 : 0;
		}
		if (Shot.Pixels.Num() == ShotSize * ShotSize)
		{
			Shot.Centre = Shot.Pixels[(ShotSize / 2) * ShotSize + ShotSize / 2];
			// Wall beside the hole: 150 px (about 8 cm) off the centre, outside the rim decal.
			Shot.Wall = Shot.Pixels[(ShotSize / 2) * ShotSize + ShotSize / 2 + 150];
		}
		return Shot;
	};

	const FVector Front(WallX - 50.0, 0, 0);
	const FVector Back(WallX + 50.0, 0, 0);
	const FVector Hole(WallX, 0, 0);
	const float Ages[] = {0.f, 1.f, 2.5f, 4.f};
	int32 HotAtImpact = 0;
	// Warm-up: the first frames with the rim decal compile its material and draw the mask.
	for (int32 Warm = 0; Warm < 3; ++Warm)
	{
		Shoot(Front, Hole);
	}
	for (const float Age : Ages)
	{
		Now = 10000 + uint32(Age * 1000.f);
		const FShot Shot = Shoot(Front, Hole);
		if (!TestEqual(TEXT("a full frame"), Shot.Pixels.Num(), ShotSize * ShotSize))
		{
			return false;
		}
		SavePng(*this, FString::Printf(TEXT("hole_cooling_%04dms"), int32(Age * 1000.f)), Shot.Pixels);
		TestEqual(*FString::Printf(TEXT("%.1f s: banned pixels"), Age), Shot.Banned, 0);
		AddInfo(FString::Printf(TEXT("%.1f s: %d glowing rim pixels, %d banned"), Age, Shot.Hot, Shot.Banned));
		if (Age == 0.f)
		{
			HotAtImpact = Shot.Hot;
			TestTrue(*FString::Printf(TEXT("the rim glows at impact (%d hot pixels)"), Shot.Hot), Shot.Hot > 20);
		}
		if (Age >= 4.f)
		{
			TestTrue(*FString::Printf(TEXT("the glow is out at 4 s (%d hot pixels)"), Shot.Hot), Shot.Hot * 20 < FMath::Max(HotAtImpact, 1));
		}
	}

	// Through the hole from both sides: the backdrop behind the wall fills the hole's centre.
	const FShot FrontShot = Shoot(Front, Hole);
	const FShot BackShot = Shoot(Back, Hole);
	SavePng(*this, TEXT("hole_through_front"), FrontShot.Pixels);
	SavePng(*this, TEXT("hole_through_back"), BackShot.Pixels);
	auto Differs = [](const FColor& A, const FColor& B) {
		return FMath::Abs(int32(A.R) - int32(B.R)) + FMath::Abs(int32(A.G) - int32(B.G)) + FMath::Abs(int32(A.B) - int32(B.B)) > 40;
	};
	TestTrue(*FString::Printf(TEXT("front: the hole shows the warm backdrop (%s vs wall %s)"), *FrontShot.Centre.ToString(), *FrontShot.Wall.ToString()),
		Differs(FrontShot.Centre, FrontShot.Wall) && FrontShot.Centre.R > FrontShot.Centre.B + 20);
	TestTrue(*FString::Printf(TEXT("back: the hole shows the olive backdrop (%s vs wall %s)"), *BackShot.Centre.ToString(), *BackShot.Wall.ToString()),
		Differs(BackShot.Centre, BackShot.Wall) && BackShot.Centre.G > BackShot.Centre.B + 20);
	TestEqual(TEXT("front and back palettes clean"), FrontShot.Banned + BackShot.Banned, 0);
	TestTrue(TEXT("TestSight sees through the hole front to back"), W.Penetration->TestSight(Front, Back));
	TestTrue(TEXT("TestSight sees through the hole back to front"), W.Penetration->TestSight(Back, Front));
	TestFalse(TEXT("TestSight is blocked beside the hole"), W.Penetration->TestSight(Front + FVector(0, 20, 0), Back + FVector(0, 20, 0)));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

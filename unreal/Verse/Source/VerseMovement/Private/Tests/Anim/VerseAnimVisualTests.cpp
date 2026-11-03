#include "Anim/VerseFirstPerson.h"
#include "Anim/VerseHumanSkeleton.h"
#include "Animation/AnimSequence.h"
#include "Animation/SkeletalMeshActor.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/Engine.h"
#include "Engine/PointLight.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/Paths.h"
#include "UnrealClient.h"

#if WITH_DEV_AUTOMATION_TESTS

/*
 * Verse.Visual.Characters (WP13 evidence, run by scripts/unreal/screenshot.py):
 * turnarounds of every body and uniform, first-person views per weapon
 * (idle, ADS, reload), the paired finisher at its phase markers and the
 * wall-clipping pair of A13.5 (weapon 20 cm from a wall, with and without
 * the wall). PNGs go to Saved/Harness/proof/WP13/visual/.
 */
namespace VerseVisual
{
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

	FString ProofDir()
	{
		return FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/WP13/visual")));
	}

	struct FShot
	{
		FString Name;
		TFunction<void(UWorld*)> Setup;
	};

	class FStage
	{
	public:
		TArray<TWeakObjectPtr<AActor>> Actors;
		ACameraActor* Camera = nullptr;

		void Clear()
		{
			for (TWeakObjectPtr<AActor>& A : Actors)
			{
				if (A.IsValid())
				{
					A->Destroy();
				}
			}
			Actors.Reset();
		}

		template <typename T>
		T* Spawn(UWorld* World, const FVector& Location, const FRotator& Rotation = FRotator::ZeroRotator)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			T* Actor = World->SpawnActor<T>(Location, Rotation, Params);
			Actors.Add(Actor);
			return Actor;
		}

		void Lights(UWorld* World)
		{
			ADirectionalLight* Sun = Spawn<ADirectionalLight>(World, FVector(0, 0, 500), FRotator(-40.f, 35.f, 0.f));
			Sun->GetLightComponent()->SetMobility(EComponentMobility::Movable);
			Sun->GetLightComponent()->SetIntensity(6.f);
			for (const FVector& P : {FVector(250, -250, 260), FVector(-250, 200, 220)})
			{
				APointLight* Fill = Spawn<APointLight>(World, P);
				Fill->PointLightComponent->SetMobility(EComponentMobility::Movable);
				Fill->PointLightComponent->SetIntensity(9000.f);
				Fill->PointLightComponent->SetAttenuationRadius(2000.f);
			}
			UStaticMesh* Plane = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Plane.Plane"));
			if (Plane)
			{
				AStaticMeshActor* Floor = Spawn<AStaticMeshActor>(World, FVector::ZeroVector);
				Floor->GetStaticMeshComponent()->SetMobility(EComponentMobility::Movable);
				Floor->GetStaticMeshComponent()->SetStaticMesh(Plane);
				Floor->SetActorScale3D(FVector(30, 30, 1));
			}
		}

		USkeletalMeshComponent* Character(UWorld* World, const TCHAR* MeshPath, const FVector& At, float Yaw, const TCHAR* Clip, float Time)
		{
			USkeletalMesh* Mesh = LoadObject<USkeletalMesh>(nullptr, MeshPath);
			ASkeletalMeshActor* Actor = Spawn<ASkeletalMeshActor>(World, At, FRotator(0.f, Yaw, 0.f));
			USkeletalMeshComponent* Comp = Actor->GetSkeletalMeshComponent();
			Comp->SetMobility(EComponentMobility::Movable);
			Comp->SetSkeletalMesh(Mesh);
			if (UAnimSequence* Seq = Clip ? LoadObject<UAnimSequence>(nullptr, *VerseHuman::ClipPath(Clip)) : nullptr)
			{
				Comp->SetAnimationMode(EAnimationMode::AnimationSingleNode);
				Comp->PlayAnimation(Seq, false);
				Comp->SetPosition(Time, false);
				Comp->SetPlayRate(0.f);
				Comp->TickAnimation(0.f, false);
				Comp->RefreshBoneTransforms();
			}
			return Comp;
		}

		/**
		 * A stand-in weapon on `Weapon_R` until WP14's weapons land: a box around the
		 * reference grip (barrel along +Y, the weapon frame), rendered first person.
		 */
		void StandInWeapon(USkeletalMeshComponent* Body, const FString& Clip)
		{
			UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
			if (!Cube || !Body || !Body->GetOwner())
			{
				return;
			}
			// Sizes in cm (X across, Y along the barrel, Z up) and centre in the weapon frame.
			FVector Size(5.0, 75.0, 14.0);
			FVector Centre(0.0, 17.5, -3.0);
			if (Clip.Contains(TEXT("Pistol")))
			{
				Size = FVector(3.5, 21.0, 14.0);
				Centre = FVector(0.0, 7.5, -4.0);
			}
			else if (Clip.Contains(TEXT("Knife")))
			{
				Size = FVector(1.0, 22.0, 3.0);
				Centre = FVector(0.0, 9.0, 0.0);
			}
			UStaticMeshComponent* Weapon = NewObject<UStaticMeshComponent>(Body->GetOwner());
			Weapon->SetMobility(EComponentMobility::Movable);
			Weapon->SetStaticMesh(Cube);
			Weapon->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Weapon->SetupAttachment(Body, TEXT("Weapon_R"));
			Weapon->SetRelativeLocation(Centre);
			Weapon->SetRelativeScale3D(Size / 100.0);
			Weapon->RegisterComponent();
			UVerseFirstPersonLibrary::MarkFirstPerson(Weapon);
			const FVector Tip = Weapon->GetComponentTransform().TransformPosition(FVector(0.0, 50.0, 0.0));
			UE_LOG(LogTemp, Display, TEXT("VerseVisual stand-in %s: root %s tip %s"), *Clip,
				*Body->GetSocketLocation(TEXT("Weapon_R")).ToString(), *Tip.ToString());
		}

		void Look(UWorld* World, const FVector& From, const FVector& At, float Fov = 40.f)
		{
			Camera = Spawn<ACameraActor>(World, From, (At - From).Rotation());
			Camera->GetCameraComponent()->SetFieldOfView(Fov);
			Camera->GetCameraComponent()->bConstrainAspectRatio = false;
			if (APlayerController* PC = World->GetFirstPlayerController())
			{
				PC->SetViewTarget(Camera);
			}
		}
	};

	FStage& Shared()
	{
		static FStage Stage;
		return Stage;
	}

	/** Runs the shots one after another: setup, settle a few frames, capture, wait for the file. */
	class FShotsCommand : public IAutomationLatentCommand
	{
	public:
		FShotsCommand(FAutomationTestBase* InTest, TArray<FShot> InShots) : Test(InTest), Shots(MoveTemp(InShots)) {}

		virtual bool Update() override
		{
			UWorld* World = GameWorld();
			if (!World)
			{
				Test->AddError(TEXT("no game world (run through scripts/unreal/screenshot.py)"));
				return true;
			}
			if (Index >= Shots.Num())
			{
				Shared().Clear();
				return true;
			}
			const double Now = FPlatformTime::Seconds();
			if (Phase == 0)
			{
				Shared().Clear();
				Shared().Lights(World);
				Shots[Index].Setup(World);
				Phase = 1;
				Start = Now;
				return false;
			}
			if (Phase == 1 && Now - Start > 1.5)
			{
				File = FPaths::Combine(ProofDir(), Shots[Index].Name + TEXT(".png"));
				IFileManager::Get().Delete(*File, false, true, true);
				FScreenshotRequest::RequestScreenshot(File, false, false);
				Phase = 2;
				Start = Now;
				return false;
			}
			if (Phase == 2 && (IFileManager::Get().FileExists(*File) || Now - Start > 10.0))
			{
				if (!IFileManager::Get().FileExists(*File))
				{
					Test->AddError(FString::Printf(TEXT("screenshot %s was not written"), *File));
				}
				++Index;
				Phase = 0;
			}
			return false;
		}

	private:
		FAutomationTestBase* Test;
		TArray<FShot> Shots;
		int32 Index = 0;
		int32 Phase = 0;
		double Start = 0.0;
		FString File;
	};

}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualCharactersTest, "Verse.Visual.Characters",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVerseVisualCharactersTest::RunTest(const FString& Parameters)
{
	using namespace VerseVisual;
	IFileManager::Get().MakeDirectory(*ProofDir(), true);
	TArray<FShot> Shots;
	// Turnarounds: every body and uniform, four sides, the stand idle's first frame.
	for (const TCHAR* Path : VerseHuman::MeshPaths())
	{
		const FString Name = FPaths::GetBaseFilename(FString(Path).LeftChop(FString(Path).Len() - FString(Path).Find(TEXT("."))));
		for (const float Yaw : {0.f, 90.f, 180.f, 270.f})
		{
			Shots.Add({FString::Printf(TEXT("turn_%s_%03d"), *Name, FMath::RoundToInt(Yaw)), [Path, Yaw](UWorld* World)
				{
					FStage& S = Shared();
					S.Character(World, Path, FVector::ZeroVector, Yaw, TEXT("A_Stand_Idle"), 0.f);
					S.Look(World, FVector(0, 680, 100), FVector(0, 0, 92), 30.f);
				}});
		}
	}
	// First person per weapon: idle, ADS, reload (mid), from the Camera bone with the head hidden.
	struct FFp
	{
		const TCHAR* Clip;
		float Time;
	};
	const FFp FirstPerson[] = {{TEXT("A_Rifle_Idle"), 0.f}, {TEXT("A_Rifle_ADS"), 0.f}, {TEXT("A_Rifle_Reload_Tactical"), 0.8f},
		{TEXT("A_Pistol_Idle"), 0.f}, {TEXT("A_Pistol_ADS"), 0.f}, {TEXT("A_Pistol_Reload_Empty"), 0.6f}, {TEXT("A_Knife_Idle"), 0.f},
		{TEXT("A_Knife_Strike"), 0.15f}};
	for (const FFp& Fp : FirstPerson)
	{
		const FString ClipName(Fp.Clip);
		const float Time = Fp.Time;
		Shots.Add({FString::Printf(TEXT("fp_%s"), Fp.Clip), [ClipName, Time](UWorld* World)
			{
				FStage& S = Shared();
				USkeletalMeshComponent* Body = S.Character(World, VerseHuman::MeshPaths()[0], FVector::ZeroVector, -90.f, *ClipName, Time);
				const FTransform Eye = Body->GetSocketTransform(TEXT("Camera"));
				S.Look(World, Eye.GetLocation(), Eye.GetLocation() + FVector(100, 0, 0), 100.f);
				UVerseFirstPersonLibrary::ConfigureOwnerView(Body, nullptr, S.Camera->GetCameraComponent());
				Body->SetOnlyOwnerSee(false);
				S.StandInWeapon(Body, ClipName);
			}});
	}
	// A13.5 pair: the rifle at ADS (the weapon in the owner's view) with a wall 20 cm in front of the hands, and without it.
	// The third shot hides the body: the pixels that differ from "off" are the body's (the A13.5 mask).
	for (const int32 Variant : {0, 1, 2})
	{
		const bool bWall = Variant == 1;
		const bool bBody = Variant != 2;
		const TCHAR* Names[] = {TEXT("fp_wall_off"), TEXT("fp_wall_on"), TEXT("fp_wall_nobody")};
		Shots.Add({Names[Variant], [bWall, bBody](UWorld* World)
			{
				FStage& S = Shared();
				USkeletalMeshComponent* Body = S.Character(World, VerseHuman::MeshPaths()[0], FVector::ZeroVector, -90.f, TEXT("A_Rifle_ADS"), 0.f);
				const FTransform Eye = Body->GetSocketTransform(TEXT("Camera"));
				const FVector Hand = Body->GetSocketLocation(TEXT("Hand_L"));
				S.Look(World, Eye.GetLocation(), Eye.GetLocation() + FVector(100, 0, 0), 100.f);
				UVerseFirstPersonLibrary::ConfigureOwnerView(Body, nullptr, S.Camera->GetCameraComponent());
				Body->SetOnlyOwnerSee(false);
				if (bBody)
				{
					S.StandInWeapon(Body, TEXT("A_Rifle_ADS"));
				}
				Body->SetVisibility(bBody);
				if (bWall)
				{
					if (UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube")))
					{
						AStaticMeshActor* Wall = S.Spawn<AStaticMeshActor>(World, FVector(Hand.X + 20.0 + 5.0, 0, 150));
						Wall->GetStaticMeshComponent()->SetMobility(EComponentMobility::Movable);
						Wall->GetStaticMeshComponent()->SetStaticMesh(Cube);
						Wall->SetActorScale3D(FVector(0.1, 8, 4));
						UE_LOG(LogTemp, Display, TEXT("VerseVisual wall: eye %s hand_l %s wall face x %.1f"),
							*Eye.GetLocation().ToString(), *Hand.ToString(), Hand.X + 20.0);
					}
				}
			}});
	}
	// Finisher: attacker and victim at each phase marker, side view.
	for (const TPair<FName, float>& Marker : VerseHuman::FinisherMarkers())
	{
		for (const float Offset : {0.f, -0.12f})
		{
			const float Time = FMath::Max(0.f, Marker.Value + Offset);
			const FString Name = FString::Printf(TEXT("finisher_%04d_%s"), FMath::RoundToInt(Time * 1000.f), *Marker.Key.ToString());
			Shots.Add({Name, [Time](UWorld* World)
				{
					FStage& S = Shared();
					// Mesh forward is +Y; actor yaw -90 turns it to +X. The victim starts 55 cm ahead.
					S.Character(World, TEXT("/Game/Verse/Characters/Opponent/SK_Opponent_M.SK_Opponent_M"), FVector(0, 0, 0), -90.f,
						TEXT("A_Finisher_Attacker"), Time);
					S.Character(World, TEXT("/Game/Verse/Characters/Crew/SK_Crew_M.SK_Crew_M"), FVector(55, 0, 0), -90.f,
						TEXT("A_Finisher_Victim"), Time);
					S.Look(World, FVector(40, -480, 140), FVector(40, 0, 70), 35.f);
				}});
		}
	}
	ADD_LATENT_AUTOMATION_COMMAND(FShotsCommand(this, MoveTemp(Shots)));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

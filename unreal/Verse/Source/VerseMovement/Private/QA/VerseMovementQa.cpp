#include "QA/VerseMovementQa.h"

#include "Camera/CameraActor.h"
#include "Containers/Ticker.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Fixture/VerseMovementCourse.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Qa/VerseQaRegistry.h"
#include "Subsystems/EngineSubsystem.h"
#include "UnrealClient.h"
#include "VerseCharacter.h"
#include "VerseCharacterMovement.h"
#include "VerseLog.h"
#include "VerseMovementScripts.h"


namespace
{
	AVerseCharacter* FindLocalPawn()
	{
		if (!GEngine)
		{
			return nullptr;
		}
		for (const FWorldContext& Context : GEngine->GetWorldContexts())
		{
			UWorld* World = Context.World();
			if (!World || (Context.WorldType != EWorldType::Game && Context.WorldType != EWorldType::PIE))
			{
				continue;
			}
			for (FConstPlayerControllerIterator It = World->GetPlayerControllerIterator(); It; ++It)
			{
				APlayerController* Controller = It->Get();
				if (Controller && Controller->IsLocalController())
				{
					if (AVerseCharacter* Pawn = Cast<AVerseCharacter>(Controller->GetPawn()))
					{
						return Pawn;
					}
				}
			}
		}
		return nullptr;
	}

	FString StateJson(const AVerseCharacter& Pawn)
	{
		const UVerseCharacterMovement* M = Pawn.GetVerseMovement();
		const FVector L = Pawn.GetActorLocation();
		return FString::Printf(
			TEXT("{\"pawn\": \"%s\", \"location\": [%.1f, %.1f, %.1f], \"stance\": \"%s\", \"lean\": %d, \"sprinting\": %s, \"airborne\": %s, \"mantling\": %s, \"blocks_firing\": %s, \"mantles\": %d, \"net\": %s}"),
			*Pawn.GetName(), L.X, L.Y, L.Z, *StaticEnum<EVerseStance>()->GetNameStringByValue(int64(M->GetStance())), int32(M->GetLeanQuantized()),
			M->IsSprinting() ? TEXT("true") : TEXT("false"), M->IsAirborne() ? TEXT("true") : TEXT("false"),
			M->IsMantling() ? TEXT("true") : TEXT("false"), M->BlocksFiring() ? TEXT("true") : TEXT("false"), M->GetMantleCount(),
			*M->GetNetStats().ToJson());
	}

	void Place(AVerseCharacter& Pawn, const FVector& Feet, float Yaw)
	{
		const float Half = Pawn.GetSimpleCollisionHalfHeight();
		Pawn.SetActorLocationAndRotation(Feet + FVector(0.f, 0.f, Half + 2.f), FRotator(0.f, Yaw, 0.f), false, nullptr, ETeleportType::TeleportPhysics);
		if (AController* Controller = Pawn.GetController())
		{
			Controller->SetControlRotation(FRotator(0.f, Yaw, 0.f));
		}
		Pawn.GetVerseMovement()->StopMovementImmediately();
	}
}

void UVerseMovementQa::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Collection.InitializeDependency<UVerseQaRegistry>();
	if (UVerseQaRegistry* Registry = UVerseQaRegistry::Get())
	{
		auto Add = [this, Registry](const TCHAR* Name, const TCHAR* Help, FVerseQaHandler Handler)
		{
			if (Registry->Register(Name, Help, MoveTemp(Handler)))
			{
				Registered.Add(Name);
			}
		};
		Add(TEXT("Verse.QA.Movement.State"), TEXT("Movement state of the local pawn (stance, lean, flags, corrections)"),
			[](const TArray<FString>&) -> FString
			{
				const AVerseCharacter* Pawn = FindLocalPawn();
				return Pawn ? StateJson(*Pawn) : FString(TEXT("{\"error\": \"no local Verse pawn\"}"));
			});
		Add(TEXT("Verse.QA.Movement.Soak"), TEXT("Verse.QA.Movement.Soak <seconds> <seed> <report.json> [quit]: seeded movement soak"),
			[this](const TArray<FString>& Args) -> FString
			{
				if (Args.Num() < 3)
				{
					return TEXT("{\"error\": \"usage: <seconds> <seed> <report.json> [quit]\"}");
				}
				const bool bOk = StartSoak(FCString::Atof(*Args[0]), FCString::Strtoui64(*Args[1], nullptr, 10), Args[2], Args.Num() > 3 && Args[3] == TEXT("quit"));
				return bOk ? FString(TEXT("{\"started\": true}")) : FString(TEXT("{\"error\": \"no local Verse pawn\"}"));
			});
		Add(TEXT("Verse.QA.Movement.Shoot"), TEXT("Verse.QA.Movement.Shoot <folder>: capture mantle, slide and lean shots on LV_Test_Movement"),
			[this](const TArray<FString>& Args) -> FString
			{
				const FString Folder = Args.Num() ? Args[0] : FPaths::ProjectSavedDir() / TEXT("Harness/proof/WP01/1.9");
				return StartShoot(Folder) ? FString(TEXT("{\"started\": true}")) : FString(TEXT("{\"error\": \"no local Verse pawn\"}"));
			});
	}

	FString Soak;
	if (FParse::Value(FCommandLine::Get(), TEXT("VerseMovementSoak="), Soak))
	{
		TArray<FString> Parts;
		Soak.ParseIntoArray(Parts, TEXT(":"));
		if (Parts.Num() >= 3)
		{
			PendingSoakSeconds = FCString::Atof(*Parts[0]);
			PendingSoakSeed = FCString::Strtoui64(*Parts[1], nullptr, 10);
			PendingSoakReport = FString::Join(TArrayView<const FString>(Parts).RightChop(2), TEXT(":"));
		}
	}
	FParse::Value(FCommandLine::Get(), TEXT("VerseMovementShoot="), PendingShootFolder);
	TickHandle = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateUObject(this, &UVerseMovementQa::Tick));
}

void UVerseMovementQa::Deinitialize()
{
	FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
	if (UVerseQaRegistry* Registry = UVerseQaRegistry::Get())
	{
		for (const FString& Name : Registered)
		{
			Registry->Unregister(Name);
		}
	}
	Registered.Reset();
	Super::Deinitialize();
}

bool UVerseMovementQa::StartSoak(float Seconds, uint64 Seed, const FString& Report, bool bQuit)
{
	AVerseCharacter* Pawn = FindLocalPawn();
	if (!Pawn)
	{
		return false;
	}
	SoakPawn = Pawn;
	SoakReport = Report;
	SoakSeconds = Seconds;
	SoakElapsed = 0.f;
	bSoakRunning = true;
	bSoakQuit = bQuit;
	Pawn->GetVerseMovement()->GetNetStats() = FVerseMovementNetStats();
	Pawn->SetInputScript(VerseMovementScripts::MakeSoak(Seed, Seconds, Pawn, FVector::ZeroVector));
	UE_LOG(LogVerseQa, Display, TEXT("movement soak: %.0f s, seed %llu, report %s"), Seconds, Seed, *Report);
	return true;
}

bool UVerseMovementQa::Tick(float DeltaSeconds)
{
	if (PendingSoakSeconds > 0.f || !PendingShootFolder.IsEmpty())
	{
		WaitTime += DeltaSeconds;
		AVerseCharacter* Pawn = FindLocalPawn();
		// Give the connection a moment to settle before measuring.
		if (Pawn && Pawn->HasActorBegunPlay() && WaitTime > 3.f)
		{
			if (PendingSoakSeconds > 0.f)
			{
				StartSoak(PendingSoakSeconds, PendingSoakSeed, PendingSoakReport, true);
				PendingSoakSeconds = 0.f;
			}
			else
			{
				StartShoot(PendingShootFolder);
				PendingShootFolder.Reset();
			}
		}
		else if (WaitTime > 120.f)
		{
			UE_LOG(LogVerseQa, Error, TEXT("movement QA driver: no local Verse pawn after 120 s"));
			PendingSoakSeconds = 0.f;
			PendingShootFolder.Reset();
			FPlatformMisc::RequestExit(false);
		}
	}
	if (bSoakRunning)
	{
		SoakElapsed += DeltaSeconds;
		AVerseCharacter* Pawn = SoakPawn.Get();
		if (!Pawn || !Pawn->HasInputScript())
		{
			bSoakRunning = false;
			const UVerseCharacterMovement* M = Pawn ? Pawn->GetVerseMovement() : nullptr;
			const FString Json = M
				? FString::Printf(TEXT("{\"role\": \"client\", \"seconds\": %.2f, \"mantles\": %d, \"stats\": %s}"), SoakElapsed, M->GetMantleCount(), *M->GetNetStats().ToJson())
				: FString(TEXT("{\"role\": \"client\", \"error\": \"pawn lost\"}"));
			FFileHelper::SaveStringToFile(Json, *SoakReport);
			UE_LOG(LogVerseQa, Display, TEXT("movement soak done: %s"), *Json);
			if (bSoakQuit)
			{
				FPlatformMisc::RequestExit(false);
			}
		}
	}
	if (ShootStep >= 0)
	{
		TickShoot(DeltaSeconds);
	}
	return true;
}

bool UVerseMovementQa::StartShoot(const FString& Folder)
{
	AVerseCharacter* Pawn = FindLocalPawn();
	if (!Pawn)
	{
		return false;
	}
	ShootPawn = Pawn;
	ShootFolder = Folder;
	IFileManager::Get().MakeDirectory(*Folder, true);
	ShootCamera = Pawn->GetWorld()->SpawnActor<ACameraActor>();
	ShootStep = 0;
	ShootTime = 0.f;
	bShotTaken = false;
	return true;
}

void UVerseMovementQa::TickShoot(float DeltaSeconds)
{
	using namespace VerseMovementCourse;
	AVerseCharacter* Pawn = ShootPawn.Get();
	ACameraActor* Camera = ShootCamera.Get();
	APlayerController* Controller = Pawn ? Cast<APlayerController>(Pawn->GetController()) : nullptr;
	if (!Pawn || !Camera || !Controller)
	{
		ShootStep = -1;
		return;
	}
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	auto Shot = [this](const TCHAR* Name)
	{
		FScreenshotRequest::RequestScreenshot(FPaths::Combine(ShootFolder, FString(Name) + TEXT(".png")), false, false);
		UE_LOG(LogVerseQa, Display, TEXT("movement shot %s"), Name);
	};
	auto Look = [Camera, Controller](const FVector& From, const FVector& At)
	{
		Camera->SetActorLocationAndRotation(From, (At - From).Rotation());
		Controller->SetViewTarget(Camera);
	};
	auto Next = [this]() { ++ShootStep; ShootTime = 0.f; bShotTaken = false; };
	ShootTime += DeltaSeconds;
	const float LaneY = LedgeLaneY(2); // 1.5 m ledge
	switch (ShootStep)
	{
	case 0: // mantle: walk at the 1.5 m ledge and hold jump
		Place(*Pawn, FVector(LedgeFaceX - 160.f, LaneY, 0.f), 0.f);
		Pawn->SetInputScript([](float T, float, FVerseInputFrame& F)
		{
			F.Move = FVector2f(1.f, 0.f);
			F.Buttons = T > 0.2f ? uint32(EVerseInputButton::Jump) : 0u;
			F.Pressed = (T > 0.2f && T < 0.25f) ? uint32(EVerseInputButton::Jump) : 0u;
			return T < 2.f;
		});
		Look(FVector(LedgeFaceX - 40.f, LaneY - 520.f, 170.f), FVector(LedgeFaceX - 40.f, LaneY, 120.f));
		Next();
		break;
	case 1:
		if (M->IsMantling() && M->GetMantleElapsed() > M->GetMantleDuration() * 0.5f && !bShotTaken)
		{
			Shot(TEXT("mantle_side"));
			bShotTaken = true;
		}
		if ((bShotTaken && ShootTime > 1.5f) || ShootTime > 4.f)
		{
			Next();
		}
		break;
	case 2: // slide on the open floor
		Place(*Pawn, FVector(-600.f, OpenFloorY, 0.f), 0.f);
		Pawn->SetInputScript([](float T, float, FVerseInputFrame& F)
		{
			F.Move = FVector2f(1.f, 0.f);
			F.Buttons = uint32(EVerseInputButton::Sprint) | (T > 1.4f ? uint32(EVerseInputButton::Crouch) : 0u);
			F.Pressed = (T > 1.4f && T < 1.45f) ? uint32(EVerseInputButton::Crouch) : 0u;
			return T < 3.f;
		});
		Next();
		break;
	case 3:
		if (M->IsSliding() && !bShotTaken)
		{
			const FVector At = Pawn->GetActorLocation();
			Look(At + FVector(250.f, -450.f, 60.f), At + FVector(120.f, 0.f, -40.f));
			if (ShootTime > 1.65f)
			{
				Shot(TEXT("slide_side"));
				bShotTaken = true;
			}
		}
		if ((bShotTaken && ShootTime > 3.f) || ShootTime > 5.f)
		{
			Next();
		}
		break;
	case 4: // lean left into the open corridor, seen from behind
		Place(*Pawn, FVector(CornerEndX - 150.f, CornerLaneY, 0.f), 0.f);
		Pawn->SetInputScript([](float T, float, FVerseInputFrame& F)
		{
			F.Buttons = uint32(EVerseInputButton::LeanLeft);
			return T < 3.f;
		});
		Look(FVector(CornerEndX - 520.f, CornerLaneY, 190.f), FVector(CornerEndX - 150.f, CornerLaneY, 130.f));
		Next();
		break;
	case 5:
		if (ShootTime > 0.6f && !bShotTaken)
		{
			Shot(TEXT("lean_behind"));
			bShotTaken = true;
		}
		if (ShootTime > 1.2f)
		{
			Controller->SetViewTarget(Pawn);
			Next();
		}
		break;
	case 6:
		if (ShootTime > 0.5f && !bShotTaken)
		{
			Shot(TEXT("lean_first_person"));
			bShotTaken = true;
		}
		if (ShootTime > 1.5f)
		{
			Next();
		}
		break;
	default:
		UE_LOG(LogVerseQa, Display, TEXT("movement shots done: %s"), *ShootFolder);
		ShootStep = -1;
		FPlatformMisc::RequestExit(false);
		break;
	}
}

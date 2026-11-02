#include "VerseHarnessSubsystem.h"

#include "Balance/VerseBalanceGauntletController.h"
#include "Balance/VerseHarnessScenario.h"
#include "Capture/VerseCaptureDirector.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformTime.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "VerseLog.h"

namespace VerseHarnessSubsystemPrivate
{
	bool Switch(const TCHAR* Name, FString& Out) { return FParse::Value(FCommandLine::Get(), Name, Out); }
}

bool UVerseHarnessSubsystem::IsHarnessRun()
{
	FString Unused;
	using namespace VerseHarnessSubsystemPrivate;
	return Switch(TEXT("VerseHarness="), Unused) || Switch(TEXT("VerseCapture="), Unused)
		|| Switch(TEXT("VerseNetDuration="), Unused);
}

bool UVerseHarnessSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return IsHarnessRun() && Super::ShouldCreateSubsystem(Outer);
}

void UVerseHarnessSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	StartWallS = FPlatformTime::Seconds();
	TickHandle = FTSTicker::GetCoreTicker().AddTicker(
		FTickerDelegate::CreateUObject(this, &UVerseHarnessSubsystem::TickHarness));
}

void UVerseHarnessSubsystem::Deinitialize()
{
	FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
	Super::Deinitialize();
}

void UVerseHarnessSubsystem::Quit(const TCHAR* Why)
{
	if (bQuitRequested)
	{
		return;
	}
	bQuitRequested = true;
	UE_LOG(LogVerseHarness, Display, TEXT("[VerseHarness] exit: %s"), Why);
	FPlatformMisc::RequestExit(false, TEXT("VerseHarness"));
}

void UVerseHarnessSubsystem::StartDrivers(UWorld* World)
{
	using namespace VerseHarnessSubsystemPrivate;
	bStarted = true;
	FString Path;
	FString Error;
	if (Switch(TEXT("VerseHarness="), Path))
	{
		FString Text;
		FVerseHarnessScenario Scenario;
		if (!FFileHelper::LoadFileToString(Text, *Path) || !FVerseHarnessScenario::Parse(Text, Scenario, Error))
		{
			UE_LOG(LogVerseHarness, Error, TEXT("[VerseHarness] scenario %s: %s"), *Path, *Error);
			Quit(TEXT("bad scenario"));
			return;
		}
		Balance = NewObject<UVerseBalanceGauntletController>(this);
		if (!Balance->Start(World, Scenario, Error))
		{
			UE_LOG(LogVerseHarness, Error, TEXT("[VerseHarness] cannot start: %s"), *Error);
			Quit(TEXT("start failed"));
		}
		return;
	}
	if (Switch(TEXT("VerseCapture="), Path))
	{
		FString Text;
		FVerseCaptureScript Script;
		if (!FFileHelper::LoadFileToString(Text, *Path) || !FVerseCaptureScript::Parse(Text, Script, Error))
		{
			UE_LOG(LogVerseHarness, Error, TEXT("[VerseCapture] script %s: %s"), *Path, *Error);
			Quit(TEXT("bad capture script"));
			return;
		}
		FString Out;
		if (!Switch(TEXT("VerseCaptureOut="), Out))
		{
			Out = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness"), TEXT("proof"), TEXT("capture"));
		}
		Capture = NewObject<UVerseCaptureDirector>(this);
		if (!Capture->Start(World, Script, Out, FParse::Param(FCommandLine::Get(), TEXT("VersePerf")), Error))
		{
			Quit(TEXT("capture start failed"));
		}
		return;
	}
	FString Duration;
	if (Switch(TEXT("VerseNetDuration="), Duration))
	{
		NetDurationS = FCString::Atod(*Duration);
		NetStartS = World->GetTimeSeconds();
		FString Seed;
		bAutopilot = Switch(TEXT("VerseNetAutopilot="), Seed);
		AutopilotRng = FVerseRng(uint64(FCString::Atoi64(*Seed)), 0, EVerseRngSalt::Harness);
		if (World->GetNetMode() == NM_DedicatedServer || World->GetNetMode() == NM_ListenServer)
		{
			UE_LOG(LogVerseHarness, Display, TEXT("[VerseNet] server ready"));
		}
	}
}

void UVerseHarnessSubsystem::TickNet(UWorld* World, float DeltaS)
{
	const double Now = World->GetTimeSeconds();
	if (bAutopilot && World->GetNetMode() == NM_Client)
	{
		APlayerController* PC = World->GetFirstPlayerController();
		ACharacter* Character = PC ? Cast<ACharacter>(PC->GetPawn()) : nullptr;
		if (Character)
		{
			if (Now >= NextTurnS)
			{
				AutopilotMove = AutopilotRng.UnitDisk().GetSafeNormal();
				NextTurnS = Now + AutopilotRng.Range(0.5, 2.0);
				if (AutopilotRng.Chance(0.25))
				{
					Character->Jump();
				}
				if (AutopilotRng.Chance(0.2))
				{
					Character->bIsCrouched ? Character->UnCrouch() : Character->Crouch();
				}
			}
			Character->AddMovementInput(FVector(AutopilotMove.X, AutopilotMove.Y, 0.0), 1.f);
			++AutopilotTicks;
		}
	}
	if (NetStartS >= 0.0 && Now - NetStartS >= NetDurationS)
	{
		UE_LOG(LogVerseHarness, Display, TEXT("[VerseCounter] autopilotTicks=%lld"), AutopilotTicks);
		Quit(TEXT("netcode duration reached"));
	}
}

bool UVerseHarnessSubsystem::TickHarness(float DeltaS)
{
	if (bQuitRequested)
	{
		return true;
	}
	UGameInstance* GI = GetGameInstance();
	UWorld* World = GI ? GI->GetWorld() : nullptr;
	if (!World || !World->HasBegunPlay())
	{
		if (FPlatformTime::Seconds() - StartWallS > 600.0)
		{
			Quit(TEXT("no game world after 10 minutes"));
		}
		return true;
	}
	if (!bStarted)
	{
		StartDrivers(World);
	}
	if (Balance && !Balance->Tick())
	{
		Quit(TEXT("balance run finished"));
	}
	if (Capture && !Capture->Tick(DeltaS))
	{
		Quit(TEXT("capture finished"));
	}
	if (NetStartS >= 0.0)
	{
		TickNet(World, DeltaS);
	}
	return true;
}

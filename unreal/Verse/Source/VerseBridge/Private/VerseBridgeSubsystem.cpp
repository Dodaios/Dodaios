#include "VerseBridgeSubsystem.h"

#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Qa/VerseQaRegistry.h"
#include "Scalability.h"
#include "VerseFramePacing.h"
#include "VerseLog.h"
#include "Widgets/SWindow.h"

#if PLATFORM_WINDOWS
#include "Windows/WindowsHWrapper.h"
#endif

using namespace VerseBridgeJson;

/** The engine side of IVerseLifecycleHost. */
class FVerseEngineLifecycleHost : public IVerseLifecycleHost
{
public:
	explicit FVerseEngineLifecycleHost(UGameInstance* InGameInstance, FVerseBridgeClient* InClient)
		: GameInstance(InGameInstance)
		, Client(InClient)
	{
	}

	TSharedPtr<SWindow> Window() const
	{
		return GEngine && GEngine->GameViewport ? GEngine->GameViewport->GetWindow() : nullptr;
	}

	virtual void ShowWindow(const FVerseMonitor& Monitor, const FString& ActivationToken) override
	{
#if PLATFORM_LINUX
		if (!ActivationToken.IsEmpty())
		{
			// xdg-activation: the app handed its token over the bridge (architecture 1.2).
			FPlatformMisc::SetEnvironmentVar(TEXT("XDG_ACTIVATION_TOKEN"), *ActivationToken);
		}
#endif
		if (TSharedPtr<SWindow> W = Window())
		{
			W->MoveWindowTo(FVector2D(Monitor.X, Monitor.Y));
			W->Resize(FVector2D(Monitor.W, Monitor.H));
			W->ShowWindow();
			W->BringToFront(true);
			FSlateApplication::Get().SetAllUserFocusToGameViewport();
		}
	}

	virtual void HideWindow() override
	{
		if (TSharedPtr<SWindow> W = Window())
		{
			W->HideWindow();
		}
	}

	virtual void SetRendering(bool bOn) override
	{
		if (GEngine && GEngine->GameViewport)
		{
			GEngine->GameViewport->bDisableWorldRendering = !bOn;
		}
	}

	virtual void SetMaxFps(float Fps) override
	{
		// The frame pacer owns t.MaxFPS: 0 leaves the person's limit and the pacing rules in charge.
		FVerseFramePacing::SetLifecycleCap(Fps);
	}

	virtual void SetMuted(bool bMuted) override
	{
		FApp::SetVolumeMultiplier(bMuted ? 0.f : 1.f);
	}

	virtual void SetPaused(bool bPaused) override
	{
		if (GameInstance && GameInstance->GetWorld())
		{
			UGameplayStatics::SetGamePaused(GameInstance->GetWorld(), bPaused);
		}
	}

	virtual void SetLowScalability(bool bLow) override
	{
		if (bLow && !bLowered)
		{
			Saved = Scalability::GetQualityLevels();
			Scalability::FQualityLevels Low = Saved;
			Low.SetFromSingleQualityLevel(0);
			Scalability::SetQualityLevels(Low);
			bLowered = true;
		}
		else if (!bLow && bLowered)
		{
			Scalability::SetQualityLevels(Saved);
			bLowered = false;
		}
	}

	virtual void AllowForeground(int32 Pid) override
	{
#if PLATFORM_WINDOWS
		if (Pid > 0)
		{
			::AllowSetForegroundWindow(static_cast<DWORD>(Pid));
		}
#endif
	}

	virtual bool SaveState() override
	{
		const FString Path = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("VerseState.json"));
		const TSharedPtr<FJsonObject> State = MakeShared<FJsonObject>();
		State->SetObjectField(TEXT("settings"), Client ? Client->Settings.GetSettings() : MakeShared<FJsonObject>());
		State->SetNumberField(TEXT("saved_at"), FDateTime::UtcNow().ToUnixTimestampDecimal());
		return FFileHelper::SaveStringToFile(Write(State), *Path);
	}

	virtual void RequestExit() override
	{
		FPlatformMisc::RequestExit(false, TEXT("VerseLifecycle"));
	}

	virtual float Fps() const override
	{
		const double Dt = FApp::GetDeltaTime();
		return Dt > 0.0 ? float(1.0 / Dt) : 0.f;
	}

private:
	UGameInstance* GameInstance = nullptr;
	FVerseBridgeClient* Client = nullptr;
	Scalability::FQualityLevels Saved;
	bool bLowered = false;
};

/** The one key back to the app (default F10, rebindable; Esc stays the in-game menu). */
class FVerseReturnKeyProcessor : public IInputProcessor
{
public:
	explicit FVerseReturnKeyProcessor(FVerseLifecycleController* InLifecycle)
		: Lifecycle(InLifecycle)
	{
	}

	virtual void Tick(const float DeltaTime, FSlateApplication& SlateApp, TSharedRef<ICursor> Cursor) override {}

	virtual bool HandleKeyDownEvent(FSlateApplication& SlateApp, const FKeyEvent& InKeyEvent) override
	{
		if (!Lifecycle || Lifecycle->GetState() != EVerseLifecycleState::Visible)
		{
			return false;
		}
		const FKey Wanted(*Lifecycle->GetReturnKey());
		if (InKeyEvent.GetKey() == Wanted && !InKeyEvent.IsRepeat())
		{
			Lifecycle->ReturnToApp(TEXT("return_key"));
			return true;
		}
		return false;
	}

	virtual const TCHAR* GetDebugName() const override { return TEXT("VerseReturnKey"); }

private:
	FVerseLifecycleController* Lifecycle;
};

TArray<FString> UVerseBridgeSubsystem::DefaultTopics()
{
	return {TEXT("roster"), TEXT("panes"), TEXT("progression"), TEXT("groups"), TEXT("meetings"), TEXT("companion"), TEXT("lifecycle"), TEXT("panel")};
}

bool UVerseBridgeSubsystem::AcquireInstance()
{
	FPlatformProcess::FSemaphore* Lock = FPlatformProcess::NewInterprocessSynchObject(TEXT("DodaiosVerseInstance"), true, 1);
	if (!Lock)
	{
		return true;
	}
	if (!Lock->TryLock(0))
	{
		FPlatformProcess::DeleteInterprocessSynchObject(Lock);
		return false;
	}
	InstanceMutex = Lock;
	return true;
}

void UVerseBridgeSubsystem::ReleaseInstance()
{
	if (InstanceMutex)
	{
		FPlatformProcess::FSemaphore* Lock = static_cast<FPlatformProcess::FSemaphore*>(InstanceMutex);
		Lock->Unlock();
		FPlatformProcess::DeleteInterprocessSynchObject(Lock);
		InstanceMutex = nullptr;
	}
}

void UVerseBridgeSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	BridgeClient = MakeShared<FVerseBridgeClient>();
	EngineHost = MakeShared<FVerseEngineLifecycleHost>(GetGameInstance(), BridgeClient.Get());
	LifecycleController = MakeShared<FVerseLifecycleController>(*EngineHost, *BridgeClient);

	FVerseBridgeClient::FDiscovery Discovery;
	const bool bSupervised = !FPlatformMisc::GetEnvironmentVariable(TEXT("DODAIOS_VERSE_TOKEN")).IsEmpty();
	if (bSupervised)
	{
		bOwnsInstance = AcquireInstance();
		if (!bOwnsInstance)
		{
			// A second launch hands its command line to the first and exits.
			FFileHelper::SaveStringToFile(FCommandLine::Get(), *FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Verse.handoff")));
			UE_LOG(LogVerseBridge, Warning, TEXT("bridge: another Verse is running; handing over and exiting"));
			FPlatformMisc::RequestExit(false, TEXT("VerseSingleInstance"));
			return;
		}
	}
	if (!FVerseBridgeClient::Discover(Discovery))
	{
		UE_LOG(LogVerseBridge, Log, TEXT("bridge: no backend to talk to (no DODAIOS_VERSE_BRIDGE, no dev discovery file)"));
		return;
	}
	BridgeClient->Subscribe(DefaultTopics());
	BridgeClient->OnFrame.AddLambda([this](const FVerseBridgeFrame& F) { LifecycleController->HandleFrame(F); });
	BridgeClient->OnLaunchOver.AddLambda([this]() { LifecycleController->LaunchOver(); });
	BridgeClient->OnServerCommand.AddUObject(this, &UVerseBridgeSubsystem::HandleServerCommand);
	BridgeClient->Start(Discovery);
	bConnected = true;
	TickHandle = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateUObject(this, &UVerseBridgeSubsystem::Tick));
	if (FSlateApplication::IsInitialized())
	{
		ReturnKey = MakeShared<FVerseReturnKeyProcessor>(LifecycleController.Get());
		FSlateApplication::Get().RegisterInputPreProcessor(ReturnKey);
	}
	EndFrameHandle = FCoreDelegates::OnEndFrame.AddLambda([this]()
	{
		if (GEngine && GEngine->GameViewport && GFrameCounter > 2)
		{
			LifecycleController->NotifyFirstFrame((FPlatformTime::Seconds() - GStartTime) * 1000.0);
			FCoreDelegates::OnEndFrame.Remove(EndFrameHandle);
		}
	});
}

void UVerseBridgeSubsystem::Deinitialize()
{
	if (TickHandle.IsValid())
	{
		FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
	}
	if (EndFrameHandle.IsValid())
	{
		FCoreDelegates::OnEndFrame.Remove(EndFrameHandle);
	}
	if (ReturnKey.IsValid() && FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().UnregisterInputPreProcessor(ReturnKey);
	}
	if (BridgeClient)
	{
		BridgeClient->Stop();
	}
	ReleaseInstance();
	LifecycleController.Reset();
	EngineHost.Reset();
	BridgeClient.Reset();
	Super::Deinitialize();
}

bool UVerseBridgeSubsystem::Tick(float DeltaSeconds)
{
	if (BridgeClient)
	{
		BridgeClient->Tick(FPlatformTime::Seconds());
	}
	return true;
}

void UVerseBridgeSubsystem::HandleServerCommand(const FVerseBridgeFrame& Frame)
{
	// qa.exec (bridge-protocol.md 14): the backend forwards it only with DODAIOS_VERSE_QA=1.
	UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
	if (!Registry)
	{
		BridgeClient->Reply(Frame.Id, false, nullptr, TEXT("unavailable"), TEXT("QA registry is not running."));
		return;
	}
	TArray<FString> Args;
	if (const TArray<TSharedPtr<FJsonValue>>* A = Arr(Frame.Data, TEXT("args")))
	{
		for (const TSharedPtr<FJsonValue>& V : *A)
		{
			Args.Add(V->AsString());
		}
	}
	FString Out;
	const FString Command = Str(Frame.Data, TEXT("command"));
	if (!Registry->Execute(Command, Args, Out))
	{
		BridgeClient->Reply(Frame.Id, false, nullptr, TEXT("not_found"), Out);
		return;
	}
	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	const TSharedPtr<FJsonObject> Parsed = Read(Out);
	if (Parsed.IsValid())
	{
		Result->SetObjectField(TEXT("result"), Parsed);
	}
	else
	{
		Result->SetStringField(TEXT("result"), Out);
	}
	BridgeClient->Reply(Frame.Id, true, Result);
}

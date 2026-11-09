#include "Stream/VerseConsoleStreamDriver.h"

#include "Engine/Engine.h"
#include "HAL/IConsoleManager.h"
#include "Stream/VerseStreamInputPolicy.h"
#include "UnrealEngine.h"
#include "VerseLog.h"

namespace
{
	const TCHAR* const StartCommand = TEXT("PixelStreaming.StartStreaming");
	const TCHAR* const StopCommand = TEXT("PixelStreaming.StopStreaming");
	const TCHAR* const UrlVar = TEXT("PixelStreaming2.ConnectionURL");

	bool SetVar(const FString& Name, const FString& Value)
	{
		IConsoleVariable* Var = IConsoleManager::Get().FindConsoleVariable(*Name);
		if (Var == nullptr)
		{
			return false;
		}
		Var->Set(*Value, ECVF_SetByCode);
		return true;
	}
}

TArray<TPair<FString, FString>> FVerseConsoleStreamDriver::SettingsFor(const FVerseStreamConfig& Config)
{
	TArray<TPair<FString, FString>> Out;
	Out.Emplace(UrlVar, Config.SignalUrl);
	Out.Emplace(TEXT("PixelStreaming2.WebRTC.Fps"), FString::FromInt(Config.Fps));
	Out.Emplace(TEXT("PixelStreaming2.WebRTC.MaxBitrate"), FString::FromInt(Config.MaxBitrateBps));
	Out.Emplace(TEXT("PixelStreaming2.WebRTC.StartBitrate"), FString::FromInt(FMath::Min(Config.StartBitrateBps, Config.MaxBitrateBps)));
	Out.Emplace(TEXT("PixelStreaming2.Encoder.Codec"), Config.Codec);
	Out.Emplace(TEXT("PixelStreaming2.WebRTC.PortAllocatorFlags"), TEXT("DISABLE_STUN,DISABLE_RELAY"));
	Out.Emplace(TEXT("PixelStreaming2.WebRTC.DisableReceiveAudio"), TEXT("true"));
	Out.Emplace(TEXT("PixelStreaming2.WebRTC.DisableTransmitAudio"), TEXT("true"));
	Out.Emplace(TEXT("PixelStreaming2.AllowPixelStreamingCommands"), TEXT("false"));
	Out.Emplace(TEXT("PixelStreaming2.KeyFilter"), VerseStreamInput::BuildKeyFilter());
	return Out;
}

bool FVerseConsoleStreamDriver::IsAvailable() const
{
	IConsoleManager& Console = IConsoleManager::Get();
	return Console.FindConsoleVariable(UrlVar) != nullptr && Console.FindConsoleObject(StartCommand) != nullptr
		&& Console.FindConsoleObject(StopCommand) != nullptr;
}

bool FVerseConsoleStreamDriver::RunCommand(const TCHAR* Command) const
{
	IConsoleObject* Object = IConsoleManager::Get().FindConsoleObject(Command);
	IConsoleCommand* Cmd = Object ? Object->AsCommand() : nullptr;
	if (Cmd == nullptr)
	{
		return false;
	}
	UWorld* World = GEngine ? GEngine->GetCurrentPlayWorld() : nullptr;
	return Cmd->Execute(TArray<FString>(), World, *GLog);
}

FVerseConsoleStreamDriver::FWindowState FVerseConsoleStreamDriver::CurrentWindow() const
{
	FWindowState State;
	State.ResX = GSystemResolution.ResX;
	State.ResY = GSystemResolution.ResY;
	State.Mode = GSystemResolution.WindowMode;
	return State;
}

void FVerseConsoleStreamDriver::RequestWindow(const FWindowState& State) const
{
	if (GEngine == nullptr)
	{
		return;
	}
	FSystemResolution::RequestResolutionChange(State.ResX, State.ResY, State.Mode);
}

void FVerseConsoleStreamDriver::ApplyRenderSize(FIntPoint RenderSize) const
{
	if (RenderSize.X <= 0 || RenderSize.Y <= 0)
	{
		return;
	}
	// The default streamer captures the back buffer, so the window renders at the panel's size.
	FWindowState Panel;
	Panel.ResX = RenderSize.X;
	Panel.ResY = RenderSize.Y;
	Panel.Mode = EWindowMode::Windowed;
	RequestWindow(Panel);
}

void FVerseConsoleStreamDriver::RestoreWindow()
{
	if (!bSavedWindow)
	{
		return;
	}
	bSavedWindow = false;
	// A headless or not yet sized window has nothing worth restoring.
	if (SavedWindow.ResX > 0 && SavedWindow.ResY > 0)
	{
		RequestWindow(SavedWindow);
	}
}

void FVerseConsoleStreamDriver::Start(const FVerseStreamConfig& Config, FOnStarted OnStarted)
{
	if (!IsAvailable())
	{
		OnStarted(false, VerseStream::ErrorStreamerUnavailable);
		return;
	}
	if (Config.SignalUrl.IsEmpty())
	{
		OnStarted(false, VerseStream::ErrorNoSignal);
		return;
	}
	for (const TPair<FString, FString>& Setting : SettingsFor(Config))
	{
		if (!SetVar(Setting.Key, Setting.Value))
		{
			UE_LOG(LogVerseStream, Verbose, TEXT("Panel stream: console variable %s not present"), *Setting.Key);
		}
	}
	if (IConsoleVariable* MaxFps = IConsoleManager::Get().FindConsoleVariable(TEXT("t.MaxFPS")))
	{
		if (!bSavedMaxFps)
		{
			SavedMaxFps = MaxFps->GetString();
			bSavedMaxFps = true;
		}
		MaxFps->Set(*FString::FromInt(Config.Fps), ECVF_SetByCode);
	}
	if (!bSavedWindow)
	{
		SavedWindow = CurrentWindow();
		bSavedWindow = true;
	}
	ApplyRenderSize(Config.RenderSize);
	if (!RunCommand(StartCommand))
	{
		Stop();
		OnStarted(false, VerseStream::ErrorStreamerUnavailable);
		return;
	}
	bStreaming = true;
	UE_LOG(LogVerseStream, Log, TEXT("Panel stream started at %dx%d, %d fps"), Config.RenderSize.X, Config.RenderSize.Y, Config.Fps);
	OnStarted(true, FString());
}

void FVerseConsoleStreamDriver::Stop()
{
	if (bStreaming)
	{
		RunCommand(StopCommand);
		bStreaming = false;
		UE_LOG(LogVerseStream, Log, TEXT("Panel stream stopped"));
	}
	if (bSavedMaxFps)
	{
		SetVar(TEXT("t.MaxFPS"), SavedMaxFps);
		bSavedMaxFps = false;
	}
	RestoreWindow();
	// Leave no signalling URL (it carries the streamer key) in the console variable.
	SetVar(UrlVar, FString());
}

void FVerseConsoleStreamDriver::Resize(FIntPoint RenderSize)
{
	if (bStreaming)
	{
		ApplyRenderSize(RenderSize);
	}
}

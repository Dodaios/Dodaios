#include "Lifecycle/VerseLifecycle.h"

#include "Bridge/VerseBridgeClient.h"
#include "Bridge/VerseBridgeCodec.h"
#include "HAL/PlatformTime.h"
#include "VerseLog.h"

using namespace VerseBridgeJson;

const TCHAR* LexToString(EVerseLifecycleState State)
{
	switch (State)
	{
	case EVerseLifecycleState::Booting: return TEXT("booting");
	case EVerseLifecycleState::Visible: return TEXT("visible");
	case EVerseLifecycleState::Panel: return TEXT("panel");
	case EVerseLifecycleState::Dormant: return TEXT("dormant");
	case EVerseLifecycleState::Exiting: return TEXT("exiting");
	}
	return TEXT("booting");
}

double IVerseLifecycleHost::Now() const
{
	return FPlatformTime::Seconds();
}

FVerseLifecycleController::FVerseLifecycleController(IVerseLifecycleHost& InHost, FVerseBridgeClient& InClient)
	: Host(InHost)
	, Client(InClient)
{
}

void FVerseLifecycleController::ReportState()
{
	TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetStringField(TEXT("state"), LexToString(State));
	Data->SetNumberField(TEXT("vram_mb"), FMath::Max(0, Host.VramMb()));
	Data->SetNumberField(TEXT("fps"), FMath::Max(0.f, Host.Fps()));
	Client.SendNotice(TEXT("lifecycle.state"), Data);
}

void FVerseLifecycleController::NotifyLinked()
{
	if (const TSharedPtr<FJsonObject> Welcome = Client.GetWelcome())
	{
		AppPid = int32(Int(Welcome, TEXT("app_pid")));
		ReturnKey = Str(Obj(Welcome, TEXT("settings")), TEXT("return_key"), ReturnKey);
		const TSharedPtr<FJsonObject> St = Obj(Welcome, TEXT("state"));
		bPanelVisible = Str(St, TEXT("panel")) == TEXT("visible");
		bGpuYield = Str(St, TEXT("gpu")) == TEXT("yield");
	}
	ReportState();
}

void FVerseLifecycleController::Enter(EVerseLifecycleState Next)
{
	if (State == EVerseLifecycleState::Exiting || Next == State)
	{
		return;
	}
	const EVerseLifecycleState Previous = State;
	State = Next;
	switch (Next)
	{
	case EVerseLifecycleState::Visible:
		Host.SetRendering(true);
		Host.SetMaxFps(0.f);
		Host.SetMuted(false);
		Host.SetPaused(bPaused);
		Host.SetLowScalability(bGpuYield);
		break;
	case EVerseLifecycleState::Panel:
		// Offscreen at panel size, decks only, no match (architecture 1.3).
		Host.HideWindow();
		Host.SetRendering(true);
		Host.SetMaxFps(30.f);
		Host.SetMuted(true);
		Host.SetPaused(true);
		break;
	case EVerseLifecycleState::Dormant:
		Host.HideWindow();
		Host.SetRendering(false);
		Host.SetMaxFps(2.f);
		Host.SetMuted(true);
		Host.SetPaused(true);
		break;
	case EVerseLifecycleState::Exiting:
	case EVerseLifecycleState::Booting:
		Host.SetRendering(false);
		Host.SetMuted(true);
		break;
	}
	UE_LOG(LogVerseBridge, Log, TEXT("lifecycle: %s -> %s"), LexToString(Previous), LexToString(Next));
	ReportState();
	OnStateChanged.Broadcast(Next);
}

void FVerseLifecycleController::HandleFrame(const FVerseBridgeFrame& F)
{
	const FString& T = F.Type;
	if (T == TEXT("welcome"))
	{
		NotifyLinked();
		return;
	}
	if (T == TEXT("lifecycle.show"))
	{
		const TSharedPtr<FJsonObject> M = Obj(F.Data, TEXT("monitor"));
		FVerseMonitor Monitor;
		if (M.IsValid())
		{
			Monitor.X = int32(Int(M, TEXT("x")));
			Monitor.Y = int32(Int(M, TEXT("y")));
			Monitor.W = int32(Int(M, TEXT("w"), 1920));
			Monitor.H = int32(Int(M, TEXT("h"), 1080));
			Monitor.Dpi = float(Num(M, TEXT("dpi"), 96.0));
		}
		ShowAt = Host.Now();
		Host.ShowWindow(Monitor, Str(F.Data, TEXT("activation_token")));
		Enter(EVerseLifecycleState::Visible);
		LastShowSeconds = Host.Now() - ShowAt;
		if (Str(F.Data, TEXT("reason")) == TEXT("quick_start_duel"))
		{
			OnQuickStartDuel.Broadcast();
		}
	}
	else if (T == TEXT("lifecycle.hide") || T == TEXT("focus.app_took"))
	{
		Enter(bPanelVisible ? EVerseLifecycleState::Panel : EVerseLifecycleState::Dormant);
	}
	else if (T == TEXT("lifecycle.pause") || T == TEXT("lifecycle.resume"))
	{
		bPaused = T == TEXT("lifecycle.pause");
		if (State == EVerseLifecycleState::Visible)
		{
			Host.SetPaused(bPaused);
			Host.SetMuted(bPaused);
		}
	}
	else if (T == TEXT("lifecycle.quit"))
	{
		Quit(Str(F.Data, TEXT("reason"), TEXT("app_quit")));
	}
	else if (T == TEXT("panel.visibility"))
	{
		bPanelVisible = Bool(F.Data, TEXT("visible"));
		if (bPanelVisible)
		{
			Host.ResizePanel(int32(Int(F.Data, TEXT("w"))), int32(Int(F.Data, TEXT("h"))), float(Num(F.Data, TEXT("dpr"), 1.0)));
			if (State != EVerseLifecycleState::Visible)
			{
				Enter(EVerseLifecycleState::Panel);
			}
		}
		else if (State == EVerseLifecycleState::Panel)
		{
			Enter(EVerseLifecycleState::Dormant);
		}
	}
	else if (T == TEXT("panel.resize"))
	{
		Host.ResizePanel(int32(Int(F.Data, TEXT("w"))), int32(Int(F.Data, TEXT("h"))), float(Num(F.Data, TEXT("dpr"), 1.0)));
	}
	else if (T == TEXT("gpu.yield"))
	{
		bGpuYield = true;
		if (State == EVerseLifecycleState::Dormant || State == EVerseLifecycleState::Booting)
		{
			Quit(TEXT("gpu_pressure"));
		}
		else
		{
			Host.SetLowScalability(true);
		}
	}
	else if (T == TEXT("gpu.free"))
	{
		bGpuYield = false;
		Host.SetLowScalability(false);
	}
	else if (T == TEXT("settings.changed"))
	{
		ReturnKey = Str(F.Data, TEXT("return_key"), ReturnKey);
	}
}

void FVerseLifecycleController::ReturnToApp(const FString& Reason)
{
	if (State != EVerseLifecycleState::Visible)
	{
		return;
	}
	// Order matters on Windows: allow the app to take the foreground, tell it, then hide.
	Host.AllowForeground(AppPid);
	TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetStringField(TEXT("reason"), Reason);
	Client.SendNotice(TEXT("focus.return_to_app"), Data);
	Enter(bPanelVisible ? EVerseLifecycleState::Panel : EVerseLifecycleState::Dormant);
}

void FVerseLifecycleController::NotifyFirstFrame(double MsSinceStart)
{
	if (bReady)
	{
		return;
	}
	bReady = true;
	TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetNumberField(TEXT("first_frame_ms"), FMath::RoundToDouble(MsSinceStart));
	Client.SendNotice(TEXT("lifecycle.ready"), Data);
}

void FVerseLifecycleController::Quit(const FString& Reason)
{
	if (State == EVerseLifecycleState::Exiting)
	{
		return;
	}
	OnQuitting.Broadcast(Reason);
	Enter(EVerseLifecycleState::Exiting);
	const bool bSaved = Host.SaveState();
	TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetBoolField(TEXT("saved"), bSaved);
	Client.SendNotice(TEXT("lifecycle.bye"), Data);
	Host.RequestExit();
}

void FVerseLifecycleController::LaunchOver()
{
	Quit(TEXT("launch_over"));
}

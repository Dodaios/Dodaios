#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class FVerseBridgeClient;
struct FVerseBridgeFrame;

/** Lifecycle states of Verse.exe (architecture.md 1.3; wire spelling lower case). */
enum class EVerseLifecycleState : uint8
{
	Booting,
	Visible,
	Panel,
	Dormant,
	Exiting,
};

VERSEBRIDGE_API const TCHAR* LexToString(EVerseLifecycleState State);

struct FVerseMonitor
{
	int32 X = 0;
	int32 Y = 0;
	int32 W = 1920;
	int32 H = 1080;
	float Dpi = 96.f;
};

/** What the lifecycle controller asks of the engine and the OS (faked in tests). */
class IVerseLifecycleHost
{
public:
	virtual ~IVerseLifecycleHost() = default;
	virtual void ShowWindow(const FVerseMonitor& Monitor, const FString& ActivationToken) = 0;
	virtual void HideWindow() = 0;
	virtual void SetRendering(bool bOn) = 0;
	/** The lifecycle frame cap; 0 = none (the person's limit and FVerseFramePacing rules apply). */
	virtual void SetMaxFps(float Fps) = 0;
	virtual void SetMuted(bool bMuted) = 0;
	virtual void SetPaused(bool bPaused) = 0;
	virtual void SetLowScalability(bool bLow) = 0;
	/** Windows AllowSetForegroundWindow; X11/Wayland hand-off on Linux. */
	virtual void AllowForeground(int32 Pid) = 0;
	/** Save match-free state (deck, position, settings); true when saved. */
	virtual bool SaveState() = 0;
	virtual void RequestExit() = 0;
	virtual void ResizePanel(int32 W, int32 H, float Dpr) {}
	virtual int32 VramMb() const { return 0; }
	virtual float Fps() const { return 0.f; }
	virtual double Now() const;
};

/**
 * The lifecycle state machine (WP17.12, bridge-protocol.md 12): Booting, Visible, Panel,
 * Dormant, Exiting. Applies lifecycle.*, panel.*, gpu.*, focus.app_took and settings.changed
 * from the backend; reports lifecycle.state on every change, lifecycle.ready after the first
 * frame, focus.return_to_app for the return key, lifecycle.bye on quit.
 */
class VERSEBRIDGE_API FVerseLifecycleController
{
public:
	FVerseLifecycleController(IVerseLifecycleHost& InHost, FVerseBridgeClient& InClient);

	/** Feed every server frame here (bound to FVerseBridgeClient::OnFrame). */
	void HandleFrame(const FVerseBridgeFrame& Frame);

	/** The return key (or a station, or the Esc menu): give the foreground back to the app. */
	void ReturnToApp(const FString& Reason = TEXT("return_key"));

	/** The first frame was presented; MsSinceStart is the process-relative time. */
	void NotifyFirstFrame(double MsSinceStart);

	/** The bridge said the launch is over (4401 on reconnect): save and quit. */
	void LaunchOver();

	/** The link came up: report the current state. */
	void NotifyLinked();

	EVerseLifecycleState GetState() const { return State; }
	bool IsPanelVisible() const { return bPanelVisible; }
	bool IsGpuYielded() const { return bGpuYield; }
	FString GetReturnKey() const { return ReturnKey; }
	int32 GetAppPid() const { return AppPid; }
	/** Seconds the last lifecycle.show took to reach Visible (-1 before one). */
	double GetLastShowSeconds() const { return LastShowSeconds; }

	/** lifecycle.show with reason quick_start_duel: the arena opens straight away. */
	TMulticastDelegate<void()> OnQuickStartDuel;
	/** Before the bye: send any pending duel.result (WP21 hooks here). */
	TMulticastDelegate<void(const FString& /*Reason*/)> OnQuitting;
	TMulticastDelegate<void(EVerseLifecycleState)> OnStateChanged;

private:
	void Enter(EVerseLifecycleState Next);
	void ReportState();
	void Quit(const FString& Reason);

	IVerseLifecycleHost& Host;
	FVerseBridgeClient& Client;
	EVerseLifecycleState State = EVerseLifecycleState::Booting;
	bool bPanelVisible = false;
	bool bGpuYield = false;
	bool bPaused = false;
	bool bReady = false;
	FString ReturnKey = TEXT("F10");
	int32 AppPid = 0;
	double ShowAt = -1.0;
	double LastShowSeconds = -1.0;
};

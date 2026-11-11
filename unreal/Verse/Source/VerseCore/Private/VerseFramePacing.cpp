#include "VerseFramePacing.h"

#include "Containers/Ticker.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformMisc.h"
#include "Misc/App.h"
#include "Misc/CoreMisc.h"
#include "Performance/LatencyMarkerModule.h"
#include "Performance/MaxTickRateHandlerModule.h"

#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <windows.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

namespace VerseFramePacingPrivate
{
	FVerseFramePacing::FUserLimit UserLimit;
	float LifecycleCap = 0.f;
	float StreamCap = 0.f;
	FTSTicker::FDelegateHandle TickHandle;

	/** Applying a few times a second is enough: focus and state changes are rare. */
	constexpr float TickInterval = 0.2f;
	/** The display is read again at most this often (a window can move to another monitor). */
	constexpr double DisplayReadInterval = 2.0;
	double LastDisplayRead = -1.0e9;
	float DisplayHz = 0.f;
	/** -1 unknown, 0 normal, 1 raised. */
	int32 PriorityRaised = -1;

	/**
	 * Above-normal priority while the person plays (foreground, no lifecycle or stream cap): other
	 * work on the PC (builds, agents) then preempts the game threads less. Measured on the
	 * packaged 1440p hangar deck view under background load: 1 % low 97 -> 177 fps.
	 */
	void SetRaisedPriority(bool bRaise)
	{
		if (PriorityRaised == int32(bRaise))
		{
			return;
		}
		PriorityRaised = int32(bRaise);
#if PLATFORM_WINDOWS
		::SetPriorityClass(::GetCurrentProcess(), bRaise ? ABOVE_NORMAL_PRIORITY_CLASS : NORMAL_PRIORITY_CLASS);
#endif
	}

	void Lower(float& Cap, float Candidate)
	{
		if (Candidate > 0.f && (Cap <= 0.f || Candidate < Cap))
		{
			Cap = Candidate;
		}
	}
}

float FVerseFramePacing::Resolve(const FInputs& In)
{
	float Cap = 0.f;
	if (In.User.bMatchDisplay)
	{
		VerseFramePacingPrivate::Lower(Cap, In.DisplayHz > 1.f ? In.DisplayHz : FallbackDisplayFps);
	}
	else
	{
		VerseFramePacingPrivate::Lower(Cap, In.User.Fps);
	}
	VerseFramePacingPrivate::Lower(Cap, In.LifecycleCap);
	VerseFramePacingPrivate::Lower(Cap, In.StreamCap);
	if (!In.bForeground)
	{
		VerseFramePacingPrivate::Lower(Cap, BackgroundFps);
	}
	return Cap;
}

void FVerseFramePacing::SetUserLimit(const FUserLimit& Limit)
{
	VerseFramePacingPrivate::UserLimit = Limit;
	VerseFramePacingPrivate::UserLimit.Fps = FMath::Max(0.f, Limit.Fps);
	Apply();
}

FVerseFramePacing::FUserLimit FVerseFramePacing::GetUserLimit()
{
	return VerseFramePacingPrivate::UserLimit;
}

void FVerseFramePacing::SetLifecycleCap(float Fps)
{
	VerseFramePacingPrivate::LifecycleCap = FMath::Max(0.f, Fps);
	Apply();
}

void FVerseFramePacing::SetStreamCap(float Fps)
{
	VerseFramePacingPrivate::StreamCap = FMath::Max(0.f, Fps);
	Apply();
}

void FVerseFramePacing::SetLowLatency(bool bEnabled)
{
	IModularFeatures& Features = IModularFeatures::Get();
	for (IMaxTickRateHandlerModule* Handler :
		Features.GetModularFeatureImplementations<IMaxTickRateHandlerModule>(IMaxTickRateHandlerModule::GetModularFeatureName()))
	{
		Handler->SetEnabled(bEnabled);
		// Flag 1: low-latency mode (Reflex "Enabled"); boost stays off, it only raises clocks.
		Handler->SetFlags(bEnabled ? 1u : 0u);
	}
	for (ILatencyMarkerModule* Markers :
		Features.GetModularFeatureImplementations<ILatencyMarkerModule>(ILatencyMarkerModule::GetModularFeatureName()))
	{
		Markers->SetEnabled(bEnabled);
	}
}

float FVerseFramePacing::ReadDisplayHz()
{
#if PLATFORM_WINDOWS
	// The foreground window is the Verse window whenever its limit matters (in the background
	// BackgroundFps is lower than any display).
	if (HWND Window = ::GetForegroundWindow())
	{
		if (HMONITOR Monitor = ::MonitorFromWindow(Window, MONITOR_DEFAULTTOPRIMARY))
		{
			MONITORINFOEXW Info;
			FMemory::Memzero(Info);
			Info.cbSize = sizeof(Info);
			if (::GetMonitorInfoW(Monitor, &Info))
			{
				DEVMODEW Mode;
				FMemory::Memzero(Mode);
				Mode.dmSize = sizeof(Mode);
				// 0 and 1 mean "the hardware default": unknown.
				if (::EnumDisplaySettingsW(Info.szDevice, ENUM_CURRENT_SETTINGS, &Mode) && Mode.dmDisplayFrequency > 1)
				{
					return float(Mode.dmDisplayFrequency);
				}
			}
		}
	}
#endif
	return float(FPlatformMisc::GetMaxRefreshRate());
}

void FVerseFramePacing::Apply()
{
	if (GIsEditor || !IsInGameThread())
	{
		return;
	}
	VerseFramePacingPrivate::SetRaisedPriority(
		FApp::HasFocus() && VerseFramePacingPrivate::LifecycleCap <= 0.f && VerseFramePacingPrivate::StreamCap <= 0.f);
	IConsoleVariable* Var = IConsoleManager::Get().FindConsoleVariable(TEXT("t.MaxFPS"));
	if (!Var)
	{
		return;
	}
	// A value from the console or the command line is a deliberate choice: leave it.
	if ((Var->GetFlags() & ECVF_SetByMask) > ECVF_SetByCode)
	{
		return;
	}
	FInputs In;
	In.User = VerseFramePacingPrivate::UserLimit;
	In.LifecycleCap = VerseFramePacingPrivate::LifecycleCap;
	In.StreamCap = VerseFramePacingPrivate::StreamCap;
	In.bForeground = FApp::HasFocus();
	if (In.User.bMatchDisplay && In.bForeground)
	{
		const double Now = FPlatformTime::Seconds();
		if (Now - VerseFramePacingPrivate::LastDisplayRead >= VerseFramePacingPrivate::DisplayReadInterval)
		{
			VerseFramePacingPrivate::LastDisplayRead = Now;
			VerseFramePacingPrivate::DisplayHz = ReadDisplayHz();
		}
	}
	In.DisplayHz = VerseFramePacingPrivate::DisplayHz;
	const float Want = Resolve(In);
	if (!FMath::IsNearlyEqual(Var->GetFloat(), Want, 0.01f))
	{
		Var->Set(Want, ECVF_SetByCode);
	}
}

void FVerseFramePacing::Start()
{
	if (GIsEditor || IsRunningCommandlet() || IsRunningDedicatedServer() || VerseFramePacingPrivate::TickHandle.IsValid())
	{
		return;
	}
	VerseFramePacingPrivate::TickHandle = FTSTicker::GetCoreTicker().AddTicker(
		FTickerDelegate::CreateLambda([](float)
		{
			Apply();
			return true;
		}),
		VerseFramePacingPrivate::TickInterval);
}

void FVerseFramePacing::Stop()
{
	if (VerseFramePacingPrivate::TickHandle.IsValid())
	{
		FTSTicker::GetCoreTicker().RemoveTicker(VerseFramePacingPrivate::TickHandle);
		VerseFramePacingPrivate::TickHandle.Reset();
	}
}

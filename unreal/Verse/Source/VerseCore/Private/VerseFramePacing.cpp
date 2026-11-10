#include "VerseFramePacing.h"

#include "Containers/Ticker.h"
#include "Engine/Engine.h"
#include "GameFramework/GameUserSettings.h"
#include "HAL/IConsoleManager.h"
#include "Misc/App.h"
#include "Misc/CoreMisc.h"

namespace VerseFramePacingPrivate
{
	float LifecycleCap = 0.f;
	float StreamCap = 0.f;
	bool bDuelRunning = false;
	FTSTicker::FDelegateHandle TickHandle;

	/** Applying a few times a second is enough: focus and state changes are rare. */
	constexpr float TickInterval = 0.2f;

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
	VerseFramePacingPrivate::Lower(Cap, In.UserLimit);
	VerseFramePacingPrivate::Lower(Cap, In.LifecycleCap);
	VerseFramePacingPrivate::Lower(Cap, In.StreamCap);
	if (!In.bDuelRunning)
	{
		VerseFramePacingPrivate::Lower(Cap, DeckFps);
	}
	if (!In.bForeground)
	{
		VerseFramePacingPrivate::Lower(Cap, BackgroundFps);
	}
	return Cap;
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

void FVerseFramePacing::SetDuelRunning(bool bRunning)
{
	VerseFramePacingPrivate::bDuelRunning = bRunning;
	Apply();
}

void FVerseFramePacing::Apply()
{
	if (GIsEditor || !IsInGameThread())
	{
		return;
	}
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
	if (GEngine)
	{
		if (const UGameUserSettings* User = GEngine->GetGameUserSettings())
		{
			In.UserLimit = User->GetFrameRateLimit();
		}
	}
	In.LifecycleCap = VerseFramePacingPrivate::LifecycleCap;
	In.StreamCap = VerseFramePacingPrivate::StreamCap;
	In.bDuelRunning = VerseFramePacingPrivate::bDuelRunning;
	In.bForeground = FApp::HasFocus();
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

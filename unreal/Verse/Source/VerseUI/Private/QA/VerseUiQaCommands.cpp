#include "QA/VerseUiQaCommands.h"

#include "Core/VerseUiSubsystem.h"
#include "Misc/App.h"
#include "Qa/VerseQaRegistry.h"
#include "Scalability.h"

namespace
{
	TWeakObjectPtr<UVerseUiSubsystem> GOwner;

	const TCHAR* QualityName(int32 Level)
	{
		switch (Level)
		{
		case 0: return TEXT("low");
		case 1: return TEXT("medium");
		case 2: return TEXT("high");
		case 3: return TEXT("epic");
		case 4: return TEXT("cinematic");
		default: return TEXT("custom");
		}
	}

	FString Stats(const TArray<FString>&)
	{
		// parity Q-01: {fps, frame_ms, tier, state}; hud_ms is the A18.3 game-thread number.
		const double Delta = FMath::Max(1e-6, FApp::GetDeltaTime());
		const int32 Level = Scalability::GetQualityLevels().GetSingleQualityLevel();
		const double HudMs = GOwner.IsValid() ? GOwner->GetHudCostMs() : 0.0;
		// Lifecycle as the bridge reports it (WP17 sets visible, panel, dormant; booting until welcome).
		const FString State = GOwner.IsValid() ? GOwner->GetLifecycleState().ToString() : FString(TEXT("booting"));
		return FString::Printf(TEXT("{\"fps\":%.1f,\"frame_ms\":%.2f,\"tier\":\"%s\",\"state\":\"%s\",\"hud_ms\":%.3f}"),
			1.0 / Delta, Delta * 1000.0, QualityName(Level), *State, HudMs);
	}
}

void VerseUiQa::RegisterCommands(UVerseUiSubsystem* Owner)
{
	GOwner = Owner;
	UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
	if (Registry && !Registry->IsRegistered(TEXT("Verse.QA.Stats")))
	{
		Registry->Register(TEXT("Verse.QA.Stats"), TEXT("Frame numbers: fps, frame_ms, tier, state, hud_ms"), &Stats);
	}
}

void VerseUiQa::Release(UVerseUiSubsystem* Owner)
{
	if (GOwner.Get() == Owner)
	{
		GOwner.Reset();
	}
}

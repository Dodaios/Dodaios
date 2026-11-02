#include "Adaptive/VerseBotAdaptiveController.h"

#include "Bot/VerseBotAdaptiveConfig.h"
#include "Bot/VerseBotTier.h"

void FVerseBotAdaptiveController::Reset(const UVerseBotAdaptiveConfig& InConfig)
{
	Config = &InConfig;
	Window.Reset();
	KillsSoFar = 0;
	Applied = FMath::Clamp(InConfig.StartSkill, 0.f, 1.f);
	Pending = Applied;
	Trace.Reset();
}

float FVerseBotAdaptiveController::GetWindowShare() const
{
	if (Window.Num() == 0)
	{
		return Config.IsValid() ? Config->TargetPersonShare : 0.5f;
	}
	int32 Person = 0;
	for (const bool bPerson : Window)
	{
		Person += bPerson ? 1 : 0;
	}
	return float(Person) / float(Window.Num());
}

void FVerseBotAdaptiveController::OnKill(bool bPersonKill)
{
	if (!Config.IsValid())
	{
		return;
	}
	++KillsSoFar;
	Window.Add(bPersonKill);
	const int32 WindowKills = FMath::Max(1, Config->WindowKills);
	if (Window.Num() > WindowKills)
	{
		Window.RemoveAt(0, Window.Num() - WindowKills, EAllowShrinking::No);
	}
	const float Share = GetWindowShare();
	Pending = Config->NextSkill(Pending, Share, KillsSoFar);

	FVerseBotAdaptiveTraceEntry Entry;
	Entry.Kill = KillsSoFar;
	Entry.bPersonKill = bPersonKill;
	Entry.WindowShare = Share;
	Entry.PendingSkill = Pending;
	Entry.AppliedSkill = Applied;
	Trace.Add(Entry);
}

bool FVerseBotAdaptiveController::OnBotRespawn()
{
	const bool bChanged = Pending != Applied;
	Applied = Pending;
	if (Trace.Num() > 0)
	{
		Trace.Last().AppliedSkill = Applied;
	}
	return bChanged;
}

void FVerseBotAdaptiveController::BuildTier(const UVerseBotTier& Normal, const UVerseBotTier& Hard, const UVerseBotTier& Elite, float S,
	UVerseBotTier& Out)
{
	UVerseBotAdaptiveConfig::InterpolateTier(Normal, Hard, Elite, S, Out);
}

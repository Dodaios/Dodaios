#include "Loading/VerseLoadingModel.h"

void FVerseLoadingModel::Begin(double Now, int32 Seed)
{
	Phase = EPhase::Showing;
	StartedAt = Now;
	FirstFrameAt = -1.0;
	FadeStartedAt = -1.0;
	GoneAt = -1.0;
	Tip = 1 + int32(uint32(FMath::Abs(Seed)) % uint32(NumTips));
}

void FVerseLoadingModel::NotifyFirstDeckFrame(double Now)
{
	if (Phase == EPhase::Showing && FirstFrameAt < 0.0)
	{
		FirstFrameAt = Now;
		Tick(Now);
	}
}

void FVerseLoadingModel::Tick(double Now)
{
	if (Phase == EPhase::Showing && FirstFrameAt >= 0.0)
	{
		const double Start = FMath::Max(FirstFrameAt, StartedAt + MinShowSeconds);
		if (Now >= Start)
		{
			Phase = EPhase::Leaving;
			FadeStartedAt = Start;
		}
	}
	if (Phase == EPhase::Leaving && Now >= FadeStartedAt + FadeSeconds)
	{
		Phase = EPhase::Gone;
		GoneAt = FadeStartedAt + FadeSeconds;
	}
}

float FVerseLoadingModel::Opacity(double Now) const
{
	switch (Phase)
	{
	case EPhase::Showing: return 1.f;
	case EPhase::Leaving: return float(FMath::Clamp(1.0 - (Now - FadeStartedAt) / FadeSeconds, 0.0, 1.0));
	default: return 0.f;
	}
}

float FVerseLoadingModel::GuessProgress(double ElapsedSeconds)
{
	return float(0.92 * (1.0 - FMath::Exp(-FMath::Max(0.0, ElapsedSeconds) / 2.2)));
}

float FVerseLoadingModel::Progress(double Now) const
{
	if (Phase == EPhase::Leaving || Phase == EPhase::Gone)
	{
		return 1.f;
	}
	return Phase == EPhase::Showing ? GuessProgress(Now - StartedAt) : 0.f;
}

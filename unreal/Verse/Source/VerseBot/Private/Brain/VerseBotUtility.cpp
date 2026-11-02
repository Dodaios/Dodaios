#include "Brain/VerseBotUtility.h"

void FVerseBotUtilitySelector::Reset(EVerseBotState Start, float NowS)
{
	CurrentState = Start;
	EnteredAtS = NowS;
}

void FVerseBotUtilitySelector::Force(EVerseBotState State, float NowS)
{
	CurrentState = State;
	EnteredAtS = NowS;
}

FVerseBotUtilitySelector::FDecision FVerseBotUtilitySelector::Decide(const float (&Utilities)[VerseBot::NumStates],
	const float (&Bonus)[VerseBot::NumStates], float UtilityNoise, bool bInterrupt, float NowS, FVerseRng& Rng)
{
	FDecision D;
	const int32 Cur = int32(CurrentState);
	int32 Best = -1;
	float BestScore = -1.0e9f;
	for (int32 i = 0; i < VerseBot::NumStates; ++i)
	{
		// One draw per state per decision, always, so the stream does not depend on which states run.
		const float Noise = float(Rng.Range(0.0, FMath::Max(UtilityNoise, 0.f)));
		if (Utilities[i] < 0.f)
		{
			D.Scores[i] = -1.0e9f;
			continue;
		}
		const float Score = Utilities[i] + Noise + Bonus[i] + (i == Cur ? Hysteresis : 0.f);
		D.Scores[i] = Score;
		if (Score > BestScore)
		{
			BestScore = Score;
			Best = i;
		}
	}
	const bool bDwelling = (NowS - EnteredAtS) < MinDwellS && !bInterrupt;
	const bool bCurrentRunnable = Utilities[Cur] >= 0.f;
	if (Best < 0 || (bDwelling && bCurrentRunnable))
	{
		D.State = CurrentState;
		return D;
	}
	D.State = EVerseBotState(Best);
	D.bChanged = D.State != CurrentState;
	if (D.bChanged)
	{
		CurrentState = D.State;
		EnteredAtS = NowS;
	}
	return D;
}

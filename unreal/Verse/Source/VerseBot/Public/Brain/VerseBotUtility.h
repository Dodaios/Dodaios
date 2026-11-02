#pragma once

#include "Brain/VerseBotTypes.h"
#include "CoreMinimal.h"
#include "VerseRng.h"

/**
 * Utility selection with hysteresis (bot.md 5): the current state gets +0.18, every state gets
 * U(0, UtilityNoise) per decision, a state is kept at least 0.4 s unless the decision is an
 * interrupt. Deterministic per RNG stream. The StateTree root (ST_VerseDuelBot) evaluates its
 * children's utility through this selector, so the rule lives in one place.
 */
class VERSEBOT_API FVerseBotUtilitySelector
{
public:
	static constexpr float Hysteresis = 0.18f;
	static constexpr float MinDwellS = 0.4f;

	struct FDecision
	{
		EVerseBotState State = EVerseBotState::Search;
		bool bChanged = false;
		/** Final scores (utility + hysteresis + noise + bonus), state order. */
		float Scores[VerseBot::NumStates] = {};
	};

	void Reset(EVerseBotState Start, float NowS);

	/**
	 * Picks a state. Utilities: base utility per state, state order; a negative value means the
	 * state cannot run. Bonus: per-state forced bonus for this decision (5.2). bInterrupt lifts the
	 * dwell. Noise draws come from Rng in state order, one per state, every decision.
	 */
	FDecision Decide(const float (&Utilities)[VerseBot::NumStates], const float (&Bonus)[VerseBot::NumStates],
		float UtilityNoise, bool bInterrupt, float NowS, FVerseRng& Rng);

	/** Force a state (own respawn: Search), restarting its dwell. */
	void Force(EVerseBotState State, float NowS);

	EVerseBotState Current() const { return CurrentState; }
	float EnteredS() const { return EnteredAtS; }

private:
	EVerseBotState CurrentState = EVerseBotState::Search;
	float EnteredAtS = 0.f;
};

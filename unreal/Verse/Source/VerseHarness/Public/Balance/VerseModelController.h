#pragma once

#include "Balance/VersePersonModels.h"
#include "Balance/VerseTrickOverrides.h"
#include "Bot/VersePerceptTypes.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameFramework/Controller.h"
#include "VerseRng.h"

#include "VerseModelController.generated.h"

/**
 * A person model in the balance harness (bot.md 11.1, 11.2; frozen interface): the same brain
 * as the bot with person parameters and optional trick overrides. It perceives only through
 * FVersePerceptFrame (fairness F6) and acts only through FVerseInputFrame (bot.md B1).
 *
 * Until VerseBot's FVerseBotBrainCore lands (WP08) the brain is the null brain: an empty input
 * frame every tick. SetBrain plugs the real one in without touching the model or trick layers.
 */
UCLASS()
class VERSEHARNESS_API AVerseModelController : public AController
{
	GENERATED_BODY()

public:
	using FBrain = TFunction<FVerseInputFrame(const FVersePerceptFrame&)>;

	AVerseModelController();

	virtual void PostInitializeComponents() override;

	void Configure(const FVersePersonModel& InModel, const FVerseTrickConfig& InTrick, uint32 InSeed);
	void SetBrain(FBrain InBrain);

	/** One server tick: brain, then reaction delay and turn-rate limit, then trick overrides. */
	FVerseInputFrame Think(const FVersePerceptFrame& Percepts, double NowS, float DeltaS);

	/** Forget everything learnt in the match (BG9: nothing carries over). */
	void ResetMatchMemory();

	const FVerseInputFrame& GetLastInput() const { return LastInput; }
	const FVersePersonModel& GetModel() const { return Model; }
	const FVerseTrickConfig& GetTrickConfig() const { return TrickConfig; }
	bool IsReacting(double NowS) const { return NowS < ReactUntilS; }

	/** Pure model layer, exposed for tests: delay and turn limit applied to a brain frame. */
	static FVerseInputFrame ApplyPersonLimits(const FVersePersonModel& Model, const FVerseInputFrame& Brain,
		bool bReacting, float DeltaS);

private:
	FVersePersonModel Model;
	FVerseTrickConfig TrickConfig;
	FVerseTrickState TrickState;
	FVerseRng Rng;
	uint32 Seed = 0;
	FBrain Brain;
	FVerseInputFrame LastInput;
	bool bSawLastTick = false;
	double ReactUntilS = 0.0;
};

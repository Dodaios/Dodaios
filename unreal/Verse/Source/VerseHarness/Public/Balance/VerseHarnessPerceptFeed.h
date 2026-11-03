#pragma once

#include "Bot/VersePerceptTypes.h"
#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "VerseHarnessPerceptFeed.generated.h"

class AController;
class UWorld;

DECLARE_MULTICAST_DELEGATE_TwoParams(FVerseHarnessPerceptFrameEvent, AController*, const FVersePerceptFrame&);

/**
 * The percept source of the harness person models until UVersePerceptionService lands (WP07,
 * VerseCombat). It has the frozen shape of that service (bot.md frozen interface):
 * RegisterObserver(AController*, const FVersePerceptionProfile&), UnregisterObserver and the
 * delegate OnPerceptFrame(AController*, const FVersePerceptFrame&), so the model controller
 * binds the real service without changing.
 *
 * It is a null perception: every server tick each observer gets a frame with the server time and
 * its own state (FVerseSelfPercept: what its own HUD shows) and no sighting, sound, bolt or hurt.
 * It never reports anything about another actor, so fairness F1 and F6 hold by construction.
 */
UCLASS()
class VERSEHARNESS_API UVerseHarnessPerceptFeed : public UObject
{
	GENERATED_BODY()

public:
	void RegisterObserver(AController* Observer, const FVersePerceptionProfile& Profile);
	void UnregisterObserver(AController* Observer);
	bool IsObserving(const AController* Observer) const;
	int32 NumObservers() const { return Observers.Num(); }

	/** One server tick: one frame per registered observer, in registration order. */
	void Tick(UWorld* World);

	/** The observer's own part of a frame (bot.md 3.3), exposed for tests. */
	static FVerseSelfPercept SelfOf(const AController& Observer);

	FVerseHarnessPerceptFrameEvent OnPerceptFrame;

private:
	TArray<TWeakObjectPtr<AController>> Observers;
};

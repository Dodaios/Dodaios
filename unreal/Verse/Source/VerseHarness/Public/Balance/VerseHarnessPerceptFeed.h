#pragma once

#include "Bot/VersePerceptTypes.h"
#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "VerseHarnessPerceptFeed.generated.h"

class AController;
class UWorld;
class UVersePerceptionService;

DECLARE_MULTICAST_DELEGATE_TwoParams(FVerseHarnessPerceptFrameEvent, AController*, const FVersePerceptFrame&);

/**
 * The percept source of the harness person models (bot.md 2, F6). It has the frozen shape of
 * UVersePerceptionService (RegisterObserver(AController*, const FVersePerceptionProfile&),
 * UnregisterObserver and OnPerceptFrame(AController*, const FVersePerceptFrame&)) and relays that
 * service: in a world that has it, every observer is registered with the service under its own
 * profile and receives exactly the frames a bot receives (sightings, sounds, bolts, hurt, HUD),
 * with all perception error applied by the service.
 *
 * Worlds without the service (fixture tests) fall back to a null perception: every Tick each
 * observer gets a frame with the server time and its own state and nothing about another actor.
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
	/** True when the observer's frames come from UVersePerceptionService (not the null fallback). */
	bool IsServed(const AController* Observer) const;

	/** Tests: use the null perception even where the world has the service. */
	void SetUseService(bool bInUse) { bUseService = bInUse; }

	/** One server tick: one null frame per observer the service does not serve, in registration order. */
	void Tick(UWorld* World);

	/** The observer's own part of a frame (bot.md 3.3), exposed for tests. */
	static FVerseSelfPercept SelfOf(const AController& Observer);

	FVerseHarnessPerceptFrameEvent OnPerceptFrame;

	virtual void BeginDestroy() override;

private:
	UVersePerceptionService* ServiceFor(const AController& Observer) const;
	void Bind(UVersePerceptionService& Service);
	void Unbind();
	void HandleServiceFrame(AController* Observer, const FVersePerceptFrame& Frame);

	TArray<TWeakObjectPtr<AController>> Observers;
	/** Observers registered with the service. */
	TArray<TWeakObjectPtr<AController>> Served;
	TWeakObjectPtr<UVersePerceptionService> BoundService;
	FDelegateHandle ServiceHandle;
	bool bUseService = true;
};

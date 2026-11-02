#pragma once

#include "Balance/VerseBoutRecorder.h"
#include "Balance/VerseHarnessScenario.h"
#include "Balance/VersePersonModels.h"
#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "VerseBalanceGauntletController.generated.h"

class AController;
class UWorld;
struct FVerseDeathEvent;
struct FVerseFireEvent;
struct FVerseGadgetEvent;
struct FVerseHitEvent;
struct FVerseReloadEvent;

/**
 * Drives one headless balance process (bot.md 11.1): both slots possessed on the dedicated
 * server, endless deathmatch cut into bouts (first to KillsToWin or MatchTimeLimitS of match
 * time), spawn sides alternating per bout, one verse.bout/1 line per bout in
 * <output>/bouts.jsonl and <output>/speed.json (x real time, RK1) when the scenario is done.
 *
 * Started by UVerseHarnessSubsystem from -VerseHarness=<scenario.json>. It is a plain UObject
 * driven by the subsystem's ticker, so it needs no Gauntlet plugin dependency; the Unreal
 * Gauntlet test node can wrap this process later without changing it.
 *
 * Bot slots spawn /Script/VerseBot.VerseBotController when that class exists (WP08) and fall
 * back to a null-brain AVerseModelController until then; speed.json names which one ran.
 */
UCLASS()
class VERSEHARNESS_API UVerseBalanceGauntletController : public UObject
{
	GENERATED_BODY()

public:
	bool Start(UWorld* InWorld, const FVerseHarnessScenario& InScenario, FString& OutError);

	/** One frame; returns false once the run finished and exit was requested. */
	bool Tick();

	bool IsFinished() const { return bFinished; }

private:
	void BeginUnit();
	void BeginBout();
	void EndBout();
	void Finish(const TCHAR* Why);
	AController* SpawnSlot(const FVerseHarnessSlot& Slot, uint32 SlotSeed);
	void ClearSlots();
	int32 PlayerIdOf(const AController* Controller) const;
	double Now() const;
	void ReadAdaptive();

	void HandleFire(const FVerseFireEvent& Event);
	void HandleHit(const FVerseHitEvent& Event);
	void HandleDeath(const FVerseDeathEvent& Event);
	void HandleReload(const FVerseReloadEvent& Event);
	void HandleGadget(const FVerseGadgetEvent& Event);

	TWeakObjectPtr<UWorld> World;
	FVerseHarnessScenario Scenario;
	FVersePersonModelSet PersonModels;
	int32 UnitIndex = -1;
	int32 BoutIndex = 0;
	double BoutStartS = 0.0;
	double MatchTimeS = 0.0;
	TUniquePtr<FVerseBoutRecorder> Recorder;
	TArray<TWeakObjectPtr<AController>> Slots;
	TArray<float> AdaptiveTrace;
	FString BoutsFile;
	FString BotControllerKind;
	double WallStartS = 0.0;
	double SimStartS = 0.0;
	double StartupS = 0.0;
	double SimTotalS = 0.0;
	int64 Ticks = 0;
	bool bFinished = false;
	TArray<FDelegateHandle> HubHandles;
};

#pragma once

#include "Balance/VerseBoutRecorder.h"
#include "Balance/VerseHarnessScenario.h"
#include "Balance/VersePersonModels.h"
#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "VerseBalanceGauntletController.generated.h"

class AController;
class UVerseBotTier;
class UVerseHarnessPerceptFeed;
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
 * Bot slots spawn /Script/VerseBot.VerseBotController when that class exists (WP08) and get
 * their tier through the frozen SetTier(const UVerseBotTier*) and SetAdaptive(bool) (the tier
 * asset is tiers.json start values plus the unit's tierPatch; learning off sets LearnWeightMax 0).
 * A bot class that cannot be configured fails the run. Until WP08 lands the slot falls back to a
 * null-brain AVerseModelController with the tier's person parameters; speed.json names which ran.
 *
 * Model slots observe through the percept feed (UVerseHarnessPerceptFeed, the stand-in for
 * UVersePerceptionService) and drive their pawns from it every server tick.
 *
 * Spawn sides: the controller picks one spawn pair per unit (two player starts tagged VerseSide0
 * and VerseSide1, else the first start by name and the start farthest from it, else two
 * harness transforms 20 m apart). Every bout respawns both pawns; slot A takes side BoutIndex % 2.
 * The bout line records the side slot A actually spawned on, measured from its pawn.
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

	/** True when the run ended on an error (a slot that could not be configured, a bad patch). */
	bool HasFailed() const { return bFailed; }
	const FString& GetEndReason() const { return EndReason; }

	/** Test hooks: the slot controllers, the spawn pair and the side slot A spawned on this bout. */
	AController* GetSlot(int32 Index) const { return Slots.IsValidIndex(Index) ? Slots[Index].Get() : nullptr; }
	const FTransform& GetSpawnTransform(int32 Side) const { return SpawnPair[Side & 1]; }
	int32 GetSpawnSideA() const { return SpawnSideA; }
	int32 GetBoutIndex() const { return BoutIndex; }
	UVerseHarnessPerceptFeed* GetPerceptFeed() const { return Feed; }
	void EndBoutForTest() { EndBout(); }

	/**
	 * A tier asset for a slot: start values of TierId (adaptive starts from normal), the patch
	 * (either {Field: value} for every tier or {tierId: {Field: value}}; field names are
	 * UVerseBotTier's), LearnWeightMax 0 when learning is off. Null with a reason on any error.
	 */
	static UVerseBotTier* MakeTier(UObject* Outer, FName TierId, bool bLearning, const FString& TierPatchJson, FString& OutError);

	/** A tier-based person model (trick models "base hard", bot stand-ins) from a tier asset. */
	static FVersePersonModel PersonFromTier(const UVerseBotTier& Tier, FName Name);

private:
	void BeginUnit();
	void BeginBout();
	void EndBout();
	void Finish(const TCHAR* Why);
	void Fail(const FString& Why);
	AController* SpawnSlot(const FVerseHarnessSlot& Slot, const FString& TierPatchJson, uint32 SlotSeed, FString& OutError);
	bool ConfigureBot(AController& Bot, const FVerseHarnessSlot& Slot, const FString& TierPatchJson, FString& OutError);
	void ResolveSpawnPair();
	void RespawnSlot(AController& Controller, const FTransform& Where);
	int32 MeasureSpawnSideA() const;
	double ServerMs() const;
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
	double BoutStartMs = 0.0;
	int32 SpawnSideA = 0;
	FTransform SpawnPair[2];
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
	bool bFailed = false;
	bool bWarnedNoSkill = false;
	FString EndReason;
	TArray<FDelegateHandle> HubHandles;

	UPROPERTY()
	TObjectPtr<UVerseHarnessPerceptFeed> Feed;

	/** Tier assets handed to bots and models of the current unit (kept alive for SetTier). */
	UPROPERTY()
	TArray<TObjectPtr<UVerseBotTier>> UnitTiers;
};

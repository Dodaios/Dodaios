#pragma once

#include "Audit/VerseBotFireAudit.h"
#include "Bot/VersePerceptTypes.h"
#include "Brain/VerseBotAimDriver.h"
#include "Brain/VerseBotBelief.h"
#include "Brain/VerseBotTypes.h"
#include "Brain/VerseBotUtility.h"
#include "Brain/VerseBotWorldQueries.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Learning/VerseBotMatchMemory.h"
#include "Tactics/VerseBotTactics.h"
#include "VerseRng.h"

class UVerseBotTier;

/**
 * The deterministic bot brain (bot.md B5, frozen interface): percept frame and world-query answers
 * in, one FVerseInputFrame out. No engine state is read: given the seed, the tier, the percept
 * stream and the query answers, the output is bit-identical (BR1). Runs on the server.
 *
 * Per tick: belief step (10 Hz, at once on a positive percept), learning update, reflexes, a
 * decision every DecisionMs x U(0.8, 1.2) or on a forced trigger (5.2), at most one scheduled EQS
 * query, the current state's tick, aim, the fire gate with the F4 audit, and the input frame.
 */
class VERSEBOT_API FVerseBotBrainCore
{
public:
	struct FConfig
	{
		uint64 Seed = 0;
		/** The bot's player id (kill feed). */
		int32 SelfId = 0;
		/** Learning on (7); the harness turns it off for the BG8 control run. */
		bool bLearning = true;
	};

	FVerseBotBrainCore();
	~FVerseBotBrainCore();

	/** Starts a match: tier copied by reference (must outlive the brain), RNG streams seeded, memory empty. */
	void Init(const UVerseBotTier& InTier, const FConfig& InConfig);

	/** Swap the tier (adaptive applies at respawn, 9.2). Memory is kept. */
	void SetTier(const UVerseBotTier& InTier);

	/** Replace the belief (WP07's grid) or aim (WP09's model); the brain owns them. */
	void SetBelief(TUniquePtr<IVerseBotBelief> InBelief);
	void SetAimDriver(TUniquePtr<IVerseBotAimDriver> InAim);

	/** One server tick. */
	FVerseInputFrame Think(const FVersePerceptFrame& Frame, IVerseBotWorldQueries& World);

	/** Match end (7.3): memory, belief, plan, audit dropped. */
	void ResetMatch();

	EVerseBotState GetState() const { return Selector.Current(); }
	FVerseBotPresentation GetPresentation() const;
	const FVerseBotFireAuditLog& GetFireAudit() const { return Audit; }
	FVerseBotFireAuditLog& GetFireAudit() { return Audit; }
	const FVerseBotMatchMemory& GetMemory() const { return *Memory; }
	FVerseBotMatchMemory& GetMemory() { return *Memory; }
	/** Use an external memory (UVerseBotMatchMemory of the controller); it must outlive the brain. */
	void UseMemory(FVerseBotMatchMemory& InMemory);
	const IVerseBotBelief& GetBelief() const { return *Belief; }
	int32 GetDecisionCount() const { return DecisionIndex; }
	/** Number of decisions per state since Init (presentation, harness). */
	const int32* GetStateCounts() const { return StateCounts; }
	/** Ticks the bot wanted to move but made no progress for 3 s (BG12 stuck events). */
	int32 GetStuckEvents() const { return StuckEvents; }

private:
	void BuildContext(const FVersePerceptFrame& Frame, IVerseBotWorldQueries& World);
	void UpdateLearning(const FVersePerceptFrame& Frame);
	bool ForcedTriggers(const FVersePerceptFrame& Frame, float (&Bonus)[VerseBot::NumStates]);
	void RunScheduledQuery();
	void Decide(bool bInterrupt, const float (&Bonus)[VerseBot::NumStates]);
	void Reflexes(FVerseBotIntent& Intent);
	void ApplyFireGate(FVerseBotIntent& Intent, const FVerseBotAimResult& Aim);
	FVerseInputFrame ToInput(const FVerseBotIntent& Intent, const FVerseBotAimResult& Aim, uint32 ServerTimeMs);
	void OnOwnDeath();
	void OnOwnRespawn();
	void TacticsVisibleReset();
	FVector NextWaypoint(const FVector& Target, bool bCrouch);

	const UVerseBotTier* Tier = nullptr;
	FConfig Config;
	TUniquePtr<IVerseBotBelief> Belief;
	TUniquePtr<IVerseBotAimDriver> Aim;
	FVerseBotMatchMemory OwnedMemory;
	FVerseBotMatchMemory* Memory = &OwnedMemory;
	FVerseBotFireAuditLog Audit;
	FVerseBotUtilitySelector Selector;
	FVerseBotTacticsMemory TacticsMem;
	FVerseBotQueryCache Cache;
	FVerseRng DecisionRng;
	FVerseRng TacticsRng;
	FVerseRng ReflexRng;

	// Per-tick context (valid inside Think).
	FVerseBotTacticsContext Ctx;
	FVerseBotBeliefSummary BeliefSummary;
	TArray<FVector> BeliefCellsScratch;
	TArray<FVector> Spawns;
	IVerseBotWorldQueries* WorldThisTick = nullptr;
	const FVersePerceptFrame* FrameThisTick = nullptr;
	FVerseSightPercept SightingThisTick;
	bool bSightingThisTick = false;
	FVerseHeardPercept LastHeard;
	float LastHeardS = -1.0e6f;

	// Timing
	float NowS = 0.f;
	float LastThinkS = -1.f;
	float NextDecisionS = 0.f;
	float NextBeliefStepS = 0.f;
	float LastBeliefStepS = 0.f;
	int32 DecisionIndex = 0;
	int32 StateCounts[VerseBot::NumStates] = {};

	// Triggers (5.2)
	bool bHadSighting = false;
	float LastSightingS = -1.0e6f;
	FVector LastSeenLocation = FVector::ZeroVector;
	uint32 LastSightPerceptId = 0;
	bool bWasAlive = false;
	int32 LastMagazine = -1;
	float LastHurtS = -1.0e6f;
	float AttackBonusUntilS = -1.f;
	bool bAcquiredPending = false;

	// EQS scheduler
	TArray<EVerseBotQuery, TInlineAllocator<2>> Pending;
	int32 QueryCursor = 0;

	// Path cache
	FVerseBotPath Path;
	FVector PathTarget = FVector(1.0e9);
	int32 PathIndex = 0;
	int32 PathDecision = -1;

	// Learning bookkeeping
	bool bInEngagement = false;
	float EngagementRangeCm = 0.f;
	float EngagementLastS = -1.0e6f;
	int32 LastPersonZone = INDEX_NONE;
	bool bFirstContactDone = false;

	// Health
	FVector StuckRef = FVector::ZeroVector;
	float StuckSinceS = 0.f;
	bool bStuckCounted = false;

	// Reflex state
	bool bAdsHeld = false;
	bool bFireHeld = false;
	uint32 PrevButtons = 0;
	int32 VisibleBurst = 0;
	float BurstRestUntilS = 0.f;
	bool bNewTargetForAim = false;
	FVector AimTarget = FVector::ZeroVector;
	bool bHasAimTarget = false;
	bool bChooseHead = false;
	bool bPistolRolled = false;
	bool bPistolChosen = false;
	bool bKnifeRolled = false;
	bool bKnifeChosen = false;
	bool bCoarseBelief = true;
	bool bSpawnsFetched = false;
	int32 StuckEvents = 0;
	float LastSightRecordS = -1.0e6f;
	float LastOpponentKillS = -1.0e6f;
};

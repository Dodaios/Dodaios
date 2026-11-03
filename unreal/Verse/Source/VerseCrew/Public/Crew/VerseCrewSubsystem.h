#pragma once

#include "Crew/VerseCrewDeck.h"
#include "Crew/VerseCrewFeeds.h"
#include "Crew/VerseCrewPlanner.h"
#include "Crew/VerseCrewPresentation.h"
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseCrewSubsystem.generated.h"

class AVerseCompanionDrone;
class AVerseCrewPawn;
class APlayerController;
class USkeletalMesh;
struct FVerseArenaSwitchEvent;

/**
 * A command crew life sends over the bridge: the message type and its data
 * (bridge-protocol.md 2). The bridge client (WP17) adds id and ts and sends it.
 */
using FVerseCrewCommandSink = TFunction<void(const FString& Type, const TSharedRef<FJsonObject>& Data)>;

/** Counters for tests, the duty sheet and the soak report. */
struct VERSECREW_API FVerseCrewStats
{
	int32 Spawned = 0;
	int32 Despawned = 0;
	int32 Arrivals = 0;
	int32 Resyncs = 0;
	int32 Replans = 0;
	/** Pawns that made no progress toward their goal for StuckSeconds. */
	int32 StuckEvents = 0;
	int32 CommandsSent = 0;
	int32 CommandsRateLimited = 0;
	double LastTickMs = 0.0;
	double MaxTickMs = 0.0;
	double TotalTickMs = 0.0;
	int64 Ticks = 0;
	/** Walks that follow a Recast path. */
	int32 NavPaths = 0;
	/** Walks on a straight line because no nav path was found (the line was clear). */
	int32 NavFallbacks = 0;
	/** No nav path and the straight line runs into geometry: the pawn is placed at its goal. */
	int32 NavBlocked = 0;
	/** Walks planned while the world had no navmesh at all. */
	int32 NavMissing = 0;
	/** Walkers that were jammed for YieldSeconds and squeezed past the crowd. */
	int32 CrowdYields = 0;
	/** Pawns taken from the pool instead of spawned. */
	int32 PoolReuses = 0;
	/** Costliest single work item of each kind, ms (wall clock). */
	double MaxPlanDeckMs = 0.0;
	double MaxSpawnMs = 0.0;
	double MaxPathMs = 0.0;
	/** Most queued work items at once, and ticks that ended with work still queued. */
	int32 PeakQueuedWork = 0;
	int64 TicksWithBacklog = 0;
};

/**
 * Crew and daily life (WP15): officers (society agents) and technicians (coding panes) as
 * pawns on the decks, from the roster, groups, meetings and companion topics of
 * verse.bridge/1. Pure planning lives in VerseCrewPlanner; this subsystem turns plans into
 * walking, sitting, sleeping pawns, reports walk_together and team_briefing, hides the crew
 * from the arena and turns clicks into agent.open / pane.open.
 *
 * Inputs: HandleBridgeFrame (every server frame of the crew topics, as the bridge client
 * receives it), RegisterDeck / SetLoadedDecks / SetCommanderDeck (VerseDecks), the arena
 * switch on UVerseEventHub. Output: SetCommandSink.
 */
UCLASS()
class VERSECREW_API UVerseCrewSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseCrewSubsystem* Get(const UObject* WorldContextObject);

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;
	virtual void Tick(float DeltaSeconds) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override { return bAutoTick; }

	// --- bridge in -------------------------------------------------------------------------
	/** One server frame (JSON text). Returns false when it was not a crew frame or malformed. */
	bool HandleBridgeFrame(const FString& JsonText);
	bool HandleBridgeObject(const TSharedRef<FJsonObject>& Frame);

	// --- bridge out ------------------------------------------------------------------------
	void SetCommandSink(FVerseCrewCommandSink InSink) { Sink = MoveTemp(InSink); }

	// --- decks -----------------------------------------------------------------------------
	void RegisterDeck(const FVerseCrewDeck& Deck);
	/** The decks whose crew is spawned (normally the one on screen). */
	void SetLoadedDecks(const TArray<FName>& DeckIds);
	/** The deck the commander is on (team_briefing needs the bridge). */
	void SetCommanderDeck(FName DeckId);
	/** Registers the WP15 fixture decks (until WP12's placement files land). */
	bool RegisterFixtureDecks(const TMap<FName, FVector>& OriginsCm, FString& OutError);
	const FVerseCrewDeck* FindDeck(FName DeckId) const { return Decks.Find(DeckId); }

	// --- commander -------------------------------------------------------------------------
	/** Tests and the harness drive the commander directly; unset uses the first player pawn. */
	void SetCommanderOverride(TOptional<FVector> Location, float HeadingDeg = 0.f);
	FVector GetCommanderLocation() const;

	// --- arena -----------------------------------------------------------------------------
	void HandleArenaSwitch(const FVerseArenaSwitchEvent& Event);
	bool IsArenaOn() const { return bArenaOn; }
	FBox ArenaBoundsWorld() const;

	// --- interaction (15.8) ----------------------------------------------------------------
	/** First click selects, a second click on the same member opens it in the app. */
	bool ClickMember(const FString& MemberId);
	bool ClickActor(const AActor* Actor);
	/** Picks the crew member under the cursor (never one behind a wall). */
	bool ClickUnderCursor(APlayerController* Controller);
	void ClearSelection();
	const FString& GetSelected() const { return SelectedId; }

	// --- QA --------------------------------------------------------------------------------
	/** Verse.QA.SetDuty: force a member's duty; Unset releases it (parity C-24). */
	void SetDutyOverride(const FString& MemberId, TOptional<EVerseCrewDuty> Duty);
	/** Pose and status of every crew pawn, for Verse.QA.Dump and the duty sheet. */
	TSharedRef<FJsonObject> DumpJson() const;

	// --- state for tests and the duty sheet -------------------------------------------------
	const FVerseCrewRoster& GetRoster() const { return Roster; }
	const FVerseCrewMeetings& GetMeetings() const { return Meetings; }
	const FVerseCrewCompanion& GetCompanion() const { return Companion; }
	const FVerseCrewPresentation& GetPresentation() const { return Presentation; }
	const FVerseCrewTuning& GetTuning() const { return Tuning; }
	FVerseCrewTuning& MutableTuning() { return Tuning; }
	const FVerseCrewStats& GetStats() const { return Stats; }
	FVerseCrewStats& MutableStats() { return Stats; }
	const FVerseCrewWalkTogether& GetWalkTogether() const { return WalkTogether; }
	AVerseCrewPawn* FindPawn(const FString& MemberId) const;
	TArray<AVerseCrewPawn*> GetPawns() const;
	AVerseCompanionDrone* GetDrone() const;
	const FVerseCrewDeckPlan* FindPlan(FName DeckId) const { return Plans.Find(DeckId); }
	bool IsArriving(const FString& MemberId) const;
	/** Seconds on the crew clock (sum of Tick deltas). */
	double GetClockSeconds() const { return ClockSeconds; }
	/** The planner's wall clock in ms (epoch at Initialize plus the crew clock). */
	int64 GetNowMs() const;
	void SetEpochMs(int64 EpochMs) { BaseEpochMs = EpochMs; }
	/** Off: the world tick no longer drives the subsystem (tests call Tick themselves). */
	void SetAutoTick(bool bInAutoTick) { bAutoTick = bInAutoTick; }
	/** Re-plans now and does all queued work at once, outside the tick budget (tests, QA). */
	void ReplanNow();
	/** Queued work items (deck plans, spawns, path queries, retirements); 0 when idle. */
	int32 NumQueuedWork() const;

	// --- navigation ------------------------------------------------------------------------
	/** True when the world has a navmesh to walk on. */
	bool HasNavigation() const;
	/**
	 * Recast path between two points at capsule centre height (cm), both ends projected onto
	 * the navmesh within Tuning.NavProjectExtentCm. OutPoints starts at From's projection and
	 * ends at To's. False when there is no navmesh or no path.
	 */
	bool FindNavPath(const FVector& FromCm, const FVector& ToCm, TArray<FVector>& OutPoints) const;
	/** FindNavPath that also says why it failed (start or goal off the navmesh, no path, partial path). */
	bool FindNavPathWhy(const FVector& FromCm, const FVector& ToCm, TArray<FVector>& OutPoints, const TCHAR*& OutReason) const;
	/**
	 * Tests and QA: a pawn outside the roster that walks from Start to Goal (capsule centre
	 * height) with the crew's avoidance and stays there. Planning never touches it.
	 */
	bool SpawnScriptedWalker(const FString& Id, FName Deck, const FVector& StartCm, const FVector& GoalCm);
	/** Whether a pawn has reached its goal (false when there is no such pawn). */
	bool HasArrived(const FString& MemberId) const;

private:
	enum class EGoal : uint8
	{
		Socket,
		/** Walk to the lift and vanish (leavers, parity C-15). */
		Leave,
		/** A new agent walking from the shuttle to the lift (parity C-13). */
		Arrive,
		/** A test or QA walker outside the roster (SpawnScriptedWalker). */
		Scripted,
	};

	struct FBody
	{
		TWeakObjectPtr<AVerseCrewPawn> Pawn;
		FString MemberId;
		FName Deck;
		EGoal Goal = EGoal::Socket;
		FString SocketKey;
		FVector GoalLocation = FVector::ZeroVector;
		float GoalHeading = 0.f;
		EVerseCrewActivity GoalActivity = EVerseCrewActivity::StandRest;
		bool bFaceCommander = false;
		TArray<FVector> Path;
		int32 PathIndex = 0;
		bool bArrived = false;
		float PaceCmS = 130.f;
		float BestDistanceCm = TNumericLimits<float>::Max();
		double LastProgressSeconds = 0.0;
		bool bStuckReported = false;
		FVector Velocity = FVector::ZeroVector;
		/** Squeezing past a jam (counted once per jam in Stats.CrowdYields). */
		bool bYielding = false;
		/** Waiting in the spawn queue: no pawn yet, appears at SpawnLocation. */
		bool bSpawnPending = false;
		FVector SpawnLocation = FVector::ZeroVector;
		float SpawnHeading = 0.f;
		/** Waiting in the path queue: the pawn stands until its path is computed. */
		bool bPathPending = false;
		/** Bumped on every new goal; a queued path query for an older goal is dropped. */
		uint32 GoalSerial = 0;
		/** Scripted walkers carry their own member record. */
		TOptional<FVerseCrewMember> ScriptedMember;
	};

	struct FPathJob
	{
		FString Key;
		uint32 Serial = 0;
	};

	static FString BodyKey(FName Deck, const FString& MemberId);

	void HandleRoster(const FString& Type, const TSharedRef<FJsonObject>& Frame, const TSharedRef<FJsonObject>& Data);
	void HandleGroups(const FString& Type, const TSharedRef<FJsonObject>& Frame, const TSharedRef<FJsonObject>& Data);
	void HandleAwarded(const TSharedRef<FJsonObject>& Data);
	/** Sequence rule of bridge-protocol.md 1: a delta whose base is not the last frame of its topic asks for resync. */
	bool AcceptSequenced(const FString& Topic, const TSharedRef<FJsonObject>& Frame, bool bSnapshot);
	void RequestResync(const FString& Topic);

	TArray<FVerseCrewMember> EffectiveMembers() const;
	bool EffectiveMember(const FString& Id, FVerseCrewMember& Out) const;
	/** Starts a plan pass: every loaded deck goes into the plan queue. */
	void BeginPlanPass();
	void PlanDeck(FName DeckId);
	void FinishPlanPass();
	/** Runs queued work until the budget (ms since TickStart) is used; at least one item. */
	void RunQueuedWork(double TickStartSeconds, double BudgetMs);
	/** One queued work item; false when nothing was queued. */
	bool RunOneWorkItem();
	/** The kind of the next work item (0 duties, 1 plan, 2 spawn from the pool, 3 path, 4 pool trim, 5 new pooled actor), INDEX_NONE when idle. */
	int32 NextWorkKind() const;
	void SpawnBodyNow(const FString& Key);
	void BuildPathNow(const FString& Key, uint32 Serial);
	void ReconcileDeck(const FVerseCrewDeck& Deck, const FVerseCrewDeckPlan& Plan, const TArray<FVerseCrewMember>& Members);
	void ReconcileArrivals(const TArray<FVerseCrewMember>& Members);
	AVerseCrewPawn* SpawnPawn(const FVerseCrewMember& Member, const FVector& Location, float HeadingDeg);
	/** A new hidden pawn wearing the body mesh, for the pool. */
	AVerseCrewPawn* NewPooledPawn();
	/** Queues a body for its pawn; the body exists at once, its pawn when the queue gets to it. */
	FBody& AddBody(const FString& Key, const FString& MemberId, FName Deck, const FVector& Location, float HeadingDeg);
	/** Removes the body; its pawn is hidden and kept for reuse (or destroyed past the pool size). */
	void DespawnBody(const FString& Key);
	void SetBodyGoal(FBody& Body, EGoal Goal, const FVector& Location, float HeadingDeg, EVerseCrewActivity Activity, bool bFace, const FString& SocketKey);
	void BuildPath(FBody& Body, const FVector& From);
	/** True when a capsule moved from From to To hits no static geometry. */
	bool StraightLineClear(const FVector& From, const FVector& To) const;
	void StepBodies(float DeltaSeconds);
	void StepCompanion(float DeltaSeconds);
	void StepWorldActions();
	void RefreshDuties(const TArray<FVerseCrewMember>& Members);
	void HideCrewInArena();
	FVector ClampOutOfArena(FName Deck, const FVector& Location) const;
	TSet<FString> BlockedSockets(const FVerseCrewDeck& Deck) const;
	bool SendCommand(const FString& Type, const TSharedRef<FJsonObject>& Data, bool bOpenCommand = false);
	void SendWorldAction(const FString& Action, const FString& Ref);
	USkeletalMesh* BodyMesh();

	FVerseCrewRoster Roster;
	FVerseCrewMeetings Meetings;
	FVerseCrewCompanion Companion;
	FVerseCrewWalkTogether WalkTogether;
	FVerseCrewPresentation Presentation;
	FVerseCrewTuning Tuning;
	FVerseCrewStats Stats;

	TMap<FName, FVerseCrewDeck> Decks;
	TArray<FName> LoadedDecks;
	TSet<FName> DecksPlannedOnce;
	FName CommanderDeck;
	TMap<FName, FVerseCrewDeckPlan> Plans;
	TMap<FName, TMap<FString, FString>> PreviousKeys;
	TMap<FString, FBody> Bodies;
	TMap<FString, double> ArrivingUntil;
	TMap<FString, EVerseCrewDuty> DutyOverrides;
	TMap<FString, int64> LastSeq;
	TArray<double> OpenCommandTimes;
	TSet<FString> Briefed;

	// Queued work (A15.5): plan one deck, spawn one pawn, one path query at a time.
	TArray<FName> PlanQueue;
	TArray<FVerseCrewMember> PassMembers;
	TMap<FString, EVerseCrewRoundPart> PassRounds;
	int64 PassNowMs = 0;
	TArray<FString> SpawnQueue;
	TArray<FPathJob> PathQueue;
	int32 PathQueueHead = 0;
	int32 SpawnQueueHead = 0;
	bool bDutiesDirty = false;
	/** Recent worst cost per work kind, ms; start values until measured. */
	double PredictedCostMs[6] = { 0.05, 0.2, 0.15, 0.1, 0.1, 0.5 };
	int32 DeferredFrames = 0;
	bool bNavMissingLogged = false;
	int32 NavWarnings = 0;

	UPROPERTY(Transient)
	TArray<TObjectPtr<AVerseCrewPawn>> PawnPool;

	UPROPERTY(Transient)
	TObjectPtr<USkeletalMesh> CachedBodyMesh;
	bool bBodyMeshTried = false;

	UPROPERTY(Transient)
	TObjectPtr<AVerseCompanionDrone> Drone;

	FVerseCrewCommandSink Sink;
	FString SelectedId;
	TOptional<FVector> CommanderOverride;
	float CommanderHeadingDeg = 0.f;
	FDelegateHandle ArenaHandle;
	double ClockSeconds = 0.0;
	double LastReplanSeconds = -1.0e9;
	double LastWorldActionSeconds = 0.0;
	double SaluteUntilSeconds = -1.0;
	int64 BaseEpochMs = 0;
	bool bPlanDirty = false;
	bool bArenaOn = false;
	bool bAutoTick = true;
};

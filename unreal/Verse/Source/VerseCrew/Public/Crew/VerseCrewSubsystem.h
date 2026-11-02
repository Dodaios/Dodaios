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
	/** Re-plans now instead of at the next tick. */
	void ReplanNow();

private:
	enum class EGoal : uint8
	{
		Socket,
		/** Walk to the lift and vanish (leavers, parity C-15). */
		Leave,
		/** A new agent walking from the shuttle to the lift (parity C-13). */
		Arrive,
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
	};

	static FString BodyKey(FName Deck, const FString& MemberId);

	void HandleRoster(const FString& Type, const TSharedRef<FJsonObject>& Frame, const TSharedRef<FJsonObject>& Data);
	void HandleGroups(const FString& Type, const TSharedRef<FJsonObject>& Frame, const TSharedRef<FJsonObject>& Data);
	void HandleAwarded(const TSharedRef<FJsonObject>& Data);
	/** Sequence rule of bridge-protocol.md 1: a delta whose base is not the last frame of its topic asks for resync. */
	bool AcceptSequenced(const FString& Topic, const TSharedRef<FJsonObject>& Frame, bool bSnapshot);
	void RequestResync(const FString& Topic);

	TArray<FVerseCrewMember> EffectiveMembers() const;
	void Replan();
	void ReconcileDeck(const FVerseCrewDeck& Deck, const FVerseCrewDeckPlan& Plan, const TArray<FVerseCrewMember>& Members);
	void ReconcileArrivals(const TArray<FVerseCrewMember>& Members);
	AVerseCrewPawn* SpawnPawn(const FVerseCrewMember& Member, const FVector& Location, float HeadingDeg);
	void DespawnBody(const FString& Key);
	void SetBodyGoal(FBody& Body, EGoal Goal, const FVector& Location, float HeadingDeg, EVerseCrewActivity Activity, bool bFace, const FString& SocketKey);
	void BuildPath(FBody& Body, const FVector& From);
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

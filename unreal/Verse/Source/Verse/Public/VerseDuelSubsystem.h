#pragma once

#include "Bot/VersePerceptTypes.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseDuelSubsystem.generated.h"

class AController;
class APawn;
class AVerseBotController;

/** Per-player numbers of one duel, from the hub events (stats and the scripted runs). */
struct VERSE_API FVerseDuelPlayerStats
{
	int32 PlayerId = INDEX_NONE;
	FString Name;
	bool bBot = false;
	int32 Kills = 0;
	int32 Deaths = 0;
	int32 Headshots = 0;
	int32 Finishers = 0;
	int32 KnifeKills = 0;
	int32 GadgetKills = 0;
	int32 Shots = 0;
	int32 Hits = 0;
};

/** Frame time numbers of a run (rendered or headless). */
struct VERSE_API FVerseDuelFrameStats
{
	int32 Frames = 0;
	double SumS = 0.0;
	double WorstS = 0.0;
	TArray<float> Samples;

	void Add(float DeltaS);
	double AverageFps() const { return SumS > 0.0 ? Frames / SumS : 0.0; }
	/** Fps of the 1 % slowest frames. */
	double OnePercentLowFps() const;
};

/**
 * The hangar duel of the integration (orchestration.md 2.2): the endless 1v1 deathmatch against the
 * bot, wired end to end in the primary module because it touches VerseBot, VerseCombat, VerseDecks
 * and VerseUI, which may not include each other.
 *
 * - StartDuel spawns the bot (tier normal, hard, elite or adaptive), then asks the hangar switch
 *   for the arena; the game mode starts the deathmatch on the switch event and the ruleset spawns
 *   both players and respawns them 3 s after a death.
 * - Bots get their percept frames from UVersePerceptionService (registration, the frame hand-off,
 *   and the self and body fillers for health, magazines, gadgets, ADS and reloads).
 * - The UI's game port and HUD source are replaced by ones that know the duel and the inventory.
 * - Command line (non-shipping): -VerseDuel[=tier] starts a duel after the hangar arrived;
 *   -VerseDuelBots makes it bot vs bot with the person spectating bot A; -VerseDuelAutoplay drives
 *   the person's pawn with the scripted player; -VerseDuelSeconds=<s> ends the run after that much
 *   match time and writes -VerseDuelStats=<file> (JSON), then quits.
 */
UCLASS()
class VERSE_API UVerseDuelSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseDuelSubsystem* Get(const UObject* WorldContextObject);

	/** Server: starts (or restarts) the duel against a bot of Tier; false when it cannot. */
	bool StartDuel(FName Tier);
	/** Server: back to the day hangar; the bots leave. */
	void LeaveDuel();
	bool IsDuelRunning() const { return bDuelRunning; }
	FName GetTier() const { return Tier; }

	/** Bot vs bot: the person does not play and spectates bot A. Set before StartDuel. */
	void SetBotVsBot(bool bOn) { bBotVsBot = bOn; }
	bool IsBotVsBot() const { return bBotVsBot; }
	/** The scripted player drives the person's pawn on every spawn. */
	void SetAutoplay(bool bOn) { bAutoplay = bOn; }
	bool IsAutoplay() const { return bAutoplay; }

	const TMap<int32, FVerseDuelPlayerStats>& GetPlayerStats() const { return Players; }
	const FVerseDuelFrameStats& GetFrameStats() const { return Frames; }
	/** Match time since StartDuel, s. */
	double GetMatchSeconds() const;
	int32 GetErrorsSeen() const { return ErrorsSeen; }
	/** The stats as JSON (verse.duel_stats/1). */
	FString StatsJson() const;
	/** Resets the counters (a scripted run measures one stretch). */
	void ResetStats();

	/** The pawn the camera follows in bot vs bot (bot A), or the person's pawn. */
	APawn* GetFocusPawn() const;

	// UTickableWorldSubsystem
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Tick(float DeltaTime) override;
	/** The end-of-set screen pauses the match; scripted runs still continue it. */
	virtual bool IsTickableWhenPaused() const override { return true; }
	virtual TStatId GetStatId() const override;

private:
	AVerseBotController* SpawnBot(FName BotTier, int32 Index);
	void DestroyBots();
	void WirePerception();
	void RegisterObservers();
	void HandlePercept(AController* Observer, const FVersePerceptFrame& Frame);
	void HandleDeath(const FVerseDeathEvent& Event);
	void HandleFire(const FVerseFireEvent& Event);
	void HandleHit(const FVerseHitEvent& Event);
	void InstallUiPorts();
	/** The hangar deck stands in the dressed hall from its first frame (the duel adds the arena). */
	void HandleDeckArrived(FName Deck, bool bByLift);
	void BuildHallIfOnHangar();
	/** Puts the Sovereign skin on the deck commander. */
	void DressCommander();
	void ReadCommandLine();
	void UpdatePerson();
	void Spectate();
	FVerseDuelPlayerStats& StatsFor(int32 PlayerId);
	void FinishRun();
	/** Logs whether the nav mesh connects the two duellists (the bot and the scripted player walk it). */
	void LogNavCheck() const;

	TArray<TWeakObjectPtr<AVerseBotController>> Bots;
	TArray<TWeakObjectPtr<AController>> Observers;
	TWeakObjectPtr<APawn> AutoplayPawn;
	TMap<int32, FVerseDuelPlayerStats> Players;
	FVerseDuelFrameStats Frames;
	FName Tier = TEXT("hard");
	bool bDuelRunning = false;
	bool bBotVsBot = false;
	bool bAutoplay = false;
	bool bPerceptionWired = false;
	int32 NavChecks = 0;
	double EndOfSetSinceS = -1.0;
	int32 SetsContinued = 0;
	double MatchStartedAt = 0.0;
	int32 ErrorsSeen = 0;

	// Command-line run.
	bool bStartRequested = false;
	double StartAtWorldS = -1.0;
	double RunSeconds = 0.0;
	FString StatsFile;
	bool bRunFinished = false;

	FDelegateHandle DeathHandle;
	FDelegateHandle FireHandle;
	FDelegateHandle HitHandle;
	FDelegateHandle PerceptHandle;
	FDelegateHandle DeckArrivedHandle;
};

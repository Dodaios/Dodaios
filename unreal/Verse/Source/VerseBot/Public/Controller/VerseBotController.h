#pragma once

#include "Bot/VersePerceptTypes.h"
#include "Brain/VerseBotBrainCore.h"
#include "Brain/VerseBotTypes.h"
#include "Brain/VerseBotWorldQueries.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameFramework/Controller.h"

#include "VerseBotController.generated.h"

class UVerseBotMatchMemory;
class UVerseBotTier;

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseBotInputFrame, const FVerseInputFrame&);

/**
 * The duel bot (bot.md B1, frozen interface). Possesses an ordinary AVerseCharacter on the server
 * and acts only through FVerseInputFrame, the input a person produces: the frame drives the pawn's
 * movement input and control rotation, and OnInputFrame hands the buttons to the pawn's input
 * consumer (the "virtual input device", architecture 3.4). It reads the world only through the
 * percept frames the perception service delivers (ReceivePerceptFrame) and the world queries.
 *
 * Writes BotTier and BotEffectiveSkill into its own player state (combat-state.md 2.1).
 */
UCLASS()
class VERSEBOT_API AVerseBotController : public AController
{
	GENERATED_BODY()

public:
	AVerseBotController();
	virtual ~AVerseBotController() override;

	/** Tier for the next life; resets the match memory when the tier changes (7.3). */
	void SetTier(const UVerseBotTier* InTier);
	/** Adaptive mode (9.2); resets the match memory when it changes. */
	void SetAdaptive(bool bInAdaptive);
	bool IsAdaptive() const { return bAdaptive; }
	/** Adaptive s in [0, 1]; for a fixed tier 0 (normal), 0.5 (hard) or 1 (elite). */
	float GetEffectiveSkill() const { return EffectiveSkill; }
	/** WP09's adaptive controller sets the next s; it is applied at the next own respawn. */
	void SetPendingSkill(float S);
	/** Presentation only: state, cover spot, peek point. */
	FVerseBotPresentation GetPresentation() const;

	/** The perception service's OnPerceptFrame for this observer lands here. */
	void ReceivePerceptFrame(const FVersePerceptFrame& Frame);

	/** Match end (7.3): duel exit, arena off, tier or mode change, Verse.exe exit. */
	void ResetMatch();

	/** The input frame of the last tick. */
	const FVerseInputFrame& GetLastInputFrame() const { return LastInput; }
	FOnVerseBotInputFrame OnInputFrame;

	FVerseBotBrainCore* GetBrain() const { return Brain.Get(); }
	/** Override the world queries (harness, tests). The controller does not own them. */
	void SetWorldQueries(IVerseBotWorldQueries* InQueries) { QueriesOverride = InQueries; }

	/** Seed of the next match's brain RNG streams (harness: seeded runs). 0 picks one. */
	void SetSeed(uint64 InSeed) { FixedSeed = InSeed; }

	/** Match option ?BotTier=normal|hard|elite|adaptive; None when absent or unknown. */
	static FName ParseBotTierOption(const FString& Options);

	/**
	 * Writes FName BotTier and float BotEffectiveSkill into any reflected container that has them
	 * (the player state). False when a field is missing.
	 */
	static bool WriteBotIdentity(const UStruct* Type, void* Container, FName InTier, float InSkill);

	virtual void Tick(float DeltaSeconds) override;
	virtual void PostInitializeComponents() override;
	virtual void OnPossess(APawn* InPawn) override;
	virtual void OnUnPossess() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	void EnsureBrain();
	void ApplyInput(const FVerseInputFrame& Frame);
	void WriteIdentity();
	/** The last service frame with only the own pose refreshed from the own pawn (no new percepts). */
	FVersePerceptFrame SelfRefreshedFrame(uint32 ServerTimeMs) const;
	/** The world's server clock, ms: one clock for service frames and refreshed frames. */
	uint32 WorldServerTimeMs() const;
	const UVerseBotTier* EffectiveTier();

	TUniquePtr<FVerseBotBrainCore> Brain;
	TUniquePtr<IVerseBotWorldQueries> DefaultQueries;
	IVerseBotWorldQueries* QueriesOverride = nullptr;

	UPROPERTY(Transient)
	TObjectPtr<const UVerseBotTier> Tier;

	UPROPERTY(Transient)
	TObjectPtr<UVerseBotTier> InterpolatedTier;

	UPROPERTY(Transient)
	TObjectPtr<UVerseBotMatchMemory> MatchMemory;

	bool bAdaptive = false;
	float EffectiveSkill = 0.f;
	float PendingSkill = -1.f;
	bool bHasFrame = false;
	FVersePerceptFrame PendingFrame;
	/** The newest service frame: its own HUD (health, magazine, gadgets) stays valid between frames. */
	FVersePerceptFrame LastRealFrame;
	bool bHasRealFrame = false;
	uint32 LastThinkMs = 0;
	FVerseInputFrame LastInput;
	uint64 Seed = 0;
	uint64 FixedSeed = 0;
	bool bBrainReady = false;
};

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerState.h"

#include "VersePlayerState.generated.h"

/**
 * Score, respawn time and bot identity of one duel player (contracts/combat-state.md 2.1, 11.2).
 * Replicated to all with the push model; written on the server only: the score and RespawnAt
 * by the ruleset (Rules/), BotTier and BotEffectiveSkill by VerseBot.
 */
UCLASS()
class VERSECOMBAT_API AVersePlayerState : public APlayerState
{
	GENERATED_BODY()

public:
	AVersePlayerState();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Score")
	int32 Kills = 0;

	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Score")
	int32 Deaths = 0;

	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Score")
	int32 Headshots = 0;

	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Score")
	int32 Finishers = 0;

	/** Kills in the running set (first to UVerseRulesetConfig::KillsPerSet). */
	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Score")
	int32 SetKills = 0;

	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Score")
	int32 SetsWon = 0;

	/** Server time of the next respawn; UI countdown and kill cam length. */
	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Score")
	float RespawnAt = 0.f;

	/** normal, hard, elite or adaptive for the bot; None for a person. */
	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Bot")
	FName BotTier;

	/** Adaptive skill s of the bot; -1 for a person. */
	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Bot")
	float BotEffectiveSkill = -1.f;

	bool IsBotPlayer() const { return !BotTier.IsNone(); }

	/** Server: marks every score field dirty for the push model after the ruleset wrote them. */
	void MarkScoreDirty();
};

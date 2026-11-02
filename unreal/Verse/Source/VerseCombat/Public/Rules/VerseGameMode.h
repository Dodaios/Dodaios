#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "Rules/VerseRuleset.h"

#include "VerseGameMode.generated.h"

class AVersePlayerState;
class UVerseRulesetConfig;

/**
 * The thin game mode of combat-state.md 10: it owns one UVerseRuleset (from RulesetConfig, or
 * from unreal/Verse/Data/rules/deathmatch.json when none is set), fills the ruleset's world
 * functions, and forwards every rule question. It never decides a rule itself.
 *
 * Arena on (FVerseArenaSwitchEvent on the hub) is forwarded as OnMatchStart, every death as
 * OnKill; weapon, melee and gadget code report offensive actions with NotifyPlayerAction and
 * ask CanDamage / ModifyDamage before damage lands.
 */
UCLASS()
class VERSECOMBAT_API AVerseGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AVerseGameMode();

	UPROPERTY(EditDefaultsOnly, Category = "Verse|Rules")
	TObjectPtr<UVerseRulesetConfig> RulesetConfig;

	UPROPERTY(Transient)
	TObjectPtr<UVerseRuleset> Ruleset;

	virtual void InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage) override;
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual AActor* ChoosePlayerStart_Implementation(AController* Player) override;

	bool CanDamage(const FVerseDamageContext& Ctx) const;
	float ModifyDamage(const FVerseDamageContext& Ctx, float Damage) const;
	void NotifyPlayerAction(AVersePlayerState* Player, EVersePlayerAction Action);
	void GetLoadout(const AVersePlayerState* Player, TMap<EVerseLoadoutSlot, const UPrimaryDataAsset*>& Out) const;

	/** The world functions a ruleset gets in a real match (navmesh path length: see arena.md). */
	FVerseRulesHost MakeDefaultHost();

	/** The config the ruleset is built from; loads the rules JSON on first use. */
	const UVerseRulesetConfig* ResolveConfig();

private:
	void CreateRuleset();
	void HandleArenaSwitch(const FVerseArenaSwitchEvent& E);
	void HandleDeath(const FVerseDeathEvent& E);

	FDelegateHandle ArenaHandle;
	FDelegateHandle DeathHandle;
};

#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"

#include "VerseCombatStateComponent.generated.h"

/**
 * Combat state on the pawn (contracts/combat-state.md 2.1, 11.2). AVerseCharacter is a
 * VerseMovement class, so the combat phase and spawn protection live here; the primary
 * module's default pawn adds this component. Replicated to all with the push model.
 * It also carries the two per-victim transports of 5.1: the reliable hit copy to the victim
 * and the reliable death multicast.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSECOMBAT_API UVerseCombatStateComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseCombatStateComponent();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	static UVerseCombatStateComponent* FindOn(const AActor* Actor);

	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Combat")
	EVerseCombatPhase Phase = EVerseCombatPhase::Alive;

	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Combat")
	bool bSpawnProtected = false;

	/** Server time at which spawn protection ends (combat-state.md 9.3). */
	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Combat")
	float SpawnProtectedUntil = 0.f;

	/** Server: sets the phase (push model). */
	void SetPhase(EVerseCombatPhase NewPhase);

	/** Server: protection from Now for Duration seconds (the ruleset decides the duration). */
	void BeginSpawnProtection(float Now, float Duration);

	/** Server: ends protection on the first own offensive action (fire, melee, gadget). */
	void NotifyOffensiveAction(float Now);

	/** Protection holds at Now (flag set and the end time not reached). */
	bool IsSpawnProtected(float Now) const;

	bool IsAlive() const { return Phase == EVerseCombatPhase::Alive || Phase == EVerseCombatPhase::FinisherAttacker; }

	/** Reliable copy of a hit to the victim's owner (damage direction indicator). */
	UFUNCTION(Client, Reliable)
	void ClientReceiveHit(const FVerseHitEvent& Hit);

	/** Reliable death to everyone (score, kill cam, gore, respawn timer). */
	UFUNCTION(NetMulticast, Reliable)
	void MulticastDeath(const FVerseDeathEvent& Death);
};

#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseDamageService.generated.h"

class UAbilitySystemComponent;
class UVerseHealthSet;

/** What a rule hook is asked about (the shape of FVerseDamageContext in combat-state.md 11.2). */
struct FVerseDamageQuery
{
	AActor* Instigator = nullptr;
	AActor* Victim = nullptr;
	EVerseDamageSource Source = EVerseDamageSource::Bolt;
	EVerseHitZone Zone = EVerseHitZone::None;
};

/**
 * The ruleset hooks damage asks (combat-state.md 10: CanDamage, ModifyDamage, OnPlayerAction).
 * AVerseGameMode (WP11) binds its ruleset here; unbound hooks allow all and change nothing, which
 * is the WP11 fake WP02 tests against.
 */
struct FVerseDamageRules
{
	TFunction<bool(const FVerseDamageQuery&)> CanDamage;
	TFunction<float(const FVerseDamageQuery&, float)> ModifyDamage;
	TFunction<void(AActor* /*Player*/, EVerseDamageSource /*Offensive action*/)> OnOffensiveAction;
};

/** Ids of combat participants as events carry them. */
namespace VerseCombatIds
{
	/** Player state id for a pawn with one; a stable negative id below -1 for other actors; -1 for none (world). */
	VERSECOMBAT_API int32 IdOf(const AActor* Actor);
}

/**
 * Server damage (WP02.9): spawn protection and finisher rules, the ruleset hooks, the GAS damage
 * effect (armor first), the killing blow, FVerseDeathEvent and the hub and per-victim transports
 * of combat-state.md 5.1.
 */
UCLASS()
class VERSECOMBAT_API UVerseDamageService : public UWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseDamageService* Get(const UObject* WorldContextObject);

	FVerseDamageRules Rules;

	/** Default respawn delay put into FVerseDeathEvent::RespawnAt until a ruleset answers (start 3.0 s). */
	float DefaultRespawnDelay = 3.f;

	/**
	 * Applies Hit.Damage from Instigator to Victim on the server and completes the hit event
	 * (killing blow, spawn-protection marker, server time). Raises OnHit on the hub, the reliable copy
	 * to the victim and, on a kill, the death event. Returns the damage that reached health and armor.
	 * Server only; a call without authority does nothing.
	 */
	float ApplyHit(AActor* Instigator, AActor* Victim, FVerseHitEvent& Hit);

	/** Health and armor of a victim; nullptr when it has none. */
	static const UVerseHealthSet* FindHealth(const AActor* Actor);
	static UAbilitySystemComponent* FindAsc(const AActor* Actor);

	/** Server time used by combat on this world. */
	float Now() const;
};

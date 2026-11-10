#pragma once

#include "AbilitySystemInterface.h"
#include "CoreMinimal.h"
#include "VerseCharacter.h"

#include "VerseDefaultCharacter.generated.h"

class UAbilitySystemComponent;
class UVerseCombatStateComponent;
class UVerseGadgetComponent;
class UVerseHealthSet;
class UVerseInventoryComponent;
class UVerseMeleeComponent;
class UVerseWeaponComponent;
class UVerseCombatDriverComponent;
class UVerseViewmodelComponent;

/**
 * Default pawn: the WP01 first-person character (VerseMovement) with the combat parts of
 * contracts/combat-state.md 2.1 on it. Movement never includes Combat (decision C8), so the
 * primary module is where the two meet:
 *
 * - UAbilitySystemComponent with UVerseHealthSet (health and armor, owner only),
 * - UVerseCombatStateComponent (phase, spawn protection),
 * - UVerseInventoryComponent and UVerseWeaponComponent (firearms, 2.2),
 * - UVerseMeleeComponent (knife and finisher, 7),
 * - UVerseGadgetComponent (Bulwark and breach charge, 2.3),
 * - UVerseViewmodelComponent (the person's first-person weapon).
 *
 * AVerseDefaultGameMode hands out the loadout on every spawn.
 */
UCLASS()
class VERSE_API AVerseDefaultCharacter : public AVerseCharacter, public IAbilitySystemInterface
{
	GENERATED_BODY()

public:
	AVerseDefaultCharacter(const FObjectInitializer& ObjectInitializer);

	// IAbilitySystemInterface
	virtual UAbilitySystemComponent* GetAbilitySystemComponent() const override;

	// AActor / APawn
	virtual void PossessedBy(AController* NewController) override;
	virtual void OnRep_Controller() override;
	virtual void SetupPlayerInputComponent(UInputComponent* PlayerInputComponent) override;
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

	UVerseCombatStateComponent* GetCombatState() const { return CombatState; }
	const UVerseHealthSet* GetHealthSet() const { return HealthSet; }
	UVerseInventoryComponent* GetInventory() const { return Inventory; }
	UVerseWeaponComponent* GetWeapon() const { return Weapon; }
	UVerseMeleeComponent* GetMelee() const { return Melee; }
	UVerseGadgetComponent* GetGadgets() const { return Gadgets; }
	UVerseCombatDriverComponent* GetCombatDriver() const { return CombatDriver; }
	UVerseViewmodelComponent* GetViewmodel() const { return Viewmodel; }

private:
	void InitAbilityActorInfo();

	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UAbilitySystemComponent> Abilities;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UVerseHealthSet> HealthSet;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UVerseCombatStateComponent> CombatState;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UVerseInventoryComponent> Inventory;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UVerseWeaponComponent> Weapon;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UVerseMeleeComponent> Melee;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UVerseGadgetComponent> Gadgets;

	/** Input frame to combat (shots, reloads, slots, knife, gadgets). */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UVerseCombatDriverComponent> CombatDriver;

	/** The held weapon in front of the person's camera (locally controlled persons only). */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UVerseViewmodelComponent> Viewmodel;
};

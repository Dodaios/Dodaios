#pragma once

#include "Abilities/GameplayAbility.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

#include "VerseGadgetAbilities.generated.h"

/**
 * Base of the gadget abilities (combat-state.md 2.3): local-predicted, so the owning client plays
 * only the deploy or plant animation with a prediction key; the server asks the pawn's
 * UVerseGadgetComponent to start the use, which owns charges, cooldown, use time and spawning.
 */
UCLASS(Abstract)
class VERSECOMBAT_API UVerseGA_Gadget : public UGameplayAbility
{
	GENERATED_BODY()

public:
	UVerseGA_Gadget();

	virtual void ActivateAbility(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
		const FGameplayAbilityActivationInfo ActivationInfo, const FGameplayEventData* TriggerEventData) override;

	/** The loadout slot this ability uses. */
	EVerseLoadoutSlot GadgetSlot = EVerseLoadoutSlot::GadgetA;

	/** Server answer of the last activation (tests). */
	bool bLastServerUseStarted = false;
};

/** Deploys the Bulwark (GadgetA). */
UCLASS()
class VERSECOMBAT_API UVerseGA_Bulwark : public UVerseGA_Gadget
{
	GENERATED_BODY()

public:
	UVerseGA_Bulwark();
};

/** Plants a breach charge (GadgetB). */
UCLASS()
class VERSECOMBAT_API UVerseGA_BreachCharge : public UVerseGA_Gadget
{
	GENERATED_BODY()

public:
	UVerseGA_BreachCharge();
};

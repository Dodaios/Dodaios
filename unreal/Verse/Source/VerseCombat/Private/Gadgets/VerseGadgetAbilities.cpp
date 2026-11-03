#include "Gadgets/VerseGadgetAbilities.h"

#include "Gadgets/VerseGadgetComponent.h"
#include "Weapons/VerseCombatEvents.h"

UVerseGA_Gadget::UVerseGA_Gadget()
{
	NetExecutionPolicy = EGameplayAbilityNetExecutionPolicy::LocalPredicted;
	InstancingPolicy = EGameplayAbilityInstancingPolicy::InstancedPerActor;
}

void UVerseGA_Gadget::ActivateAbility(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
	const FGameplayAbilityActivationInfo ActivationInfo, const FGameplayEventData* TriggerEventData)
{
	bLastServerUseStarted = false;
	if (!CommitAbility(Handle, ActorInfo, ActivationInfo))
	{
		EndAbility(Handle, ActorInfo, ActivationInfo, true, true);
		return;
	}
	if (HasAuthority(&ActivationInfo) && ActorInfo)
	{
		AActor* Avatar = ActorInfo->AvatarActor.Get();
		if (UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(Avatar))
		{
			bLastServerUseStarted = Gadgets->ServerBeginUse(GadgetSlot, VerseCombatEvents::ServerTime(Avatar));
		}
	}
	// The use time runs in the gadget component; the predicted client side is animation only.
	EndAbility(Handle, ActorInfo, ActivationInfo, true, false);
}

UVerseGA_Bulwark::UVerseGA_Bulwark()
{
	GadgetSlot = EVerseLoadoutSlot::GadgetA;
}

UVerseGA_BreachCharge::UVerseGA_BreachCharge()
{
	GadgetSlot = EVerseLoadoutSlot::GadgetB;
}

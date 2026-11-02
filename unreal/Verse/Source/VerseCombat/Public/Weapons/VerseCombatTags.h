#pragma once

#include "CoreMinimal.h"
#include "NativeGameplayTags.h"

// Presentation tags of the weapon definition (combat-state.md 3: BoltColorOwn, BoltColorFoe).
// Own bolts amber, the opponent's red (README Projectiles).
namespace VerseCombatTags
{
	VERSECOMBAT_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Presentation_Bolt_Amber);
	VERSECOMBAT_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Presentation_Bolt_Red);

	/** Linear colour of a bolt presentation tag; amber for an unknown tag on the own side. */
	VERSECOMBAT_API FLinearColor BoltColor(const struct FGameplayTag& Tag, bool bOwn);
}

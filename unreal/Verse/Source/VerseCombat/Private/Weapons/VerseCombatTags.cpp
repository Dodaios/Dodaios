#include "Weapons/VerseCombatTags.h"

namespace VerseCombatTags
{
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Presentation_Bolt_Amber, "Verse.Presentation.Bolt.Amber", "Own bolt colour");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Presentation_Bolt_Red, "Verse.Presentation.Bolt.Red", "Opponent bolt colour");

	FLinearColor BoltColor(const FGameplayTag& Tag, bool bOwn)
	{
		static const FLinearColor Amber(1.0f, 0.55f, 0.05f, 1.f);
		static const FLinearColor Red(0.95f, 0.06f, 0.04f, 1.f);
		if (Tag == Presentation_Bolt_Amber)
		{
			return Amber;
		}
		if (Tag == Presentation_Bolt_Red)
		{
			return Red;
		}
		return bOwn ? Amber : Red;
	}
}

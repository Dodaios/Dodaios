#include "Brain/VerseBotTypes.h"

#include "VerseGameplayTags.h"

namespace VerseBot
{
	FGameplayTag StateTag(EVerseBotState State)
	{
		const TConstArrayView<FGameplayTag> Tags = VerseTags::AllBotStateTags();
		const int32 Index = int32(State);
		return Tags.IsValidIndex(Index) ? Tags[Index] : FGameplayTag();
	}

	const TCHAR* StateName(EVerseBotState State)
	{
		switch (State)
		{
		case EVerseBotState::Attack: return TEXT("attack");
		case EVerseBotState::Hold: return TEXT("hold");
		case EVerseBotState::Flank: return TEXT("flank");
		case EVerseBotState::StalkForFinisher: return TEXT("stalk_for_finisher");
		case EVerseBotState::Retreat: return TEXT("retreat");
		case EVerseBotState::Reload: return TEXT("reload");
		case EVerseBotState::DeployBulwark: return TEXT("deploy_bulwark");
		case EVerseBotState::Breach: return TEXT("breach");
		case EVerseBotState::Wallbang: return TEXT("wallbang");
		case EVerseBotState::Search: return TEXT("search");
		}
		return TEXT("unknown");
	}
}

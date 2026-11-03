#include "Rules/VersePlayerState.h"

#include "Net/Core/PushModel/PushModel.h"
#include "Net/UnrealNetwork.h"

AVersePlayerState::AVersePlayerState()
{
	bReplicates = true;
}

void AVersePlayerState::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);

	FDoRepLifetimeParams Params;
	Params.bIsPushBased = true;
	DOREPLIFETIME_WITH_PARAMS_FAST(AVersePlayerState, Kills, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVersePlayerState, Deaths, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVersePlayerState, Headshots, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVersePlayerState, Finishers, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVersePlayerState, SetKills, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVersePlayerState, SetsWon, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVersePlayerState, RespawnAt, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVersePlayerState, BotTier, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(AVersePlayerState, BotEffectiveSkill, Params);
}

void AVersePlayerState::MarkScoreDirty()
{
	MARK_PROPERTY_DIRTY_FROM_NAME(AVersePlayerState, Kills, this);
	MARK_PROPERTY_DIRTY_FROM_NAME(AVersePlayerState, Deaths, this);
	MARK_PROPERTY_DIRTY_FROM_NAME(AVersePlayerState, Headshots, this);
	MARK_PROPERTY_DIRTY_FROM_NAME(AVersePlayerState, Finishers, this);
	MARK_PROPERTY_DIRTY_FROM_NAME(AVersePlayerState, SetKills, this);
	MARK_PROPERTY_DIRTY_FROM_NAME(AVersePlayerState, SetsWon, this);
	MARK_PROPERTY_DIRTY_FROM_NAME(AVersePlayerState, RespawnAt, this);
}

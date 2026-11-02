#include "Damage/VerseCombatStateComponent.h"

#include "Net/Core/PushModel/PushModel.h"
#include "Net/UnrealNetwork.h"

UVerseCombatStateComponent::UVerseCombatStateComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	SetIsReplicatedByDefault(true);
}

void UVerseCombatStateComponent::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);

	FDoRepLifetimeParams Params;
	Params.bIsPushBased = true;
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseCombatStateComponent, Phase, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseCombatStateComponent, bSpawnProtected, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseCombatStateComponent, SpawnProtectedUntil, Params);
}

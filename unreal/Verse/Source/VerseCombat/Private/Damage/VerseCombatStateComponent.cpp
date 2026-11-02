#include "Damage/VerseCombatStateComponent.h"

#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Actor.h"
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

UVerseCombatStateComponent* UVerseCombatStateComponent::FindOn(const AActor* Actor)
{
	return Actor ? Actor->FindComponentByClass<UVerseCombatStateComponent>() : nullptr;
}

void UVerseCombatStateComponent::SetPhase(EVerseCombatPhase NewPhase)
{
	if (Phase != NewPhase)
	{
		Phase = NewPhase;
		MARK_PROPERTY_DIRTY_FROM_NAME(UVerseCombatStateComponent, Phase, this);
	}
}

void UVerseCombatStateComponent::BeginSpawnProtection(float Now, float Duration)
{
	bSpawnProtected = Duration > 0.f;
	SpawnProtectedUntil = Now + FMath::Max(0.f, Duration);
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseCombatStateComponent, bSpawnProtected, this);
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseCombatStateComponent, SpawnProtectedUntil, this);
}

void UVerseCombatStateComponent::NotifyOffensiveAction(float Now)
{
	if (bSpawnProtected)
	{
		bSpawnProtected = false;
		SpawnProtectedUntil = FMath::Min(SpawnProtectedUntil, Now);
		MARK_PROPERTY_DIRTY_FROM_NAME(UVerseCombatStateComponent, bSpawnProtected, this);
		MARK_PROPERTY_DIRTY_FROM_NAME(UVerseCombatStateComponent, SpawnProtectedUntil, this);
	}
}

bool UVerseCombatStateComponent::IsSpawnProtected(float Now) const
{
	return bSpawnProtected && Now < SpawnProtectedUntil;
}

void UVerseCombatStateComponent::ClientReceiveHit_Implementation(const FVerseHitEvent& Hit)
{
	// The owning client learns of the hit (direction indicator); the server already raised it.
	const AActor* Owner = GetOwner();
	if (Owner && !Owner->HasAuthority())
	{
		if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
		{
			Hub->OnHit.Broadcast(Hit);
		}
	}
}

void UVerseCombatStateComponent::MulticastDeath_Implementation(const FVerseDeathEvent& Death)
{
	const AActor* Owner = GetOwner();
	if (Owner && !Owner->HasAuthority())
	{
		if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
		{
			Hub->OnDeath.Broadcast(Death);
		}
	}
}

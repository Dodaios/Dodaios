#include "Damage/VerseDamageService.h"

#include "AbilitySystemComponent.h"
#include "AbilitySystemGlobals.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Damage/VerseHealthSet.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerState.h"

int32 VerseCombatIds::IdOf(const AActor* Actor)
{
	if (!Actor)
	{
		return -1;
	}
	if (const APawn* Pawn = Cast<APawn>(Actor))
	{
		if (const APlayerState* Ps = Pawn->GetPlayerState())
		{
			return Ps->GetPlayerId();
		}
	}
	if (const APlayerState* Ps = Cast<APlayerState>(Actor))
	{
		return Ps->GetPlayerId();
	}
	// Actors without a player state (gadgets' owners in tests, targets): stable, never -1.
	return -2 - int32(Actor->GetUniqueID() & 0x3FFFFFFF);
}

UVerseDamageService* UVerseDamageService::Get(const UObject* WorldContextObject)
{
	const UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UVerseDamageService>() : nullptr;
}

float UVerseDamageService::Now() const
{
	const UWorld* World = GetWorld();
	return World ? World->GetTimeSeconds() : 0.f;
}

UAbilitySystemComponent* UVerseDamageService::FindAsc(const AActor* Actor)
{
	return Actor ? UAbilitySystemGlobals::GetAbilitySystemComponentFromActor(Actor) : nullptr;
}

const UVerseHealthSet* UVerseDamageService::FindHealth(const AActor* Actor)
{
	const UAbilitySystemComponent* Asc = FindAsc(Actor);
	return Asc ? Asc->GetSet<UVerseHealthSet>() : nullptr;
}

float UVerseDamageService::ApplyHit(AActor* Instigator, AActor* Victim, FVerseHitEvent& Hit)
{
	if (!Victim || !Victim->HasAuthority())
	{
		return 0.f;
	}
	const float T = Now();
	Hit.ServerTime = T;
	Hit.InstigatorId = VerseCombatIds::IdOf(Instigator);
	Hit.VictimId = VerseCombatIds::IdOf(Victim);
	Hit.bHeadshot = Hit.Zone == EVerseHitZone::Head ? 1 : 0;

	UVerseCombatStateComponent* State = UVerseCombatStateComponent::FindOn(Victim);
	if (State && State->Phase == EVerseCombatPhase::Dead)
	{
		return 0.f;
	}

	bool bBlocked = false;
	if (State && State->IsSpawnProtected(T))
	{
		bBlocked = true;
		Hit.bBlockedBySpawnProtection = 1;
	}
	// A finisher victim takes no other damage (combat-state.md 7.4).
	if (State && State->Phase == EVerseCombatPhase::FinisherVictim && Hit.Source != EVerseDamageSource::Finisher)
	{
		bBlocked = true;
	}

	FVerseDamageQuery Query;
	Query.Instigator = Instigator;
	Query.Victim = Victim;
	Query.Source = Hit.Source;
	Query.Zone = Hit.Zone;
	if (!bBlocked && Rules.CanDamage && !Rules.CanDamage(Query))
	{
		bBlocked = true;
	}

	float Damage = bBlocked ? 0.f : FMath::Max(0.f, Hit.Damage);
	if (!bBlocked && Rules.ModifyDamage)
	{
		Damage = FMath::Max(0.f, Rules.ModifyDamage(Query, Damage));
	}
	Hit.Damage = Damage;

	float Applied = 0.f;
	bool bKilled = false;
	if (Damage > 0.f)
	{
		UAbilitySystemComponent* Asc = FindAsc(Victim);
		const UVerseHealthSet* Set = Asc ? Asc->GetSet<UVerseHealthSet>() : nullptr;
		if (Asc && Set)
		{
			const float Before = Set->GetHealth();
			FGameplayEffectContextHandle Context = Asc->MakeEffectContext();
			Context.AddInstigator(Instigator, Instigator);
			FGameplayEffectSpec Spec(GetDefault<UVerseDamageEffect>(), Context, 1.f);
			Spec.SetSetByCallerMagnitude(UVerseDamageEffect::DamageName, Damage);
			Asc->ApplyGameplayEffectSpecToSelf(Spec);
			Applied = Set->LastToArmor + Set->LastToHealth;
			bKilled = Before > 0.f && Set->GetHealth() <= 0.f;
		}
	}
	Hit.bKillingBlow = bKilled ? 1 : 0;

	UVerseEventHub* Hub = UVerseEventHub::Get(this);
	if (Hub)
	{
		Hub->OnHit.Broadcast(Hit);
	}
	if (State)
	{
		State->ClientReceiveHit(Hit);
	}

	if (bKilled)
	{
		FVerseDeathEvent Death;
		Death.VictimId = Hit.VictimId;
		Death.KillerId = Hit.InstigatorId;
		Death.Cause = Hit.Source;
		Death.WeaponId = Hit.WeaponId;
		Death.LastZone = Hit.Zone;
		Death.ServerTime = T;
		Death.RespawnAt = T + DefaultRespawnDelay;
		if (State)
		{
			State->SetPhase(EVerseCombatPhase::Dead);
		}
		if (Hub)
		{
			Hub->OnDeath.Broadcast(Death);
		}
		if (State)
		{
			State->MulticastDeath(Death);
		}
	}
	return Applied;
}

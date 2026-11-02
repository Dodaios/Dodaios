#include "Melee/VerseMeleeWorld.h"

#include "CollisionQueryParams.h"
#include "Components/CapsuleComponent.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/GameStateBase.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerState.h"
#include "Movement/VerseMovementQuery.h"
#include "Net/Core/PushModel/PushModel.h"
#include "Stubs/VerseNullStubs.h"

int32 VerseMelee::PlayerIdOf(const APawn* Pawn)
{
	if (!Pawn)
	{
		return -1;
	}
	if (const APlayerState* State = Pawn->GetPlayerState())
	{
		return State->GetPlayerId();
	}
	return int32(Pawn->GetUniqueID());
}

APawn* VerseMelee::FindPawnById(const UWorld* World, int32 Id)
{
	if (!World)
	{
		return nullptr;
	}
	for (TActorIterator<APawn> It(const_cast<UWorld*>(World)); It; ++It)
	{
		if (PlayerIdOf(*It) == Id)
		{
			return *It;
		}
	}
	return nullptr;
}

void VerseMelee::SetPhase(APawn* Pawn, EVerseCombatPhase Phase)
{
	UVerseCombatStateComponent* State = Pawn ? Pawn->FindComponentByClass<UVerseCombatStateComponent>() : nullptr;
	if (State && State->Phase != Phase)
	{
		State->Phase = Phase;
		MARK_PROPERTY_DIRTY_FROM_NAME(UVerseCombatStateComponent, Phase, State);
	}
}

void VerseMelee::EndSpawnProtection(APawn* Pawn)
{
	UVerseCombatStateComponent* State = Pawn ? Pawn->FindComponentByClass<UVerseCombatStateComponent>() : nullptr;
	if (State && State->bSpawnProtected)
	{
		State->bSpawnProtected = false;
		MARK_PROPERTY_DIRTY_FROM_NAME(UVerseCombatStateComponent, bSpawnProtected, State);
	}
}

double VerseMelee::HalfHeightOf(const APawn* Pawn)
{
	const ACharacter* Character = Cast<ACharacter>(Pawn);
	return Character && Character->GetCapsuleComponent() ? Character->GetCapsuleComponent()->GetScaledCapsuleHalfHeight() : 0.0;
}

double FVerseInterimMeleeWorld::ServerNow() const
{
	const UWorld* W = World.Get();
	if (!W)
	{
		return 0.0;
	}
	if (const AGameStateBase* GameState = W->GetGameState())
	{
		return GameState->GetServerWorldTimeSeconds();
	}
	return W->GetTimeSeconds();
}

FTransform FVerseInterimMeleeWorld::GetBaseTransformAt(const APawn* Pawn, double /*ServerTime*/) const
{
	// Fake rewind (WP02.8 pending): the current transform.
	if (!Pawn)
	{
		return FTransform::Identity;
	}
	FVector Location = Pawn->GetActorLocation();
	Location.Z -= VerseMelee::HalfHeightOf(Pawn);
	return FTransform(FRotator(0.0, Pawn->GetActorRotation().Yaw, 0.0), Location);
}

FVerseMeleeParticipant FVerseInterimMeleeWorld::Describe(const APawn* Pawn) const
{
	FVerseMeleeParticipant P;
	if (!Pawn)
	{
		P.Phase = EVerseCombatPhase::Dead;
		return P;
	}
	if (const UVerseCombatStateComponent* State = Pawn->FindComponentByClass<UVerseCombatStateComponent>())
	{
		P.Phase = State->Phase;
		P.bSpawnProtected = State->bSpawnProtected;
	}
	const IVerseMovementQuery* Query = nullptr;
	if (UActorComponent* Component = Pawn->FindComponentByInterface(UVerseMovementQuery::StaticClass()))
	{
		Query = Cast<IVerseMovementQuery>(Component);
	}
	if (!Query)
	{
		Query = GetDefault<UVerseNullMovementQuery>();
	}
	P.Stance = Query->GetStance();
	P.bMantling = Query->IsMantling();
	P.bAirborne = Query->IsAirborne();
	return P;
}

bool FVerseInterimMeleeWorld::IsSweepClear(const APawn* Attacker, const APawn* Victim) const
{
	UWorld* W = World.Get();
	if (!W || !Attacker || !Victim)
	{
		return false;
	}
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseMeleeSweep), false);
	Params.AddIgnoredActor(Attacker);
	Params.AddIgnoredActor(Victim);
	FCollisionObjectQueryParams Objects;
	Objects.AddObjectTypesToQuery(ECC_WorldStatic);
	Objects.AddObjectTypesToQuery(ECC_WorldDynamic);
	// A thin capsule between the two chest heights: walls, cover and glass block, the floor does not.
	const FVector From = Attacker->GetActorLocation();
	const FVector To = Victim->GetActorLocation();
	return !W->SweepTestByObjectType(From, To, FQuat::Identity, Objects, FCollisionShape::MakeCapsule(15.f, 40.f), Params);
}

void FVerseInterimMeleeWorld::GetCandidates(const APawn* Attacker, TArray<APawn*>& Out) const
{
	UWorld* W = World.Get();
	if (!W)
	{
		return;
	}
	for (TActorIterator<APawn> It(W); It; ++It)
	{
		if (*It != Attacker && !It->IsPendingKillPending())
		{
			Out.Add(*It);
		}
	}
}

float FVerseInterimMeleeWorld::GetHealth(const APawn* Pawn) const
{
	const float* Found = Health.Find(Pawn);
	return Found ? *Found : StartHealth;
}

void FVerseInterimMeleeWorld::ApplyMeleeHit(APawn* Attacker, APawn* Victim, FVerseHitEvent& Hit)
{
	if (!Victim)
	{
		return;
	}
	const FVerseMeleeParticipant Target = Describe(Victim);
	const float Before = GetHealth(Victim);
	float Applied = 0.f;
	if (Target.bSpawnProtected && Hit.Source != EVerseDamageSource::Finisher)
	{
		Hit.bBlockedBySpawnProtection = 1;
	}
	else if (VerseMelee::AllowsDamage(Target.Phase, Hit.Source) && Before > 0.f)
	{
		const float Asked = Hit.Source == EVerseDamageSource::Finisher ? Before : Hit.Damage;
		Applied = FMath::Min(Asked, Before);
	}
	const float After = Before - Applied;
	Health.Add(Victim, After);
	Hit.Damage = Applied;
	Hit.bKillingBlow = (Applied > 0.f && After <= 0.f) ? 1 : 0;
	Hit.ServerTime = float(ServerNow());

	UVerseEventHub* Hub = UVerseEventHub::Get(Victim);
	if (Hub)
	{
		Hub->OnHit.Broadcast(Hit);
	}
	if (Hit.bKillingBlow)
	{
		VerseMelee::SetPhase(Victim, EVerseCombatPhase::Dead);
		if (Hub)
		{
			FVerseDeathEvent Death;
			Death.VictimId = Hit.VictimId;
			Death.KillerId = Hit.InstigatorId;
			Death.Cause = Hit.Source;
			Death.WeaponId = Hit.WeaponId;
			Death.LastZone = Hit.Zone;
			Death.ServerTime = Hit.ServerTime;
			// The respawn delay is the ruleset's (WP11); 3.0 s is the deathmatch start value.
			Death.RespawnAt = Hit.ServerTime + 3.f;
			Hub->OnDeath.Broadcast(Death);
		}
	}
}

IVerseMeleeWorld* UVerseMeleeWorldSubsystem::Get(const UObject* WorldContextObject)
{
	if (!WorldContextObject || !GEngine)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull);
	const UVerseMeleeWorldSubsystem* Subsystem = World ? World->GetSubsystem<UVerseMeleeWorldSubsystem>() : nullptr;
	return Subsystem ? &Subsystem->GetWorldPort() : nullptr;
}

void UVerseMeleeWorldSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Interim = MakeShared<FVerseInterimMeleeWorld>(GetWorld());
}

void UVerseMeleeWorldSubsystem::Deinitialize()
{
	Override.Reset();
	Interim.Reset();
	Super::Deinitialize();
}

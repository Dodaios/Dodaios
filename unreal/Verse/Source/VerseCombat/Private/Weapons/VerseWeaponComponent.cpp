#include "Weapons/VerseWeaponComponent.h"

#include "Combat/VerseWeaponDefinition.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Damage/VerseDamageService.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/Pawn.h"
#include "Inventory/VerseInventoryComponent.h"
#include "LagComp/VerseLagCompensation.h"
#include "Movement/VerseMovementQuery.h"
#include "Net/Core/PushModel/PushModel.h"
#include "Net/UnrealNetwork.h"
#include "Projectiles/VerseProjectileManager.h"
#include "Stubs/VerseNullStubs.h"
#include "VerseGameplayTags.h"
#include "Weapons/VerseCombatEvents.h"
#include "HAL/PlatformTime.h"
#include "VerseRng.h"

namespace
{
	const IVerseMovementQuery& MovementOf(const AActor* Actor)
	{
		if (Actor)
		{
			for (UActorComponent* C : Actor->GetComponents())
			{
				if (const IVerseMovementQuery* Q = Cast<IVerseMovementQuery>(C))
				{
					return *Q;
				}
			}
		}
		return *GetDefault<UVerseNullMovementQuery>();
	}

	bool IsLocalOwner(const AActor* Owner)
	{
		const APawn* Pawn = Cast<APawn>(Owner);
		return Pawn && Pawn->IsLocallyControlled();
	}
}

FOnVerseAnyShotRejected UVerseWeaponComponent::OnAnyShotRejected;

UVerseWeaponComponent::UVerseWeaponComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	SetIsReplicatedByDefault(true);
}

void UVerseWeaponComponent::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	FDoRepLifetimeParams Params;
	Params.bIsPushBased = true;
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseWeaponComponent, AdsBlend, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseWeaponComponent, MatchSeed, Params);
}

void UVerseWeaponComponent::BeginPlay()
{
	Super::BeginPlay();
	const AActor* Owner = GetOwner();
	if (Owner && Owner->HasAuthority() && MatchSeed == 0)
	{
		// One seed per spawn unless the game mode sets a match seed; clients get it with the actor.
		SetMatchSeed(FVerseRng::Hash(uint32(FPlatformTime::Cycles()), uint32(GetUniqueID()), uint32(FMath::Rand())));
	}
}

void UVerseWeaponComponent::SetMatchSeed(uint32 Seed)
{
	MatchSeed = Seed;
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseWeaponComponent, MatchSeed, this);
}

UVerseWeaponComponent* UVerseWeaponComponent::FindOn(const AActor* Actor)
{
	return Actor ? Actor->FindComponentByClass<UVerseWeaponComponent>() : nullptr;
}

UVerseInventoryComponent* UVerseWeaponComponent::GetInventory() const
{
	return UVerseInventoryComponent::FindOn(GetOwner());
}

const UVerseWeaponDefinition* UVerseWeaponComponent::GetActiveDefinition() const
{
	const UVerseInventoryComponent* Inv = GetInventory();
	return Inv ? Inv->GetActiveWeapon() : nullptr;
}

int32 UVerseWeaponComponent::GetShooterId() const
{
	return VerseCombatIds::IdOf(GetOwner());
}

void UVerseWeaponComponent::ResyncPredictedSlot()
{
	const UVerseInventoryComponent* Inv = GetInventory();
	const FVerseWeaponSlotState* S = Inv ? Inv->GetActiveState() : nullptr;
	if (S)
	{
		PredictedSlot = *S;
		PredictedWeaponId = S->Definition ? S->Definition->WeaponId : NAME_None;
	}
}

void UVerseWeaponComponent::StepAds(bool bAdsHeld, float Dt)
{
	const UVerseWeaponDefinition* W = GetActiveDefinition();
	const float Rate = (W && W->AdsTime > 0.f) ? 1.f / W->AdsTime : 1000.f;
	const float Current = GetAdsBlend01();
	const float Next = FMath::Clamp(Current + (bAdsHeld ? 1.f : -1.f) * Rate * Dt, 0.f, 1.f);
	const uint8 Q = uint8(FMath::RoundToInt(Next * 255.f));
	if (Q != AdsBlend)
	{
		AdsBlend = Q;
		MARK_PROPERTY_DIRTY_FROM_NAME(UVerseWeaponComponent, AdsBlend, this);
	}
}

FRotator UVerseWeaponComponent::StepFire(const FVerseFireContext& Ctx, TArray<FVerseShotOut>* OutShots)
{
	const UVerseWeaponDefinition* W = GetActiveDefinition();
	if (!W)
	{
		return FRotator::ZeroRotator;
	}
	AActor* Owner = GetOwner();
	const bool bAuthority = Owner && Owner->HasAuthority();
	const UVerseInventoryComponent* Inv = GetInventory();

	// The predicted magazine follows the replicated one whenever nothing is in flight.
	if (bAuthority || Predictor.NumPending() == 0 || PredictedWeaponId != W->WeaponId)
	{
		ResyncPredictedSlot();
	}
	for (const uint16 Counter : Predictor.Expire(Ctx.Now))
	{
		FVerseMagazine::RefundRound(PredictedSlot, *W);
		OnShotAnswered.Broadcast(Counter, EVerseShotResult::Rejected);
		OnAnyShotRejected.Broadcast(GetShooterId(), Counter);
	}


	const bool bReady = (!Inv || Inv->IsReady(Ctx.Now)) && !FVerseMagazine::IsReloading(PredictedSlot) && !Ctx.bFiringBlocked;
	const int32 Rounds = bReady ? FVerseMagazine::RoundsReady(PredictedSlot, *W) : 0;
	TArray<float> Times;
	Cadence.Collect(*W, Ctx.bTriggerDown && bReady, Ctx.Now - Ctx.Dt, Ctx.Now, Rounds, Times);

	const float Ads = GetAdsBlend01();
	const float Mul = FVerseRecoilState::Multiplier(*W, Ctx.Stance, Ads);
	FRotator Control = Ctx.Control;
	FRotator Out = FRotator::ZeroRotator;
	auto AddRot = [&Control, &Out](const FVector2f& PitchYaw, float Sign)
	{
		Control.Pitch += Sign * PitchYaw.X;
		Control.Yaw += Sign * PitchYaw.Y;
		Out.Pitch += Sign * PitchYaw.X;
		Out.Yaw += Sign * PitchYaw.Y;
	};

	const int32 ShooterId = GetShooterId();
	for (const float T : Times)
	{
		AddRot(Recoil.TickKick(*W, T), 1.f);
		Recoil.BeginShot(*W, T);

		FVerseShotOut Shot;
		Shot.Counter = ++NextShotCounter;
		Shot.Seed = FVerseSpread::ShotSeed(uint32(ShooterId), Shot.Counter, MatchSeed);
		Shot.ShotIndex = Recoil.ShotIndex;
		Shot.Time = T;

		FVerseSpreadInput In;
		In.Stance = Ctx.Stance;
		In.AdsBlend = Ads;
		In.HorizontalSpeedMps = Ctx.HorizontalSpeedMps;
		In.bAirborne = Ctx.bAirborne;
		// Bloom decays up to this shot's own time (not the tick's end), exactly as the server derives it.
		Spread.DecayUntilShot(*W, T);
		Shot.Sigma = Spread.SigmaFor(*W, In, T);
		Shot.Origin = Ctx.Eye;
		Shot.Dir = FVerseSpread::ShotDirection(Control.Vector(), Shot.Sigma, Shot.Seed, Shot.ShotIndex);
		Shot.Kick = Recoil.KickFor(*W, Mul, Shot.Seed);

		Recoil.OnShot(Shot.Kick, T);
		Spread.OnShot(*W, T);
		FVerseMagazine::ConsumeRound(PredictedSlot, *W);

		FVerseFireEvent E;
		E.ShooterId = ShooterId;
		E.WeaponId = W->WeaponId;
		E.ShotCounter = Shot.Counter;
		E.Seed = Shot.Seed;
		E.Origin = Shot.Origin;
		E.Direction = Shot.Dir;
		E.ServerTime = T;

		if (bAuthority)
		{
			OnPredictedFire.Broadcast(E);
			HandleServerFire(Shot.Counter, Shot.Seed, Shot.Origin, Shot.Dir, T);
		}
		else
		{
			FVersePredictedShot P;
			P.Counter = Shot.Counter;
			P.Time = T;
			// What the server will receive: the origin quantised to 0.1 cm.
			P.Origin = FVector_NetQuantize10(Shot.Origin);
			P.Dir = Shot.Dir;
			P.WeaponId = W->WeaponId;
			Predictor.Add(P);
			OnPredictedFire.Broadcast(E);
			VerseCombatEvents::RaiseFire(this, E); // the owner predicts its own fire event
			ServerFire(Shot.Counter, Shot.Seed, FVector_NetQuantize10(Shot.Origin), FVector_NetQuantizeNormal(Shot.Dir), T);
		}
		if (OutShots)
		{
			OutShots->Add(Shot);
		}
	}

	AddRot(Recoil.TickKick(*W, Ctx.Now), 1.f);
	AddRot(Recoil.TickRecovery(*W, Ctx.Now, Ctx.Dt), -1.f);
	LastStepTime = Ctx.Now;
	if (bAuthority)
	{
		ResyncPredictedSlot();
	}
	return Out;
}

FVector UVerseWeaponComponent::ServerEye(double ViewTime) const
{
	if (RewoundEyeOverride)
	{
		return RewoundEyeOverride(ViewTime);
	}
	const AActor* Owner = GetOwner();
	if (!Owner)
	{
		return FVector::ZeroVector;
	}
	const APawn* Pawn = Cast<APawn>(Owner);
	const FVector CurrentEye = Pawn ? Pawn->GetPawnViewLocation() : Owner->GetActorLocation();
	const UVerseLagCompSubsystem* Lag = UVerseLagCompSubsystem::Get(this);
	FVerseHitBodyPose Pose;
	const double Now = VerseCombatEvents::ServerTime(this);
	if (Lag && Lag->GetPoseAt(Owner, UVerseLagCompSubsystem::ClampRewindTime(Now, ViewTime), Pose))
	{
		return Pose.Root.GetLocation() + (CurrentEye - Owner->GetActorLocation());
	}
	return CurrentEye;
}

FVector UVerseWeaponComponent::ServerForward() const
{
	if (ServerForwardOverride)
	{
		return ServerForwardOverride();
	}
	const APawn* Pawn = Cast<APawn>(GetOwner());
	return Pawn ? Pawn->GetBaseAimRotation().Vector() : (GetOwner() ? GetOwner()->GetActorForwardVector() : FVector::ForwardVector);
}

EVerseShotResult UVerseWeaponComponent::HandleServerFire(uint16 ShotCounter, uint32 Seed, const FVector& Origin, const FVector& Dir,
	float ClientServerTime)
{
	AActor* Owner = GetOwner();
	if (!Owner || !Owner->HasAuthority())
	{
		return EVerseShotResult::Rejected;
	}
	auto Reject = [this, ShotCounter]()
	{
		ClientConfirmShot(ShotCounter, EVerseShotResult::Rejected, EVerseHitZone::None, false);
		return EVerseShotResult::Rejected;
	};

	const float Now = VerseCombatEvents::ServerTime(this);
	UVerseInventoryComponent* Inv = GetInventory();
	const UVerseWeaponDefinition* W = GetActiveDefinition();
	if (!Inv || !W)
	{
		return Reject();
	}
	UVerseCombatStateComponent* State = UVerseCombatStateComponent::FindOn(Owner);
	if (State && State->Phase != EVerseCombatPhase::Alive)
	{
		return Reject(); // dead, or locked in a finisher
	}
	const IVerseMovementQuery& Move = MovementOf(Owner);
	if (Move.BlocksFiring())
	{
		return Reject();
	}
	// The client's predicted server time: never ahead of the server clock, never far behind it.
	if (!FMath::IsFinite(ClientServerTime) || ClientServerTime > Now + MaxClientLeadS || ClientServerTime < Now - MaxClientLagS)
	{
		return Reject();
	}
	// Cadence on the client's clock (the owner's shots arrive in order); 1 ms grace.
	if (ClientServerTime + 0.001f < ServerLastShotClientTime + W->FireInterval())
	{
		return Reject();
	}
	// Cadence on the server's clock: no more shots than elapsed server time allows, plus a small burst
	// for requests that arrive bunched. Forged client times cannot raise the rate.
	const float Interval = FMath::Max(W->FireInterval(), 1e-3f);
	if (ServerBudgetTime >= 0.f)
	{
		ServerShotBudget = FMath::Min(ServerBurstShots, ServerShotBudget + FMath::Max(0.f, Now - ServerBudgetTime) / Interval);
	}
	ServerBudgetTime = Now;
	if (ServerShotBudget < 1.f - 1e-3f)
	{
		return Reject();
	}
	if (Seed != FVerseSpread::ShotSeed(uint32(GetShooterId()), ShotCounter, MatchSeed))
	{
		return Reject();
	}

	// The server's own recoil and spread for this shot (R5, 4.4), on the client's shot time. Every
	// request that passed the clock checks was really fired by the owner, so the simulation advances
	// even when the shot is rejected below; counter gaps (lost requests) advance it too.
	FVerseSpreadInput In;
	In.Stance = Move.GetStance();
	In.AdsBlend = GetAdsBlend01();
	In.bAirborne = Move.IsAirborne();
	In.HorizontalSpeedMps = float(Owner->GetVelocity().Size2D() / 100.0);
	const uint16 Gap = uint16(ShotCounter - ServerLastCounter - 1);
	ServerRecoil.BeginShot(*W, ClientServerTime);
	if (Gap > 0 && Gap < 16 && ServerRecoil.ShotIndex > 0)
	{
		ServerRecoil.ShotIndex += Gap;
		ServerSpread.Bloom = FMath::Min(W->BloomMax, ServerSpread.Bloom + Gap * W->BloomPerShot);
	}
	ServerSpread.DecayUntilShot(*W, ClientServerTime);
	const float Sigma = ServerSpread.SigmaFor(*W, In, ClientServerTime);
	const int32 ShotIndex = ServerRecoil.ShotIndex;
	const FVector2f Kick = ServerRecoil.KickFor(*W, FVerseRecoilState::Multiplier(*W, In.Stance, In.AdsBlend), Seed);
	ServerRecoil.OnShot(Kick, ClientServerTime);
	ServerSpread.OnShot(*W, ClientServerTime);
	ServerLastCounter = ShotCounter;
	ServerLastShotClientTime = ClientServerTime;
	ServerShotBudget -= 1.f;
	LastServerKick = Kick;
	LastServerSigma = Sigma;
	LastServerShotIndex = ShotIndex;

	if (bServerValidates)
	{
		const FVector Forward = ServerForward();
		if (!FVerseSpread::ValidateFire(Origin, Dir, ServerEye(ClientServerTime), Forward, Sigma) ||
			!FVerseSpread::ValidateDirection(Dir, Forward, Sigma, Seed, ShotIndex))
		{
			return Reject();
		}
	}
	if (!Inv->ServerConsumeRound(Now))
	{
		return Reject();
	}

	if (State)
	{
		State->NotifyOffensiveAction(Now);
	}
	if (UVerseDamageService* Damage = UVerseDamageService::Get(this))
	{
		if (Damage->Rules.OnOffensiveAction)
		{
			Damage->Rules.OnOffensiveAction(Owner, EVerseDamageSource::Bolt);
		}
	}

	FVerseFireEvent E;
	E.ShooterId = GetShooterId();
	E.WeaponId = W->WeaponId;
	E.ShotCounter = ShotCounter;
	E.Seed = Seed;
	E.Origin = Origin;
	E.Direction = Dir.GetSafeNormal();
	E.ServerTime = Now;

	VerseCombatEvents::RaiseFire(this, E);
	VerseCombatEvents::RaiseNoise(this, VerseTags::Noise_Shot, E.ShooterId, Origin, 1.f);
	MulticastFire(E);

	if (UVerseProjectileManager* Manager = UVerseProjectileManager::Get(this))
	{
		// The latency advance comes from the validated client time and is capped at 250 ms by the manager.
		Manager->SpawnBoltFrom(E, *W, FMath::Clamp(Now - ClientServerTime, 0.f, UVerseProjectileManager::MaxLatencyS), Owner);
	}
	return EVerseShotResult::Miss;
}

void UVerseWeaponComponent::HandleBoltResolved(const FVerseBoltResult& Result)
{
	ClientConfirmShot(Result.ShotCounter, Result.Result, Result.Zone, Result.bKillingBlow);
}

void UVerseWeaponComponent::HandleConfirm(uint16 ShotCounter, EVerseShotResult Result)
{
	const FVerseShotReconcile R = Predictor.Confirm(ShotCounter, Result);
	const UVerseWeaponDefinition* W = GetActiveDefinition();
	const AActor* Owner = GetOwner();
	if (R.RefundRounds > 0 && W && Owner && !Owner->HasAuthority())
	{
		FVerseMagazine::RefundRound(PredictedSlot, *W);
	}
	OnShotAnswered.Broadcast(ShotCounter, Result);
	if (Result == EVerseShotResult::Rejected)
	{
		OnAnyShotRejected.Broadcast(GetShooterId(), ShotCounter);
	}
}

void UVerseWeaponComponent::ServerFire_Implementation(uint16 ShotCounter, uint32 Seed, FVector_NetQuantize10 Origin,
	FVector_NetQuantizeNormal Dir, float ClientServerTime)
{
	HandleServerFire(ShotCounter, Seed, Origin, Dir, ClientServerTime);
}

void UVerseWeaponComponent::ClientConfirmShot_Implementation(uint16 ShotCounter, EVerseShotResult Result, EVerseHitZone,
	bool)
{
	HandleConfirm(ShotCounter, Result);
}

void UVerseWeaponComponent::MulticastFire_Implementation(const FVerseFireEvent& E)
{
	const AActor* Owner = GetOwner();
	if (!Owner || Owner->HasAuthority() || IsLocalOwner(Owner))
	{
		return; // the server raised it; the owner predicted it
	}
	VerseCombatEvents::RaiseFire(this, E);
}

void UVerseWeaponComponent::RaiseLocalImpact(const UObject* WorldContext, const FVerseHitEvent& Impact)
{
	const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
	if (!World || World->GetNetMode() == NM_DedicatedServer)
	{
		return;
	}
	if (UVerseEventHub* Hub = UVerseEventHub::Get(WorldContext))
	{
		Hub->OnHit.Broadcast(Impact);
	}
}

void UVerseWeaponComponent::MulticastHitCosmetic_Implementation(const FVerseHitEvent& E)
{
	const AActor* Owner = GetOwner();
	if (!Owner)
	{
		return;
	}
	if (Owner->HasAuthority())
	{
		// Body hits reached the server's hub through the damage service; world, piece and Bulwark
		// impacts reach a listen-server or standalone viewer here.
		if (E.VictimId == -1)
		{
			RaiseLocalImpact(this, E);
		}
		return;
	}
	// The victim's owner gets the reliable copy instead.
	if (const UWorld* World = GetWorld())
	{
		for (FConstPlayerControllerIterator It = World->GetPlayerControllerIterator(); It; ++It)
		{
			const APlayerController* Pc = It->Get();
			if (Pc && Pc->IsLocalController() && VerseCombatIds::IdOf(Pc->GetPawn()) == E.VictimId && E.VictimId != -1)
			{
				return;
			}
		}
	}
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnHit.Broadcast(E);
	}
}

void UVerseWeaponComponent::MulticastPenetration_Implementation(const FVersePenetrationEvent& E)
{
	const AActor* Owner = GetOwner();
	if (!Owner || Owner->HasAuthority())
	{
		return;
	}
	VerseCombatEvents::RaisePenetration(this, E);
}

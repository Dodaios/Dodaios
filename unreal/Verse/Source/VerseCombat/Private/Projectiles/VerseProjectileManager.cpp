#include "Projectiles/VerseProjectileManager.h"

#include "Combat/VerseWeaponDefinition.h"
#include "Damage/VerseDamageMath.h"
#include "Damage/VerseDamageService.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Destruction/VersePenetrationTable.h"
#include "Engine/World.h"
#include "Gadgets/VerseBulwark.h"
#include "HAL/PlatformTime.h"
#include "LagComp/VerseLagCompensation.h"
#include "Stubs/VerseNullStubs.h"
#include "VerseCollision.h"
#include "Weapons/VerseCombatEvents.h"
#include "Weapons/VerseWeaponComponent.h"

UVerseProjectileManager* UVerseProjectileManager::Get(const UObject* WorldContextObject)
{
	const UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UVerseProjectileManager>() : nullptr;
}

void UVerseProjectileManager::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
}

void UVerseProjectileManager::Deinitialize()
{
	Bolts.Reset();
	Super::Deinitialize();
}

TStatId UVerseProjectileManager::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseProjectileManager, STATGROUP_Tickables);
}

double UVerseProjectileManager::Now() const
{
	return ClockOverride ? ClockOverride() : double(VerseCombatEvents::ServerTime(this));
}

void UVerseProjectileManager::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	const UWorld* World = GetWorld();
	if (bManualStepping || !World || World->GetNetMode() == NM_Client || Bolts.Num() == 0)
	{
		return;
	}
	StepAll(DeltaTime, Now());
}

bool UVerseProjectileManager::TraceWorld(const FVector& Start, const FVector& End, const AActor* Ignore, FHitResult& Out) const
{
	if (WorldTrace)
	{
		return WorldTrace(Start, End, Ignore, Out);
	}
	const UWorld* World = GetWorld();
	if (!World)
	{
		return false;
	}
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseBolt), false, Ignore);
	return World->LineTraceSingleByChannel(Out, Start, End, VerseCollision::Bolt, Params);
}

void UVerseProjectileManager::SpawnBolt(const FVerseFireEvent& Fire, const UVerseWeaponDefinition& Weapon, float LatencyS)
{
	SpawnBoltFrom(Fire, Weapon, LatencyS, nullptr);
}

void UVerseProjectileManager::SpawnBoltFrom(const FVerseFireEvent& Fire, const UVerseWeaponDefinition& Weapon, float LatencyS,
	AActor* Shooter)
{
	const UWorld* World = GetWorld();
	if (World && World->GetNetMode() == NM_Client)
	{
		return;
	}
	FVerseBolt Bolt;
	Bolt.Fire = Fire;
	Bolt.Weapon = &Weapon;
	Bolt.Shooter = Shooter;
	Bolt.Position = Fire.Origin;
	Bolt.Dir = FVector(Fire.Direction).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
	Bolt.Power = Weapon.PenetrationPower;

	// The first step covers the shooter's latency (capped), against bodies rewound to the time the
	// bolt was at each point of it: one tick-sized segment at a time.
	const double Latency = FMath::Clamp(double(LatencyS), 0.0, double(MaxLatencyS));
	const double Speed = Weapon.ProjectileSpeed * 100.0;
	const double Clock = Now();
	Bolt.Time = Clock - Latency;
	double Remaining = Latency;
	while (Bolt.bAlive && Remaining > 1e-6)
	{
		const double Dt = FMath::Min(double(ServerStepS), Remaining);
		const double PoseTime = Bolt.Time + Dt;
		StepBolt(Bolt, Speed * Dt, PoseTime, Bolt.Time + Dt);
		Remaining -= Dt;
	}
	if (Bolt.bAlive)
	{
		Bolt.Time = Clock;
		Bolts.Add(MoveTemp(Bolt));
	}
}

void UVerseProjectileManager::StepAll(float Dt, double InNow)
{
	const double T0 = FPlatformTime::Seconds();
	for (FVerseBolt& Bolt : Bolts)
	{
		if (!Bolt.bAlive)
		{
			continue;
		}
		const UVerseWeaponDefinition* W = Bolt.Weapon.Get();
		if (!W)
		{
			Bolt.bAlive = false;
			continue;
		}
		StepBolt(Bolt, W->ProjectileSpeed * 100.0 * Dt, -1.0, InNow);
	}
	Bolts.RemoveAll([](const FVerseBolt& B) { return !B.bAlive; });
	LastStepSeconds = FPlatformTime::Seconds() - T0;
}

void UVerseProjectileManager::Resolve(FVerseBolt& Bolt, EVerseShotResult Result, EVerseHitZone Zone, bool bKillingBlow,
	AActor* HitActor, const FVector& Where)
{
	Bolt.bAlive = false;
	FVerseBoltResult R;
	R.Shooter = Bolt.Shooter;
	R.WeaponId = Bolt.Fire.WeaponId;
	R.ShotCounter = Bolt.Fire.ShotCounter;
	R.Result = Result;
	R.Zone = Zone;
	R.bKillingBlow = bKillingBlow;
	R.HitActor = HitActor;
	R.Location = Where;
	R.Travelled = Bolt.Travelled + FVector::Dist(Bolt.Position, Where);
	R.Time = Bolt.Time;
	if (UVerseWeaponComponent* Weapon = UVerseWeaponComponent::FindOn(Bolt.Shooter.Get()))
	{
		Weapon->HandleBoltResolved(R);
	}
	OnBoltResolved.Broadcast(R);
}

void UVerseProjectileManager::StepBolt(FVerseBolt& Bolt, double Len, double PoseTime, double EndTime)
{
	const UVerseWeaponDefinition* W = Bolt.Weapon.Get();
	if (!W)
	{
		Bolt.bAlive = false;
		return;
	}
	const double MaxRangeCm = double(W->MaxRange) * 100.0;
	Len = FMath::Min(Len, MaxRangeCm - Bolt.Travelled);
	if (Len <= 0.0)
	{
		Resolve(Bolt, EVerseShotResult::Miss, EVerseHitZone::None, false, nullptr, Bolt.Position);
		return;
	}

	AActor* Shooter = Bolt.Shooter.Get();
	const FVector P0 = Bolt.Position;
	const FVector P1 = P0 + Bolt.Dir * Len;

	// Hit bodies: rewound for the latency segments, current otherwise.
	FVerseRewindHit Body;
	bool bBody = false;
	if (const UVerseLagCompSubsystem* Lag = UVerseLagCompSubsystem::Get(this))
	{
		bBody = Lag->TraceAt(P0, P1, PoseTime >= 0.0 ? PoseTime : EndTime, Shooter, Body);
	}

	// World and Bulwarks on VerseBolt.
	FHitResult WorldHit;
	bool bWorld = TraceWorld(P0, P1, Shooter, WorldHit);
	double WorldDist = bWorld ? WorldHit.Distance : 0.0;
	if (bWorld && WorldDist <= 0.0)
	{
		WorldDist = FVector::Dist(P0, FVector(WorldHit.ImpactPoint));
	}

	// Pieces (current-state proxies), in order.
	const IVersePenetrationQuery* Query = PenetrationQuery ? PenetrationQuery : GetDefault<UVerseNullPenetrationQuery>();
	const int32 MaxPasses = W->GetEffectiveMaxPenetrations();
	const float DistanceSoFarM = float(Bolt.Travelled / 100.0);
	const float DamageNow = FVerseDamageMath::BoltDamage(*W, EVerseHitZone::UpperTorso, DistanceSoFarM, Bolt.Factor);
	const TArray<FVersePenetrationHit> Pieces =
		Query->TraceBolt(P0, Bolt.Dir, float(Len), Bolt.Power, DamageNow, W->HoleRadiusMm, FMath::Max(1, MaxPasses - Bolt.Passes + 1));
	const UVersePenetrationTable* Table = PenetrationTable ? PenetrationTable : GetDefault<UVersePenetrationTable>();
	IVersePieceDamage* Damage = PieceDamage ? PieceDamage : static_cast<IVersePieceDamage*>(GetMutableDefault<UVerseNullPieceDamage>());
	UVerseWeaponComponent* ShooterWeapon = UVerseWeaponComponent::FindOn(Shooter);
	UVerseDamageService* DamageService = UVerseDamageService::Get(this);

	auto HitBody = [&]()
	{
		AActor* Victim = Body.Actor.Get();
		const float DistanceM = float((Bolt.Travelled + Body.Distance) / 100.0);
		FVerseHitEvent Hit;
		Hit.WeaponId = W->WeaponId;
		Hit.Source = EVerseDamageSource::Bolt;
		Hit.ShotCounter = Bolt.Fire.ShotCounter;
		Hit.Zone = Body.Zone;
		Hit.Bone = Body.Bone;
		Hit.ImpactWorld = Body.ImpactWorld;
		Hit.ImpactBoneLocal = Body.ImpactBoneLocal;
		Hit.Direction = Bolt.Dir;
		Hit.DistanceM = DistanceM;
		Hit.Damage = FVerseDamageMath::BoltDamage(*W, Body.Zone, DistanceM, Bolt.Factor);
		Hit.PenetrationCount = uint8(FMath::Clamp(Bolt.Passes, 0, 255));
		if (DamageService)
		{
			DamageService->ApplyHit(Shooter, Victim, Hit);
		}
		else
		{
			Hit.InstigatorId = VerseCombatIds::IdOf(Shooter);
			Hit.VictimId = VerseCombatIds::IdOf(Victim);
		}
		if (ShooterWeapon)
		{
			ShooterWeapon->MulticastHitCosmetic(Hit);
		}
		const EVerseShotResult Result = Hit.bBlockedBySpawnProtection ? EVerseShotResult::Blocked : EVerseShotResult::HitBody;
		Resolve(Bolt, Result, Body.Zone, Hit.bKillingBlow != 0, Victim, Body.ImpactWorld);
	};

	auto HitWorld = [&]()
	{
		const FVector Where = FVector(WorldHit.ImpactPoint);
		const float DistanceM = float((Bolt.Travelled + WorldDist) / 100.0);
		if (AVerseBulwark* Bulwark = Cast<AVerseBulwark>(WorldHit.GetActor()))
		{
			// The damage after all factors goes to the field; a Bulwark never lets a bolt through.
			Bulwark->ApplyBoltDamage(W->BaseDamage * FVerseDamageMath::Falloff(*W, DistanceM) * Bolt.Factor, Shooter);
			Resolve(Bolt, EVerseShotResult::Blocked, EVerseHitZone::None, false, Bulwark, Where);
			return;
		}
		// Impact VFX on clients come from this cosmetic copy (victim -1, zone None); it carries no damage.
		if (ShooterWeapon)
		{
			FVerseHitEvent Impact;
			Impact.InstigatorId = VerseCombatIds::IdOf(Shooter);
			Impact.VictimId = -1;
			Impact.WeaponId = W->WeaponId;
			Impact.ShotCounter = Bolt.Fire.ShotCounter;
			Impact.ImpactWorld = Where;
			Impact.Direction = Bolt.Dir;
			Impact.DistanceM = DistanceM;
			Impact.ServerTime = float(EndTime);
			ShooterWeapon->MulticastHitCosmetic(Impact);
		}
		Resolve(Bolt, EVerseShotResult::Miss, EVerseHitZone::None, false, WorldHit.GetActor(), Where);
	};

	for (const FVersePenetrationHit& Piece : Pieces)
	{
		if (Bolt.PassedPieces.Contains(Piece.PieceIndex))
		{
			continue;
		}
		const double PieceDist = FVector::Dist(P0, Piece.Entry);
		if (bBody && Body.Distance < PieceDist)
		{
			HitBody();
			return;
		}
		if (bWorld && WorldDist < PieceDist - 1.0)
		{
			HitWorld();
			return;
		}

		// Piece damage always, pass or not (server).
		FVersePieceDamage PieceHit;
		PieceHit.PieceIndex = Piece.PieceIndex;
		PieceHit.Amount = W->PieceDamage;
		PieceHit.Cause = EVerseFractureCause::Bolt;
		PieceHit.Location = Piece.Entry;
		PieceHit.Direction = Bolt.Dir;
		PieceHit.InstigatorId = VerseCombatIds::IdOf(Shooter);
		Damage->ApplyPieceDamage(PieceHit);

		const FVersePenetrationRow* Row = Table->FindRow(Piece.MaterialWireId);
		const float Cost = Row ? UVersePenetrationTable::PassCost(*Row, Piece.TracedThicknessCm) : TNumericLimits<float>::Max();
		if (Bolt.Power < Cost || Bolt.Passes >= MaxPasses)
		{
			Resolve(Bolt, EVerseShotResult::HitPiece, EVerseHitZone::None, false, nullptr, Piece.Entry);
			return;
		}
		FVersePenetrationEvent Pen;
		Pen.ShooterId = VerseCombatIds::IdOf(Shooter);
		Pen.ShotCounter = Bolt.Fire.ShotCounter;
		Pen.PieceIndex = Piece.PieceIndex;
		Pen.MaterialWireId = Piece.MaterialWireId;
		Pen.Entry = Piece.Entry;
		Pen.Exit = Piece.Exit;
		Pen.ThicknessCm = Piece.TracedThicknessCm;
		Pen.PowerBefore = Bolt.Power;
		Bolt.Power -= Cost;
		Bolt.Factor *= Row->DamageMultiplier;
		Bolt.Passes += 1;
		Bolt.PassedPieces.Add(Piece.PieceIndex);
		Pen.PowerAfter = Bolt.Power;
		Pen.DamageFactorAfter = Bolt.Factor;
		Pen.bPassed = true;
		VerseCombatEvents::RaisePenetration(this, Pen);
		if (ShooterWeapon)
		{
			ShooterWeapon->MulticastPenetration(Pen);
		}

		// The world trace may have stopped on this piece's own proxy: look again behind its exit.
		const double ExitDist = FVector::Dist(P0, Piece.Exit);
		if (bWorld && WorldDist <= ExitDist + 1.0)
		{
			const FVector Behind = Piece.Exit + Bolt.Dir * 0.5;
			bWorld = ExitDist + 0.5 < Len && TraceWorld(Behind, P1, Shooter, WorldHit);
			WorldDist = bWorld ? ExitDist + 0.5 + FVector::Dist(Behind, FVector(WorldHit.ImpactPoint)) : 0.0;
		}
	}

	if (bBody && (!bWorld || Body.Distance <= WorldDist))
	{
		HitBody();
		return;
	}
	if (bWorld)
	{
		HitWorld();
		return;
	}

	Bolt.Position = P1;
	Bolt.Travelled += Len;
	Bolt.Time = EndTime;
	if (Bolt.Travelled >= MaxRangeCm - 0.01)
	{
		Resolve(Bolt, EVerseShotResult::Miss, EVerseHitZone::None, false, nullptr, Bolt.Position);
	}
}

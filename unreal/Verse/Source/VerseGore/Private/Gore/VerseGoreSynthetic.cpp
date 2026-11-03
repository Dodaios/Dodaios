#include "Gore/VerseGoreSynthetic.h"

#include "VerseRng.h"

namespace VerseGoreSyntheticPrivate
{
	/** Zone weights of a synthetic hit (torso heavy, as rifle fire at a standing body is). */
	struct FZoneWeight
	{
		EVerseHitZone Zone;
		double Weight;
		float Damage;
	};

	constexpr FZoneWeight ZoneWeights[] = {
		{EVerseHitZone::Head, 0.12, 60.f},
		{EVerseHitZone::Neck, 0.06, 40.f},
		{EVerseHitZone::UpperTorso, 0.34, 30.f},
		{EVerseHitZone::LowerTorso, 0.20, 27.f},
		{EVerseHitZone::Arm, 0.14, 22.f},
		{EVerseHitZone::Leg, 0.14, 22.f},
	};

	EVerseHitZone PickZone(FVerseRng& Rng, float& OutDamage)
	{
		double Roll = Rng.NextUnit();
		for (const FZoneWeight& Entry : ZoneWeights)
		{
			if (Roll < Entry.Weight)
			{
				OutDamage = Entry.Damage;
				return Entry.Zone;
			}
			Roll -= Entry.Weight;
		}
		OutDamage = ZoneWeights[2].Damage;
		return EVerseHitZone::UpperTorso;
	}
}

FName FVerseGoreSyntheticStream::BoneForZone(EVerseHitZone Zone)
{
	switch (Zone)
	{
	case EVerseHitZone::Head: return TEXT("Head");
	case EVerseHitZone::Neck: return TEXT("Neck");
	case EVerseHitZone::UpperTorso: return TEXT("Spine_03");
	case EVerseHitZone::LowerTorso: return TEXT("Spine_01");
	case EVerseHitZone::Arm: return TEXT("UpperArm_R");
	case EVerseHitZone::Leg: return TEXT("Thigh_L");
	default: return NAME_None;
	}
}

double FVerseGoreSyntheticStream::HeightForZone(EVerseHitZone Zone)
{
	switch (Zone)
	{
	case EVerseHitZone::Head: return 168.0;
	case EVerseHitZone::Neck: return 152.0;
	case EVerseHitZone::UpperTorso: return 132.0;
	case EVerseHitZone::LowerTorso: return 104.0;
	case EVerseHitZone::Arm: return 128.0;
	case EVerseHitZone::Leg: return 62.0;
	default: return 120.0;
	}
}

FVerseHitEvent FVerseGoreSyntheticStream::MakeHit(EVerseHitZone Zone, const FVector& VictimLocation, const FVector& ShooterLocation,
	int32 InstigatorId, int32 VictimId, float Damage, uint16 ShotCounter, float ServerTime, bool bKillingBlow)
{
	FVerseHitEvent Hit;
	Hit.InstigatorId = InstigatorId;
	Hit.VictimId = VictimId;
	Hit.WeaponId = TEXT("synthetic_rifle");
	Hit.Source = EVerseDamageSource::Bolt;
	Hit.ShotCounter = ShotCounter;
	Hit.Zone = Zone;
	Hit.Bone = BoneForZone(Zone);

	FVerseRng Rng(uint64(VictimId) << 32 | ShotCounter, ShotCounter, EVerseRngSalt::Harness);
	const double Side = Zone == EVerseHitZone::Arm ? 24.0 : Rng.Range(-9.0, 9.0);
	const FVector Impact = VictimLocation + FVector(Rng.Range(-6.0, 6.0), Side, HeightForZone(Zone) + Rng.Range(-5.0, 5.0));
	Hit.ImpactWorld = FVector_NetQuantize10(Impact);
	Hit.ImpactBoneLocal = FVector_NetQuantize10(FVector(Rng.Range(-6.0, 6.0), Rng.Range(-6.0, 6.0), Rng.Range(-4.0, 8.0)));
	const FVector Dir = (Impact - ShooterLocation).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
	Hit.Direction = FVector_NetQuantizeNormal(Dir);
	Hit.DistanceM = float(FVector::Dist(Impact, ShooterLocation) / 100.0);
	Hit.Damage = Damage;
	Hit.bHeadshot = Zone == EVerseHitZone::Head ? 1 : 0;
	Hit.bKillingBlow = bKillingBlow ? 1 : 0;
	Hit.ServerTime = ServerTime;
	return Hit;
}

bool FVerseGoreSyntheticStream::ParseKind(const FString& Text, EVerseGoreSyntheticKind& OutKind)
{
	if (Text.Equals(TEXT("hits"), ESearchCase::IgnoreCase) || Text.Equals(TEXT("hit"), ESearchCase::IgnoreCase))
	{
		OutKind = EVerseGoreSyntheticKind::Hits;
	}
	else if (Text.Equals(TEXT("deaths"), ESearchCase::IgnoreCase) || Text.Equals(TEXT("death"), ESearchCase::IgnoreCase))
	{
		OutKind = EVerseGoreSyntheticKind::Deaths;
	}
	else if (Text.Equals(TEXT("finisher"), ESearchCase::IgnoreCase))
	{
		OutKind = EVerseGoreSyntheticKind::Finisher;
	}
	else if (Text.Equals(TEXT("storm"), ESearchCase::IgnoreCase) || Text.Equals(TEXT("gore_storm"), ESearchCase::IgnoreCase))
	{
		OutKind = EVerseGoreSyntheticKind::Storm;
	}
	else
	{
		return false;
	}
	return true;
}

TArray<FVerseGoreSyntheticEvent> FVerseGoreSyntheticStream::Build(const FVerseGoreSyntheticParams& Params)
{
	using namespace VerseGoreSyntheticPrivate;
	TArray<FVerseGoreSyntheticEvent> Events;
	FVerseRng Rng(Params.Seed, 0, EVerseRngSalt::Harness);

	if (Params.Kind == EVerseGoreSyntheticKind::Finisher)
	{
		const EVerseFinisherPhase Phases[] = {EVerseFinisherPhase::Locked, EVerseFinisherPhase::Takedown,
			EVerseFinisherPhase::Struggle, EVerseFinisherPhase::Kill, EVerseFinisherPhase::Recover};
		const double Offsets[] = {0.0, VerseGoreFinisherTimes::Takedown, VerseGoreFinisherTimes::Struggle,
			VerseGoreFinisherTimes::Kill, VerseGoreFinisherTimes::Recover};
		const FVector Behind = Params.VictimLocation - FVector(80.0, 0.0, 0.0);
		for (int32 Index = 0; Index < UE_ARRAY_COUNT(Phases); ++Index)
		{
			FVerseGoreSyntheticEvent Event;
			Event.Time = Offsets[Index];
			Event.Type = FVerseGoreSyntheticEvent::EType::Finisher;
			Event.Finisher.AttackerId = Params.InstigatorId;
			Event.Finisher.VictimId = Params.VictimId;
			Event.Finisher.Phase = Phases[Index];
			Event.Finisher.SequenceStartServerTime = 0.f;
			Event.Finisher.WarpTarget = FTransform(FRotator::ZeroRotator, Behind);
			Events.Add(Event);
			if (Phases[Index] == EVerseFinisherPhase::Kill)
			{
				FVerseGoreSyntheticEvent Death;
				Death.Time = Offsets[Index];
				Death.Type = FVerseGoreSyntheticEvent::EType::Death;
				Death.Death.VictimId = Params.VictimId;
				Death.Death.KillerId = Params.InstigatorId;
				Death.Death.Cause = EVerseDamageSource::Finisher;
				Death.Death.LastZone = EVerseHitZone::Neck;
				Death.Death.ServerTime = float(Offsets[Index]);
				Death.Death.RespawnAt = float(Offsets[Index] + 3.0);
				Events.Add(Death);
			}
		}
		return Events;
	}

	const double Rate = Params.Kind == EVerseGoreSyntheticKind::Storm ? 30.0 : FMath::Max(0.1, Params.RatePerSecond);
	const int32 Count = FMath::Max(1, FMath::FloorToInt32(Params.DurationSeconds * Rate));
	for (int32 Index = 0; Index < Count; ++Index)
	{
		const double Time = Index / Rate;
		float Damage = 30.f;
		const EVerseHitZone Zone = PickZone(Rng, Damage);
		const bool bKill = Params.Kind == EVerseGoreSyntheticKind::Deaths;
		// Shooter wanders on a 6 m arc so bolt directions vary.
		const double Angle = Rng.Range(-0.6, 0.6);
		const FVector Offset = Params.ShooterLocation - Params.VictimLocation;
		const FVector Shooter = Params.VictimLocation + Offset.RotateAngleAxisRad(Angle, FVector::UpVector);

		FVerseGoreSyntheticEvent Event;
		Event.Time = Time;
		Event.Type = FVerseGoreSyntheticEvent::EType::Hit;
		Event.Hit = MakeHit(Zone, Params.VictimLocation, Shooter, Params.InstigatorId, Params.VictimId,
			bKill ? 100.f : Damage, uint16(Index + 1), float(Time), bKill);
		Events.Add(Event);

		if (bKill)
		{
			FVerseGoreSyntheticEvent Death;
			Death.Time = Time;
			Death.Type = FVerseGoreSyntheticEvent::EType::Death;
			Death.Death.VictimId = Params.VictimId;
			Death.Death.KillerId = Params.InstigatorId;
			Death.Death.Cause = EVerseDamageSource::Bolt;
			Death.Death.LastZone = Zone;
			Death.Death.ServerTime = float(Time);
			Death.Death.RespawnAt = float(Time + 3.0);
			Events.Add(Death);
		}
	}
	return Events;
}

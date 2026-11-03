#include "Damage/VerseDamageMath.h"

#include "Combat/VerseWeaponDefinition.h"

float FVerseDamageMath::Falloff(const UVerseWeaponDefinition& W, float DistanceM)
{
	const float D = FMath::Max(0.f, DistanceM);
	if (D <= W.FalloffStart)
	{
		return 1.f;
	}
	if (D >= W.FalloffEnd || W.FalloffEnd <= W.FalloffStart)
	{
		return W.FalloffMinFraction;
	}
	const float T = (D - W.FalloffStart) / (W.FalloffEnd - W.FalloffStart);
	return FMath::Lerp(1.f, W.FalloffMinFraction, T);
}

float FVerseDamageMath::ZoneMultiplier(const UVerseWeaponDefinition& W, EVerseHitZone Zone)
{
	if (Zone == EVerseHitZone::None)
	{
		return 0.f;
	}
	const float* Found = W.ZoneMultipliers.Find(Zone);
	return Found ? *Found : 1.f;
}

float FVerseDamageMath::BoltDamage(const UVerseWeaponDefinition& W, EVerseHitZone Zone, float DistanceM, float PenetrationFactor)
{
	return W.BaseDamage * ZoneMultiplier(W, Zone) * Falloff(W, DistanceM) * FMath::Max(0.f, PenetrationFactor);
}

FVerseDamageSplit FVerseDamageMath::Split(float Damage, float Health, float Armor, float MaxArmor)
{
	FVerseDamageSplit Out;
	const float D = FMath::Max(0.f, Damage);
	Out.ToArmor = (MaxArmor > 0.f) ? FMath::Min(FMath::Max(0.f, Armor), D) : 0.f;
	Out.ToHealth = D - Out.ToArmor;
	Out.ArmorAfter = FMath::Max(0.f, Armor - Out.ToArmor);
	Out.HealthAfter = FMath::Max(0.f, Health - Out.ToHealth);
	Out.bKilled = Health > 0.f && Out.HealthAfter <= 0.f;
	return Out;
}

int32 FVerseDamageMath::HitsToKill(const UVerseWeaponDefinition& W, EVerseHitZone Zone, float DistanceM, float MaxHealth)
{
	const float D = BoltDamage(W, Zone, DistanceM, 1.f);
	if (D <= 0.f)
	{
		return MAX_int32;
	}
	// A tiny epsilon keeps exact multiples (4 x 25 = 100) at the lower count.
	return FMath::CeilToInt((MaxHealth - 1e-4f) / D);
}

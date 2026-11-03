#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

class UVerseWeaponDefinition;

/** Result of applying damage to health and armor (armor absorbs first, combat-state.md 5). */
struct FVerseDamageSplit
{
	float ToArmor = 0.f;
	float ToHealth = 0.f;
	float HealthAfter = 0.f;
	float ArmorAfter = 0.f;
	bool bKilled = false;
};

/** The damage formula of combat-state.md 5. Pure; the damage service and the tests share it. */
struct VERSECOMBAT_API FVerseDamageMath
{
	/** 1 up to FalloffStart, linear to FalloffMinFraction at FalloffEnd, FalloffMinFraction beyond. */
	static float Falloff(const UVerseWeaponDefinition& W, float DistanceM);

	/** ZoneMultipliers[zone]; 1.0 when the zone has no entry, 0 for None. */
	static float ZoneMultiplier(const UVerseWeaponDefinition& W, EVerseHitZone Zone);

	/** D = BaseDamage * ZoneMultipliers[zone] * falloff(distance) * penetration_factor */
	static float BoltDamage(const UVerseWeaponDefinition& W, EVerseHitZone Zone, float DistanceM, float PenetrationFactor);

	/** Armor first (when MaxArmor > 0), the rest to health. */
	static FVerseDamageSplit Split(float Damage, float Health, float Armor, float MaxArmor);

	/** Hits of BoltDamage(zone, distance) needed to take MaxHealth to 0. */
	static int32 HitsToKill(const UVerseWeaponDefinition& W, EVerseHitZone Zone, float DistanceM, float MaxHealth);
};

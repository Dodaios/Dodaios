#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Curves/CurveFloat.h"
#include "Engine/DataAsset.h"

#include "VerseWeaponDefinition.generated.h"

/**
 * One firearm (combat-state.md 3), one asset per weapon (DA_Weapon_<Name>). The JSON export in
 * unreal/Verse/Data/weapons/ is the merge surface. Field names, types and units are frozen;
 * the defaults below are placeholders, the start values live in the data.
 * Data units: metres, m/s, seconds, degrees.
 */
UCLASS(BlueprintType)
class VERSECORE_API UVerseWeaponDefinition : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	/** The contract cap on pieces a bolt may pass (destruction.md 2). */
	static constexpr int32 MaxPenetrationsCap = 3;

	UPROPERTY(EditDefaultsOnly, Category = "Identity")
	FName WeaponId;

	/** Fictional name only. */
	UPROPERTY(EditDefaultsOnly, Category = "Identity")
	FText DisplayName;

	UPROPERTY(EditDefaultsOnly, Category = "Identity")
	EVerseLoadoutSlot Slot = EVerseLoadoutSlot::Primary;

	UPROPERTY(EditDefaultsOnly, Category = "Fire")
	EVerseFireMode FireMode = EVerseFireMode::Auto;

	/** Rounds per burst (Burst only). */
	UPROPERTY(EditDefaultsOnly, Category = "Fire")
	int32 BurstCount = 3;

	/** Cyclic rate, rounds per minute. */
	UPROPERTY(EditDefaultsOnly, Category = "Fire")
	float RPM = 600.f;

	/** Rounds in a full magazine, not counting the chamber. */
	UPROPERTY(EditDefaultsOnly, Category = "Ammo")
	int32 MagazineSize = 30;

	/** True: a tactical reload keeps one round chambered (magazine + 1). */
	UPROPERTY(EditDefaultsOnly, Category = "Ammo")
	bool bClosedBolt = true;

	UPROPERTY(EditDefaultsOnly, Category = "Ammo")
	int32 ReserveRounds = 90;

	UPROPERTY(EditDefaultsOnly, Category = "Ammo", meta = (Units = "s"))
	float ReloadTactical = 2.f;

	UPROPERTY(EditDefaultsOnly, Category = "Ammo", meta = (Units = "s"))
	float ReloadEmpty = 2.7f;

	UPROPERTY(EditDefaultsOnly, Category = "Ammo", meta = (ClampMin = "0", ClampMax = "1"))
	float ReloadCommitFraction = 0.6f;

	UPROPERTY(EditDefaultsOnly, Category = "Handling", meta = (Units = "s"))
	float EquipTime = 0.5f;

	UPROPERTY(EditDefaultsOnly, Category = "Handling", meta = (Units = "s"))
	float HolsterTime = 0.3f;

	/** Body damage at full range, hp. */
	UPROPERTY(EditDefaultsOnly, Category = "Damage")
	float BaseDamage = 25.f;

	UPROPERTY(EditDefaultsOnly, Category = "Damage")
	TMap<EVerseHitZone, float> ZoneMultipliers;

	UPROPERTY(EditDefaultsOnly, Category = "Damage", meta = (Units = "m"))
	float FalloffStart = 20.f;

	UPROPERTY(EditDefaultsOnly, Category = "Damage", meta = (Units = "m"))
	float FalloffEnd = 40.f;

	UPROPERTY(EditDefaultsOnly, Category = "Damage", meta = (ClampMin = "0", ClampMax = "1"))
	float FalloffMinFraction = 0.7f;

	UPROPERTY(EditDefaultsOnly, Category = "Projectile", meta = (Units = "m/s"))
	float ProjectileSpeed = 300.f;

	UPROPERTY(EditDefaultsOnly, Category = "Projectile", meta = (Units = "m"))
	float MaxRange = 150.f;

	/** Power units, 100 = assault rifle (destruction.md 2). */
	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	float PenetrationPower = 100.f;

	/** Clamped to MaxPenetrationsCap. */
	UPROPERTY(EditDefaultsOnly, Category = "Penetration", meta = (ClampMin = "0", ClampMax = "3"))
	int32 MaxPenetrations = 3;

	/** Piece hp per hit; anchor 10 for the rifle (destruction.md 3.2). */
	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	float PieceDamage = 10.f;

	/** Bolt hole radius, mm; anchor 15 for the rifle (destruction.md 5). */
	UPROPERTY(EditDefaultsOnly, Category = "Penetration")
	uint8 HoleRadiusMm = 15;

	/** x = shot index, y = deg: the learnable pattern P_p(n); beyond the last key the value holds. */
	UPROPERTY(EditDefaultsOnly, Category = "Recoil")
	FRuntimeFloatCurve RecoilPitchCurve;

	/** x = shot index, y = deg: P_y(n). */
	UPROPERTY(EditDefaultsOnly, Category = "Recoil")
	FRuntimeFloatCurve RecoilYawCurve;

	/** f */
	UPROPERTY(EditDefaultsOnly, Category = "Recoil", meta = (ClampMin = "0", ClampMax = "1"))
	float RecoilRandomFraction = 0.15f;

	/** t_k */
	UPROPERTY(EditDefaultsOnly, Category = "Recoil", meta = (Units = "s"))
	float RecoilKickTime = 0.035f;

	/** rho, deg/s */
	UPROPERTY(EditDefaultsOnly, Category = "Recoil")
	float RecoilRecoveryRate = 5.f;

	/** d_r */
	UPROPERTY(EditDefaultsOnly, Category = "Recoil", meta = (Units = "s"))
	float RecoilRecoveryDelay = 0.12f;

	UPROPERTY(EditDefaultsOnly, Category = "Recoil", meta = (Units = "s"))
	float PatternResetTime = 0.35f;

	UPROPERTY(EditDefaultsOnly, Category = "Recoil")
	TMap<EVerseStance, float> RecoilStanceMultiplier;

	/** Applied at full ADS blend. */
	UPROPERTY(EditDefaultsOnly, Category = "Recoil")
	float RecoilAdsMultiplier = 0.8f;

	/** Visual-only camera shake per shot; never moves the aim. */
	UPROPERTY(EditDefaultsOnly, Category = "Recoil")
	float ViewPunchScale = 1.f;

	/** Hip to full ADS. */
	UPROPERTY(EditDefaultsOnly, Category = "Aim", meta = (Units = "s"))
	float AdsTime = 0.25f;

	/** First-person FOV at full ADS, deg. */
	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float AdsFov = 60.f;

	UPROPERTY(EditDefaultsOnly, Category = "Aim")
	float AdsMoveSpeedMultiplier = 0.6f;

	/** Cone half-angle at rest per stance: X = hip, Y = ADS, deg. */
	UPROPERTY(EditDefaultsOnly, Category = "Spread")
	TMap<EVerseStance, FVector2f> SpreadBase;

	/** Hip, ADS, deg. */
	UPROPERTY(EditDefaultsOnly, Category = "Spread")
	FVector2f FirstShotSpread = FVector2f::ZeroVector;

	UPROPERTY(EditDefaultsOnly, Category = "Spread", meta = (Units = "s"))
	float FirstShotRestTime = 0.3f;

	/** deg per m/s of horizontal speed */
	UPROPERTY(EditDefaultsOnly, Category = "Spread")
	float SpreadMovePerMps = 0.2f;

	/** deg */
	UPROPERTY(EditDefaultsOnly, Category = "Spread")
	float SpreadAirborne = 3.f;

	/** deg */
	UPROPERTY(EditDefaultsOnly, Category = "Spread")
	float BloomPerShot = 0.15f;

	/** deg */
	UPROPERTY(EditDefaultsOnly, Category = "Spread")
	float BloomMax = 2.f;

	/** deg/s */
	UPROPERTY(EditDefaultsOnly, Category = "Spread")
	float BloomRecoveryRate = 4.f;

	UPROPERTY(EditDefaultsOnly, Category = "Spread", meta = (Units = "s"))
	float BloomRecoveryDelay = 0.1f;

	/** 0..1, used for the bot's hearing (FVerseNoiseEvent). */
	UPROPERTY(EditDefaultsOnly, Category = "Noise", meta = (ClampMin = "0", ClampMax = "1"))
	float NoiseLoudness = 1.f;

	/** Presentation tag for the own bolt (amber, README). */
	UPROPERTY(EditDefaultsOnly, Category = "Presentation")
	FGameplayTag BoltColorOwn;

	/** Presentation tag for the opponent bolt (red, README). */
	UPROPERTY(EditDefaultsOnly, Category = "Presentation")
	FGameplayTag BoltColorFoe;

	float FireInterval() const { return 60.f / RPM; }

	/** MaxPenetrations clamped to the contract cap of 3. */
	int32 GetEffectiveMaxPenetrations() const { return FMath::Clamp(MaxPenetrations, 0, MaxPenetrationsCap); }

	/** The pattern P(n) = (P_p(n), P_y(n)) in degrees; beyond the curve end the last value holds. */
	FVector2f PatternAt(int32 ShotIndex) const;

	/**
	 * R1 as code (combat-state.md 4.3); the harness calls it for every asset. For every shot index
	 * 1 <= n <= MaxShot: rho * max(0, FireInterval - d_r) <= 0.5 * k_min_p with
	 * k_min_p = min_n MinMultiplier * (P_p(n) - f * |P(n)|).
	 */
	bool SatisfiesRecoveryBelowKick(float MinMultiplier, int32 MaxShot) const;
};

#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

#include "VerseMeleeRules.generated.h"

class UVerseMeleeDefinition;

/** What a melee press becomes (combat-state.md 7.2, 11.2). */
UENUM(BlueprintType)
enum class EVerseMeleeOutcome : uint8
{
	Whiff,
	Strike,
	Finisher
};

/**
 * The quantities of combat-state.md 7.1, measured on the horizontal plane from two base
 * transforms (location at the capsule base, rotation = pawn yaw), in Unreal centimetres.
 * When both pawns stand on the same spot (r below 0.1 cm) the direction d is undefined; the
 * rule is then theta = 0 and phi = 0 (the attacker counts as in front and looking at the victim).
 */
struct VERSECOMBAT_API FVerseMeleeGeometry
{
	/** Angle between the victim's facing and d (victim -> attacker), 0..180 deg. */
	double ThetaDeg = 0.0;
	/** Angle between the attacker's facing and -d, 0..180 deg. */
	double PhiDeg = 0.0;
	/** r: horizontal distance between the capsules, cm. */
	double HorizontalCm = 0.0;
	/** dz: attacker base minus victim base, cm. */
	double DzCm = 0.0;

	static FVerseMeleeGeometry Measure(const FTransform& AttackerBase, const FTransform& VictimBase);

	/** Strike reach: straight-line distance between the bases, cm. */
	double ReachCm() const { return FMath::Sqrt(HorizontalCm * HorizontalCm + DzCm * DzCm); }
};

/** The parts of a pawn's state the 7.2 rules read. Movement flags come from IVerseMovementQuery. */
struct VERSECOMBAT_API FVerseMeleeParticipant
{
	EVerseCombatPhase Phase = EVerseCombatPhase::Alive;
	bool bSpawnProtected = false;
	EVerseStance Stance = EVerseStance::Stand;
	bool bMantling = false;
	bool bAirborne = false;
};

namespace VerseMelee
{
	/** Comparisons accept values this close to a limit, so grid points on a limit classify as the table says. */
	inline constexpr double AngleToleranceDeg = 1e-3;
	inline constexpr double DistanceToleranceCm = 1e-2;
	/** Server press timing tolerance, s (a press on the cooldown tick is accepted). */
	inline constexpr double TimeTolerance = 1e-4;
	/** Weapon id carried by melee hit events (combat-state.md 2.2: the knife). */
	VERSECOMBAT_API extern const FName KnifeWeaponId;

	/**
	 * The non-geometric finisher conditions of 7.2: victim Alive (a victim already in a finisher
	 * is not Alive, so it cannot be hit by a second one), not spawn protected, not prone, not
	 * mantling; attacker Alive, grounded and not prone.
	 */
	VERSECOMBAT_API bool IsFinisherEligible(const FVerseMeleeParticipant& Attacker, const FVerseMeleeParticipant& Victim);

	/** A melee press is processed only while the attacker is Alive (not dead, not in a finisher). */
	VERSECOMBAT_API bool CanStartMelee(const FVerseMeleeParticipant& Attacker);

	/** A strike target: Alive, or a finisher attacker (who takes damage normally, 7.4). */
	VERSECOMBAT_API bool CanBeStruck(const FVerseMeleeParticipant& Victim);

	/** 7.2 over measured geometry. bEligible is IsFinisherEligible; bSweepClear the capsule sweep. */
	VERSECOMBAT_API EVerseMeleeOutcome ClassifyMeasured(const FVerseMeleeGeometry& Geometry,
		const UVerseMeleeDefinition& Def, bool bEligible, bool bSweepClear);

	/**
	 * The finisher's vulnerability rule (7.4, A4.6): a FinisherVictim takes no damage except the
	 * finisher's own kill; a Dead pawn takes none; everyone else (the finisher attacker included)
	 * takes damage normally. Every damage path (WP02.9) asks this before applying damage.
	 */
	VERSECOMBAT_API bool AllowsDamage(EVerseCombatPhase VictimPhase, EVerseDamageSource Source);
}

/** Server press gate for the strike cooldown (7.3) and the finisher lock-out. Server time, s. */
struct VERSECOMBAT_API FVerseMeleeClock
{
	double NextPressAllowed = -1.0e9;

	bool CanPress(double Now) const { return Now + VerseMelee::TimeTolerance >= NextPressAllowed; }

	/** Accepts the press and starts the cooldown, or refuses it. */
	bool TryPress(double Now, double CooldownS);

	/** No press is accepted before Time (a running finisher). */
	void BlockUntil(double Time) { NextPressAllowed = FMath::Max(NextPressAllowed, Time); }
};

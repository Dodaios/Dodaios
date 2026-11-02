#include "Melee/VerseMeleeRules.h"

#include "Combat/VerseMeleeDefinition.h"
#include "VerseCoords.h"

const FName VerseMelee::KnifeWeaponId(TEXT("hookbill"));

namespace
{
	FVector2D FacingOf(const FTransform& Base)
	{
		const double YawRad = FMath::DegreesToRadians(Base.Rotator().Yaw);
		return FVector2D(FMath::Cos(YawRad), FMath::Sin(YawRad));
	}

	double AngleBetweenDeg(const FVector2D& A, const FVector2D& B)
	{
		const double Dot = FMath::Clamp(FVector2D::DotProduct(A, B), -1.0, 1.0);
		return FMath::RadiansToDegrees(FMath::Acos(Dot));
	}
}

FVerseMeleeGeometry FVerseMeleeGeometry::Measure(const FTransform& AttackerBase, const FTransform& VictimBase)
{
	FVerseMeleeGeometry G;
	const FVector A = AttackerBase.GetLocation();
	const FVector V = VictimBase.GetLocation();
	const FVector2D Delta(A.X - V.X, A.Y - V.Y);
	G.HorizontalCm = Delta.Size();
	G.DzCm = A.Z - V.Z;
	if (G.HorizontalCm < 0.1)
	{
		G.ThetaDeg = 0.0;
		G.PhiDeg = 0.0;
		return G;
	}
	const FVector2D D = Delta / G.HorizontalCm;
	G.ThetaDeg = AngleBetweenDeg(FacingOf(VictimBase), D);
	G.PhiDeg = AngleBetweenDeg(FacingOf(AttackerBase), -D);
	return G;
}

bool VerseMelee::IsFinisherEligible(const FVerseMeleeParticipant& Attacker, const FVerseMeleeParticipant& Victim)
{
	const bool bVictimOk = Victim.Phase == EVerseCombatPhase::Alive && !Victim.bSpawnProtected
		&& Victim.Stance != EVerseStance::Prone && !Victim.bMantling;
	const bool bAttackerOk = Attacker.Phase == EVerseCombatPhase::Alive && !Attacker.bAirborne
		&& Attacker.Stance != EVerseStance::Prone;
	return bVictimOk && bAttackerOk;
}

bool VerseMelee::CanStartMelee(const FVerseMeleeParticipant& Attacker)
{
	return Attacker.Phase == EVerseCombatPhase::Alive;
}

bool VerseMelee::CanBeStruck(const FVerseMeleeParticipant& Victim)
{
	return Victim.Phase == EVerseCombatPhase::Alive || Victim.Phase == EVerseCombatPhase::FinisherAttacker;
}

EVerseMeleeOutcome VerseMelee::ClassifyMeasured(const FVerseMeleeGeometry& G, const UVerseMeleeDefinition& Def,
	bool bEligible, bool bSweepClear)
{
	using namespace Verse::Coords;
	const bool bFront = G.ThetaDeg <= Def.FrontHalfAngle + AngleToleranceDeg;
	const bool bFinisherGeometry = !bFront
		&& G.HorizontalCm <= MetresToCm(Def.FinisherRange) + DistanceToleranceCm
		&& G.PhiDeg <= Def.AttackerFacingMax + AngleToleranceDeg
		&& FMath::Abs(G.DzCm) <= MetresToCm(Def.FinisherMaxHeightDelta) + DistanceToleranceCm;
	if (bFinisherGeometry && bEligible && bSweepClear)
	{
		return EVerseMeleeOutcome::Finisher;
	}
	const bool bStrike = G.ReachCm() <= MetresToCm(Def.StrikeRange) + DistanceToleranceCm
		&& G.PhiDeg <= Def.StrikeConeHalfAngle + AngleToleranceDeg;
	return bStrike ? EVerseMeleeOutcome::Strike : EVerseMeleeOutcome::Whiff;
}

bool VerseMelee::AllowsDamage(EVerseCombatPhase VictimPhase, EVerseDamageSource Source)
{
	switch (VictimPhase)
	{
	case EVerseCombatPhase::Dead:
		return false;
	case EVerseCombatPhase::FinisherVictim:
		return Source == EVerseDamageSource::Finisher;
	default:
		return true;
	}
}

bool FVerseMeleeClock::TryPress(double Now, double CooldownS)
{
	if (!CanPress(Now))
	{
		return false;
	}
	NextPressAllowed = Now + CooldownS;
	return true;
}

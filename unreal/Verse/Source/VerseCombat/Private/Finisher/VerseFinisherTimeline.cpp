#include "Finisher/VerseFinisherTimeline.h"

namespace
{
	double Smoothstep(double X)
	{
		X = FMath::Clamp(X, 0.0, 1.0);
		return X * X * (3.0 - 2.0 * X);
	}

	FTransform Blend(const FTransform& A, const FTransform& B, double Alpha)
	{
		const FVector Location = FMath::Lerp(A.GetLocation(), B.GetLocation(), Alpha);
		const FQuat Rotation = FQuat::Slerp(A.GetRotation(), B.GetRotation(), Alpha).GetNormalized();
		return FTransform(Rotation, Location, B.GetScale3D());
	}

	FRotator YawOnly(double YawDeg)
	{
		return FRotator(0.0, YawDeg, 0.0);
	}
}

double VerseFinisher::PhaseOffset(EVerseFinisherPhase Phase)
{
	switch (Phase)
	{
	case EVerseFinisherPhase::Locked:
		return 0.0;
	case EVerseFinisherPhase::Takedown:
		return TakedownAt;
	case EVerseFinisherPhase::Struggle:
		return StruggleAt;
	case EVerseFinisherPhase::Kill:
		return KillAt;
	case EVerseFinisherPhase::Recover:
		return RecoverAt;
	default:
		return -1.0;
	}
}

EVerseFinisherPhase VerseFinisher::PhaseAt(double Elapsed)
{
	const double T = Elapsed + TimeTolerance;
	if (T >= RecoverAt)
	{
		return EVerseFinisherPhase::Recover;
	}
	if (T >= KillAt)
	{
		return EVerseFinisherPhase::Kill;
	}
	if (T >= StruggleAt)
	{
		return EVerseFinisherPhase::Struggle;
	}
	if (T >= TakedownAt)
	{
		return EVerseFinisherPhase::Takedown;
	}
	return EVerseFinisherPhase::Locked;
}

void FVerseFinisherSession::Start(double Now)
{
	StartTime = Now;
	Phase = EVerseFinisherPhase::Locked;
	bActive = true;
	bKillApplied = false;
	bAborted = false;
	bReleased = false;
}

bool FVerseFinisherSession::Advance(double Now, double AttackerDeathTime, TArray<FVerseFinisherStep>& OutEntered)
{
	if (!bActive || bReleased)
	{
		return false;
	}
	const EVerseFinisherPhase Order[] = {EVerseFinisherPhase::Takedown, EVerseFinisherPhase::Struggle,
		EVerseFinisherPhase::Kill, EVerseFinisherPhase::Recover};
	// D5: the attacker's death before the kill time aborts; at or after it the kill stands.
	// Strict: the death time is an event stamp, not a tick, so no tick tolerance applies here.
	const bool bDiesBeforeKill = AttackerDeathTime < StartTime + VerseFinisher::RecoverAt;
	for (const EVerseFinisherPhase Next : Order)
	{
		if (uint8(Next) <= uint8(Phase))
		{
			continue;
		}
		const double At = StartTime + VerseFinisher::PhaseOffset(Next);
		if (bDiesBeforeKill && AttackerDeathTime <= At && AttackerDeathTime <= Now)
		{
			break;
		}
		if (Now + VerseFinisher::TimeTolerance < At)
		{
			break;
		}
		Phase = Next;
		OutEntered.Add({Next, Now});
		if (Next == EVerseFinisherPhase::Recover)
		{
			bKillApplied = true;
		}
	}
	if (bDiesBeforeKill && AttackerDeathTime <= Now && !bKillApplied)
	{
		Phase = EVerseFinisherPhase::Aborted;
		bAborted = true;
		bReleased = true;
		bActive = false;
		OutEntered.Add({EVerseFinisherPhase::Aborted, Now});
		return true;
	}
	if (VerseFinisher::IsOver(Elapsed(Now)))
	{
		bReleased = true;
		bActive = false;
		return true;
	}
	return false;
}

void FVerseFinisherPose::ComputePaired(const FTransform& Attacker, const FTransform& Victim, double PairedOffsetCm,
	FTransform& OutVictim, FTransform& OutWarpTarget)
{
	const FVector A = Attacker.GetLocation();
	const FVector V = Victim.GetLocation();
	FVector2D Dir(V.X - A.X, V.Y - A.Y);
	if (Dir.SizeSquared() < 1e-4)
	{
		const FVector Forward = Victim.GetRotation().GetForwardVector();
		Dir = FVector2D(Forward.X, Forward.Y);
	}
	Dir.Normalize();
	const double YawDeg = FMath::RadiansToDegrees(FMath::Atan2(Dir.Y, Dir.X));
	OutVictim = FTransform(YawOnly(YawDeg), V, Victim.GetScale3D());
	const FVector Target(V.X - Dir.X * PairedOffsetCm, V.Y - Dir.Y * PairedOffsetCm, A.Z);
	OutWarpTarget = FTransform(YawOnly(YawDeg), Target, Attacker.GetScale3D());
}

FTransform FVerseFinisherPose::VictimFromWarpTarget(const FTransform& WarpTarget, double PairedOffsetCm, double VictimZ)
{
	const FVector Forward = WarpTarget.GetRotation().GetForwardVector().GetSafeNormal2D();
	FVector Location = WarpTarget.GetLocation() + Forward * PairedOffsetCm;
	Location.Z = VictimZ;
	return FTransform(WarpTarget.GetRotation(), Location, WarpTarget.GetScale3D());
}

FTransform FVerseFinisherPose::EvaluateWarp(const FTransform& StartPose, double StartElapsed, const FTransform& Target,
	double Elapsed)
{
	const double Span = VerseFinisher::TakedownAt - StartElapsed;
	// Too little time left to blend (Locked arrived late): snap, so the pose is right at Takedown.
	if (Span < VerseFinisher::MinWarpS || Elapsed + VerseFinisher::TimeTolerance >= VerseFinisher::TakedownAt)
	{
		return Target;
	}
	return Blend(StartPose, Target, Smoothstep((Elapsed - StartElapsed) / Span));
}

FTransform FVerseFinisherPose::EvaluateSnap(const FTransform& From, const FTransform& To, double SinceLocked, double SnapS)
{
	if (SnapS <= VerseFinisher::TimeTolerance || SinceLocked >= SnapS)
	{
		return To;
	}
	return Blend(From, To, Smoothstep(SinceLocked / SnapS));
}

FVerseFinisherViewState VerseFinisher::EvaluateView(double Elapsed, bool bAborted, EVerseGoreLevel Gore)
{
	FVerseFinisherViewState S;
	if (bAborted || IsOver(Elapsed) || Elapsed < -TimeTolerance)
	{
		return S;
	}
	S.bKnifeInHand = true;
	S.bActiveWeaponEquipped = false;
	const double T = Elapsed + TimeTolerance;
	const bool bCut = Gore == EVerseGoreLevel::Reduced && T >= TakedownAt && T < RecoverAt;
	S.View = bCut ? EVerseFinisherView::Black : EVerseFinisherView::ThirdPerson;
	return S;
}

FTransform VerseFinisher::CameraTransform(const FTransform& Attacker, const FTransform& Victim, double DistanceCm,
	double HeightCm)
{
	const FVector A = Attacker.GetLocation();
	const FVector V = Victim.GetLocation();
	const FVector Mid = (A + V) * 0.5;
	FVector Along = (V - A).GetSafeNormal2D();
	if (Along.IsNearlyZero())
	{
		Along = Victim.GetRotation().GetForwardVector().GetSafeNormal2D();
	}
	// To the pair's right, slightly behind the attacker, so both bodies are in the shot.
	const FVector Side(-Along.Y, Along.X, 0.0);
	const FVector Eye = Mid + (Side * 0.94 - Along * 0.34) * DistanceCm + FVector(0.0, 0.0, HeightCm);
	const FVector LookAt = Mid + FVector(0.0, 0.0, HeightCm * 0.35);
	return FTransform((LookAt - Eye).Rotation(), Eye);
}

void FVerseKnifePresentation::Press(double Now, bool bKnifeSlot)
{
	PressTime = Now;
	bKnifeSlotActive = bKnifeSlot;
	bNeedsEquip = !bKnifeSlot;
	bConfirmed = false;
	Confirmed = EVerseMeleeOutcome::Whiff;
}

void FVerseKnifePresentation::Confirm(EVerseMeleeOutcome Outcome)
{
	bConfirmed = true;
	Confirmed = Outcome;
}

EVerseKnifeAnim FVerseKnifePresentation::Evaluate(double Now) const
{
	const EVerseKnifeAnim Rest = bKnifeSlotActive ? EVerseKnifeAnim::Ready : EVerseKnifeAnim::Hidden;
	const double T = Now - PressTime;
	if (T < 0.0)
	{
		return Rest;
	}
	if (bConfirmed && Confirmed == EVerseMeleeOutcome::Finisher)
	{
		// The finisher presentation takes the knife over (VerseFinisher::EvaluateView).
		return EVerseKnifeAnim::Hidden;
	}
	const double Equip = bNeedsEquip ? FMath::Min(EquipS, HitDelayS) : 0.0;
	if (T < Equip)
	{
		return EVerseKnifeAnim::Equipping;
	}
	if (T < HitDelayS)
	{
		return EVerseKnifeAnim::Swinging;
	}
	if (T < HitDelayS + RecoverS)
	{
		return EVerseKnifeAnim::Recovering;
	}
	return Rest;
}

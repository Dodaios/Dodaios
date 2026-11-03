#include "Brain/VerseBotAimDriver.h"

#include "Bot/VerseBotTier.h"

void FVerseBotFollowAim::Reset(uint64 Seed, const UVerseBotTier& Tier)
{
	ReactionS = Tier.ReactionMs.X / 1000.f;
	TurnRateDegS = Tier.TurnRateDegS;
	FireTolerance = Tier.FireTolerance;
	SinceAcquireS = 0.f;
}

FVerseBotAimResult FVerseBotFollowAim::Step(const FVerseSelfPercept& Self, const FVerseBotAimRequest& Request, float DtS)
{
	FVerseBotAimResult R;
	if (!Request.bHasTarget)
	{
		SinceAcquireS = 0.f;
		return R;
	}
	if (Request.bNewTarget)
	{
		// A reaction the brain already waited is not waited again.
		SinceAcquireS = Request.ReactionRemainingS >= 0.f ? FMath::Max(ReactionS - Request.ReactionRemainingS, 0.f) : 0.f;
	}
	SinceAcquireS += DtS;

	const FVector ToTarget = Request.TargetPoint - Self.EyeLocation;
	const FRotator Want = ToTarget.Rotation();
	const FRotator Delta = (Want - Self.ViewRotation).GetNormalized();
	const float MaxStep = TurnRateDegS * DtS;
	const bool bReacting = SinceAcquireS < ReactionS;
	const float Pitch = bReacting ? 0.f : FMath::Clamp(float(Delta.Pitch), -MaxStep, MaxStep);
	const float Yaw = bReacting ? 0.f : FMath::Clamp(float(Delta.Yaw), -MaxStep, MaxStep);
	R.LookDeltaDeg = FVector2f(Pitch, Yaw);

	const FRotator After(Self.ViewRotation.Pitch + Pitch, Self.ViewRotation.Yaw + Yaw, 0.f);
	const FVector Axis = After.Vector();
	const FVector Dir = ToTarget.GetSafeNormal();
	R.ErrorDeg = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(float(FVector::DotProduct(Axis, Dir)), -1.f, 1.f)));
	R.bOnTarget = !bReacting && R.ErrorDeg <= FireTolerance * FMath::Max(Request.TargetHalfWidthDeg, 0.1f);
	return R;
}

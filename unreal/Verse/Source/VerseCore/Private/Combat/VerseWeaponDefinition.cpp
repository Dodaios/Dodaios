#include "Combat/VerseWeaponDefinition.h"

namespace
{
	float EvalCurve(const FRuntimeFloatCurve& Curve, float X)
	{
		const FRichCurve* Rich = Curve.GetRichCurveConst();
		return (Rich && Rich->GetNumKeys() > 0) ? Rich->Eval(X) : 0.f;
	}
}

FVector2f UVerseWeaponDefinition::PatternAt(int32 ShotIndex) const
{
	const float X = float(FMath::Max(0, ShotIndex));
	return FVector2f(EvalCurve(RecoilPitchCurve, X), EvalCurve(RecoilYawCurve, X));
}

bool UVerseWeaponDefinition::SatisfiesRecoveryBelowKick(float MinMultiplier, int32 MaxShot) const
{
	if (RPM <= 0.f || MaxShot < 1)
	{
		return false;
	}
	float KMinPitch = TNumericLimits<float>::Max();
	for (int32 N = 1; N <= MaxShot; ++N)
	{
		const FVector2f P = PatternAt(N);
		KMinPitch = FMath::Min(KMinPitch, MinMultiplier * (P.X - RecoilRandomFraction * P.Size()));
	}
	const float RecoveryBetweenShots = RecoilRecoveryRate * FMath::Max(0.f, FireInterval() - RecoilRecoveryDelay);
	return RecoveryBetweenShots <= 0.5f * KMinPitch;
}

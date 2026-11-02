#include "Weapons/VerseRecoil.h"

#include "Combat/VerseWeaponDefinition.h"
#include "VerseRng.h"

float FVerseRecoilState::Multiplier(const UVerseWeaponDefinition& W, EVerseStance Stance, float AdsBlend)
{
	const float* StanceMul = W.RecoilStanceMultiplier.Find(Stance);
	const float S = StanceMul ? *StanceMul : 1.f;
	return S * FMath::Lerp(1.f, W.RecoilAdsMultiplier, FMath::Clamp(AdsBlend, 0.f, 1.f));
}

float FVerseRecoilState::MinMultiplier(const UVerseWeaponDefinition& W)
{
	float Min = TNumericLimits<float>::Max();
	for (const EVerseStance Stance : {EVerseStance::Stand, EVerseStance::Crouch, EVerseStance::Prone, EVerseStance::Slide})
	{
		Min = FMath::Min(Min, Multiplier(W, Stance, 0.f));
		Min = FMath::Min(Min, Multiplier(W, Stance, 1.f));
	}
	return Min;
}

int32 FVerseRecoilState::ShotIndexAt(const UVerseWeaponDefinition& W, float Now) const
{
	return (Now - LastShotTime >= W.PatternResetTime) ? 0 : ShotIndex;
}

void FVerseRecoilState::BeginShot(const UVerseWeaponDefinition& W, float Now)
{
	ShotIndex = ShotIndexAt(W, Now);
}

FVector2f FVerseRecoilState::KickAt(const UVerseWeaponDefinition& W, int32 N, float Mul, uint32 Seed)
{
	const FVector2f P = W.PatternAt(N);
	FVerseRng Rng(Seed, uint64(FMath::Max(0, N)), EVerseRngSalt::Recoil);
	const FVector2D U = Rng.UnitDisk();
	const float Random = W.RecoilRandomFraction * P.Size();
	return Mul * (P + Random * FVector2f(float(U.X), float(U.Y)));
}

FVector2f FVerseRecoilState::KickFor(const UVerseWeaponDefinition& W, float Mul, uint32 Seed) const
{
	return KickAt(W, ShotIndex, Mul, Seed);
}

void FVerseRecoilState::OnShot(const FVector2f& Kick, float Now)
{
	// Whatever of the previous kick is still pending is applied with the new one.
	const FVector2f Remainder = KickTotal - KickApplied;
	KickTotal = Kick + Remainder;
	KickApplied = FVector2f::ZeroVector;
	KickStartTime = Now;

	Accumulated += Kick;
	++ShotIndex;
	LastShotTime = Now;
}

void FVerseRecoilState::OnLookInput(FVector2f& InOutDelta)
{
	// Pitch: a downward input (negative) pulls the climb back, never below zero.
	if (InOutDelta.X < 0.f && Accumulated.X > 0.f)
	{
		Accumulated.X = FMath::Max(0.f, Accumulated.X - FMath::Abs(InOutDelta.X));
	}
	else if (InOutDelta.X > 0.f && Accumulated.X < 0.f)
	{
		Accumulated.X = FMath::Min(0.f, Accumulated.X + FMath::Abs(InOutDelta.X));
	}
	// Yaw: input against the sign of A_y compensates.
	if (InOutDelta.Y < 0.f && Accumulated.Y > 0.f)
	{
		Accumulated.Y = FMath::Max(0.f, Accumulated.Y - FMath::Abs(InOutDelta.Y));
	}
	else if (InOutDelta.Y > 0.f && Accumulated.Y < 0.f)
	{
		Accumulated.Y = FMath::Min(0.f, Accumulated.Y + FMath::Abs(InOutDelta.Y));
	}
}

FVector2f FVerseRecoilState::TickKick(const UVerseWeaponDefinition& W, float Now)
{
	if (KickTotal.IsNearlyZero(1e-8f))
	{
		return FVector2f::ZeroVector;
	}
	const float Tk = FMath::Max(W.RecoilKickTime, UE_SMALL_NUMBER);
	const float T = FMath::Clamp((Now - KickStartTime) / Tk, 0.f, 1.f);
	const float Eased = 1.f - FMath::Square(1.f - T); // ease-out
	const FVector2f Target = KickTotal * Eased;
	const FVector2f Delta = Target - KickApplied;
	KickApplied = Target;
	if (T >= 1.f)
	{
		KickTotal = FVector2f::ZeroVector;
		KickApplied = FVector2f::ZeroVector;
	}
	return Delta;
}

FVector2f FVerseRecoilState::TickRecovery(const UVerseWeaponDefinition& W, float Now, float Dt)
{
	if (Now - LastShotTime < W.RecoilRecoveryDelay)
	{
		return FVector2f::ZeroVector;
	}
	const float Len = Accumulated.Size();
	if (Len <= 0.f)
	{
		return FVector2f::ZeroVector;
	}
	const float Step = FMath::Min(Len, W.RecoilRecoveryRate * FMath::Max(0.f, Dt));
	const FVector2f Removed = Accumulated * (Step / Len);
	Accumulated -= Removed;
	if (Step >= Len)
	{
		Accumulated = FVector2f::ZeroVector;
	}
	return Removed;
}

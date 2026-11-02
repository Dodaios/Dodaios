#include "Weapons/VerseSpread.h"

#include "Combat/VerseWeaponDefinition.h"
#include "VerseRng.h"

namespace
{
	FVector2f SpreadBaseFor(const UVerseWeaponDefinition& W, EVerseStance Stance)
	{
		if (const FVector2f* Found = W.SpreadBase.Find(Stance))
		{
			return *Found;
		}
		if (const FVector2f* Stand = W.SpreadBase.Find(EVerseStance::Stand))
		{
			return *Stand;
		}
		return FVector2f::ZeroVector;
	}
}

bool FVerseSpread::IsFirstShot(const UVerseWeaponDefinition& W, float Now) const
{
	return Now - LastShotTime >= W.FirstShotRestTime;
}

float FVerseSpread::RestingSigma(const UVerseWeaponDefinition& W, const FVerseSpreadInput& In, float BloomDeg)
{
	const float Ads = FMath::Clamp(In.AdsBlend, 0.f, 1.f);
	const FVector2f Base = SpreadBaseFor(W, In.Stance);
	float Sigma = FMath::Lerp(Base.X, Base.Y, Ads);
	Sigma += W.SpreadMovePerMps * FMath::Max(0.f, In.HorizontalSpeedMps);
	Sigma += In.bAirborne ? W.SpreadAirborne : 0.f;
	Sigma += FMath::Max(0.f, BloomDeg);
	return FMath::Max(0.f, Sigma);
}

float FVerseSpread::SigmaFor(const UVerseWeaponDefinition& W, const FVerseSpreadInput& In, float Now) const
{
	if (IsFirstShot(W, Now))
	{
		const float Ads = FMath::Clamp(In.AdsBlend, 0.f, 1.f);
		return FMath::Max(0.f, FMath::Lerp(W.FirstShotSpread.X, W.FirstShotSpread.Y, Ads));
	}
	return RestingSigma(W, In, Bloom);
}

void FVerseSpread::DecayTo(const UVerseWeaponDefinition& W, float Now, float Dt)
{
	if (Now - LastShotTime >= W.BloomRecoveryDelay)
	{
		Bloom = FMath::Max(0.f, Bloom - W.BloomRecoveryRate * FMath::Max(0.f, Dt));
	}
}

void FVerseSpread::OnShot(const UVerseWeaponDefinition& W, float Now)
{
	if (IsFirstShot(W, Now))
	{
		Bloom = 0.f;
	}
	Bloom = FMath::Min(W.BloomMax, Bloom + W.BloomPerShot);
	LastShotTime = Now;
}

uint32 FVerseSpread::ShotSeed(uint32 ShooterNetId, uint16 ShotCounter, uint32 MatchSeed)
{
	return FVerseRng::Hash(ShooterNetId, uint32(ShotCounter), MatchSeed);
}

FVector FVerseSpread::ShotDirection(const FVector& Forward, float SigmaDeg, uint32 Seed, int32 ShotIndex)
{
	FVerseRng Rng(Seed, uint64(FMath::Max(0, ShotIndex)), EVerseRngSalt::Spread);
	return Rng.ConeDirection(Forward, FMath::Max(0.f, SigmaDeg));
}

bool FVerseSpread::ValidateFire(const FVector& Origin, const FVector& Dir, const FVector& RewoundEye,
	const FVector& ServerForward, float SigmaDeg)
{
	if (Dir.SizeSquared() < UE_KINDA_SMALL_NUMBER)
	{
		return false;
	}
	if (FVector::Dist(Origin, RewoundEye) > OriginToleranceCm)
	{
		return false;
	}
	const FVector A = Dir.GetSafeNormal();
	const FVector B = ServerForward.GetSafeNormal();
	const double CosAngle = FMath::Clamp(FVector::DotProduct(A, B), -1.0, 1.0);
	const double AngleDeg = FMath::RadiansToDegrees(FMath::Acos(CosAngle));
	return AngleDeg <= double(SigmaDeg) + DirectionToleranceDeg;
}

void FVerseFireCadence::Collect(const UVerseWeaponDefinition& W, bool bTriggerDown, float TickStart, float Now,
	int32 RoundsAvailable, TArray<float>& OutShotTimes)
{
	const float Interval = W.FireInterval();
	const bool bPressed = bTriggerDown && !bTriggerWasDown;
	bTriggerWasDown = bTriggerDown;
	if (Interval <= 0.f)
	{
		return;
	}

	auto TryShot = [&](float At) -> bool
	{
		if (RoundsAvailable <= 0 || At > Now)
		{
			return false;
		}
		OutShotTimes.Add(At);
		--RoundsAvailable;
		NextShotTime = At + Interval;
		return true;
	};

	switch (W.FireMode)
	{
	case EVerseFireMode::Semi:
		if (bPressed)
		{
			TryShot(FMath::Max(NextShotTime, TickStart));
		}
		break;
	case EVerseFireMode::Burst:
		if (bPressed && BurstLeft <= 0 && NextShotTime <= Now)
		{
			BurstLeft = FMath::Max(1, W.BurstCount);
			NextShotTime = FMath::Max(NextShotTime, TickStart);
		}
		while (BurstLeft > 0 && TryShot(NextShotTime))
		{
			--BurstLeft;
		}
		if (RoundsAvailable <= 0)
		{
			BurstLeft = 0;
		}
		break;
	case EVerseFireMode::Auto:
	default:
		if (bTriggerDown)
		{
			float At = FMath::Max(NextShotTime, TickStart);
			while (TryShot(At))
			{
				At = NextShotTime;
			}
		}
		break;
	}
}

bool FVerseFireCadence::AllowsShotAt(const UVerseWeaponDefinition& W, float Time) const
{
	return Time + 0.001f >= NextShotTime;
}

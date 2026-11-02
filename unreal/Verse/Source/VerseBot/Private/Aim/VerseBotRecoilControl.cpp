#include "Aim/VerseBotRecoilControl.h"

#include "Bot/VerseBotTier.h"
#include "Combat/VerseWeaponDefinition.h"

FVerseBotRecoilParams FVerseBotRecoilParams::FromTier(const UVerseBotTier& Tier)
{
	FVerseBotRecoilParams Out;
	Out.PatternComp = Tier.RecoilPatternComp;
	Out.ResidualGain = Tier.RecoilResidualGain;
	Out.TrackLatencyMs = Tier.TrackLatencyMs;
	return Out;
}

void FVerseBotRecoilControl::Reset(const FVerseBotRecoilParams& InParams)
{
	Params = InParams;
	Shots.Reset();
	PatternSum = FVector2D::ZeroVector;
	ResidualSeen = FVector2D::ZeroVector;
	LastShotS = -1.0e9;
	bSpraying = false;
}

void FVerseBotRecoilControl::OnShot(double TimeS, const FVector2D& PatternKickDeg, double KickWindowS, double PatternResetS)
{
	if (!bSpraying)
	{
		Shots.Reset();
		PatternSum = FVector2D::ZeroVector;
		ResidualSeen = FVector2D::ZeroVector;
	}
	bSpraying = true;
	LastShotS = TimeS;
	ResetAfterS = PatternResetS;
	Shots.Add({TimeS, PatternKickDeg, FVector2D::ZeroVector, KickWindowS, false});
	PatternSum += PatternKickDeg;
}

void FVerseBotRecoilControl::ObserveUnexplainedMotion(double TimeS, const FVector2D& DeltaDeg)
{
	// Credit the motion to the newest shot whose kick is still being applied. Motion outside every
	// kick window (recovery, a hit flinch) is not recoil the bot fights.
	for (int32 I = Shots.Num() - 1; I >= 0; --I)
	{
		FShot& Shot = Shots[I];
		if (TimeS + 1.0e-9 < Shot.TimeS)
		{
			continue;
		}
		if (TimeS - Shot.TimeS <= Shot.KickWindowS + 1.0e-9 && !Shot.bMature)
		{
			Shot.Observed += DeltaDeg;
		}
		break;
	}
}

void FVerseBotRecoilControl::Tick(double NowS)
{
	const double LatencyS = Params.TrackLatencyMs / 1000.0;
	for (FShot& Shot : Shots)
	{
		if (!Shot.bMature && NowS - Shot.TimeS >= FMath::Max(LatencyS, Shot.KickWindowS) - 1.0e-9)
		{
			Shot.bMature = true;
			ResidualSeen += Shot.Observed - Shot.Expected;
		}
	}
	if (bSpraying && NowS - LastShotS >= ResetAfterS - 1.0e-9)
	{
		bSpraying = false;
		Shots.Reset();
		PatternSum = FVector2D::ZeroVector;
		ResidualSeen = FVector2D::ZeroVector;
	}
}

FVector2D FVerseBotRecoilControl::PatternKick(const UVerseWeaponDefinition& Weapon, int32 ShotIndex, EVerseStance Stance, double AdsBlend)
{
	const float* StanceMul = Weapon.RecoilStanceMultiplier.Find(Stance);
	const double M = (StanceMul ? *StanceMul : 1.0) * FMath::Lerp(1.0, double(Weapon.RecoilAdsMultiplier), FMath::Clamp(AdsBlend, 0.0, 1.0));
	const FVector2f P = Weapon.PatternAt(ShotIndex);
	return FVector2D(P.X, P.Y) * M;
}

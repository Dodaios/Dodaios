#include "Aim/VerseBotNoSightFire.h"

#include "Bot/VerseBotTier.h"

FVerseBotNoSightParams FVerseBotNoSightParams::FromTier(const UVerseBotTier& Tier)
{
	FVerseBotNoSightParams Out;
	Out.PrefireChance = Tier.PrefireChance;
	Out.PrefireMinBelief = FMath::Max<double>(Tier.WallbangMinBelief, FVerseBotNoSightFire::BeliefFloor);
	return Out;
}

void FVerseBotNoSightFire::Reset(const FVerseBotNoSightParams& InParams, uint64 Seed)
{
	Params = InParams;
	Rng = FVerseRng(Seed, 3, EVerseRngSalt::Aim);
	RolledApproach = 0;
	bHaveRoll = false;
	bRollPassed = false;
}

bool FVerseBotNoSightFire::SuppressionAllowed(const FVerseBotNoSightInput& In) const
{
	return In.LastSeenS >= 0.0 && In.NowS - In.LastSeenS <= SuppressionS + 1.0e-9
		&& FVector::Dist(In.AimPoint, In.LastSeenLocation) <= SuppressionRadiusCm;
}

bool FVerseBotNoSightFire::PrefireConditions(const FVerseBotNoSightInput& In) const
{
	return In.bHasPeekEdge && In.HeardS >= 0.0 && In.NowS - In.HeardS <= PrefireHeardMaxAgeS + 1.0e-9
		&& FVector::Dist(In.HeardLocation, In.PeekEdgeLocation) <= PrefireEdgeRadiusCm
		&& In.BeliefMassAtEdge >= FMath::Max(Params.PrefireMinBelief, BeliefFloor)
		&& FVector::Dist(In.AimPoint, In.PeekEdgeLocation) <= SuppressionRadiusCm;
}

EVerseBotFireAuthority FVerseBotNoSightFire::Classify(const FVerseBotNoSightInput& In)
{
	if (SuppressionAllowed(In))
	{
		return EVerseBotFireAuthority::Suppression;
	}
	if (PrefireConditions(In))
	{
		if (!bHaveRoll || RolledApproach != In.ApproachId)
		{
			bHaveRoll = true;
			RolledApproach = In.ApproachId;
			bRollPassed = Rng.Chance(Params.PrefireChance);
		}
		if (bRollPassed)
		{
			return EVerseBotFireAuthority::Prefire;
		}
	}
	if (In.bWallShotAuthorised)
	{
		return EVerseBotFireAuthority::WallShot;
	}
	return EVerseBotFireAuthority::None;
}

#include "Aim/VerseBotFireGate.h"

#include "Bot/VerseBotTier.h"

FVerseBotFireParams FVerseBotFireParams::FromTier(const UVerseBotTier& Tier, float EffectiveSkill)
{
	FVerseBotFireParams Out;
	Out.FireTolerance = Tier.FireTolerance;
	Out.AdsRangeM = Tier.AdsRangeM;
	Out.BurstRangeM = Tier.BurstRangeM;
	Out.MaxBurstShots = FMath::Max(1, Tier.MaxBurstShots);
	Out.bTapsAtLongRange = EffectiveSkill >= 0.f ? EffectiveSkill >= 0.75f : Tier.TierId == FName(TEXT("elite"));
	return Out;
}

void FVerseBotFireGate::Reset(const FVerseBotFireParams& InParams)
{
	Params = InParams;
	BurstShots = 0;
	LastShotS = -1.0e9;
	bTriggerHeld = false;
	bWaitingForRecovery = false;
}

void FVerseBotFireGate::NotifyShot(double TimeS)
{
	LastShotS = TimeS;
	++BurstShots;
}

FVerseBotFireGateOutput FVerseBotFireGate::Evaluate(const FVerseBotFireGateInput& In)
{
	FVerseBotFireGateOutput Out;
	Out.bAds = In.bHasTarget && In.RangeM > Params.AdsRangeM && !In.bSprinting && !In.bSliding;

	auto Hold = [this, &Out](EVerseBotFireBlock Block)
	{
		Out.Block = Block;
		bTriggerHeld = false;
		return Out;
	};

	// A spray that paused long enough is over: the next shot is shot 0 again.
	const double SinceShot = In.NowS - LastShotS;
	if (SinceShot >= In.PatternResetS && !bTriggerHeld)
	{
		BurstShots = 0;
	}
	if (bWaitingForRecovery && SinceShot >= In.PatternResetS && In.bRecoilSettled)
	{
		bWaitingForRecovery = false;
		BurstShots = 0;
	}

	if (!In.bHasTarget)
	{
		return Hold(EVerseBotFireBlock::NoTarget);
	}
	if (In.bTargetSpawnProtected)
	{
		return Hold(EVerseBotFireBlock::SpawnProtectedTarget);
	}
	if (!In.bCanFire)
	{
		return Hold(EVerseBotFireBlock::CannotFire);
	}
	if (bWaitingForRecovery)
	{
		return Hold(EVerseBotFireBlock::BurstRecovery);
	}
	if (!WithinTolerance(In.AimErrorDeg, In.TargetHalfWidthDeg, Params.FireTolerance))
	{
		return Hold(EVerseBotFireBlock::OffTarget);
	}

	const bool bTap = Params.bTapsAtLongRange && In.RangeM > TapRangeM;
	if (bTap)
	{
		// Single shots, each with first-shot accuracy (combat-state.md 4.4 FirstShotRestTime).
		if (SinceShot < FMath::Max(In.FirstShotRestS, In.FireIntervalS))
		{
			return Hold(EVerseBotFireBlock::TapRest);
		}
		Out.bHoldFire = true;
		Out.bPressFire = true;
		bTriggerHeld = false;
		return Out;
	}

	const bool bBurst = In.RangeM > Params.BurstRangeM;
	if (bBurst && BurstShots >= Params.MaxBurstShots)
	{
		bWaitingForRecovery = true;
		return Hold(EVerseBotFireBlock::BurstRecovery);
	}

	if (In.bAutomatic)
	{
		Out.bHoldFire = true;
		Out.bPressFire = !bTriggerHeld;
		bTriggerHeld = true;
		return Out;
	}

	// Semi-auto: one press per shot, at most at the weapon's rate.
	if (SinceShot < In.FireIntervalS)
	{
		return Hold(EVerseBotFireBlock::FireInterval);
	}
	Out.bHoldFire = true;
	Out.bPressFire = true;
	bTriggerHeld = false;
	return Out;
}

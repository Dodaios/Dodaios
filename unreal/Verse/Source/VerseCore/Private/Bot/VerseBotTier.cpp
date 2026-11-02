#include "Bot/VerseBotTier.h"

bool UVerseBotTier::ApplyStartValues(FName InTierId, UVerseBotTier& Out)
{
	if (InTierId == TEXT("normal"))
	{
		Out.ReactionMs = FVector2f(320.0f, 60.0f);
		Out.PeripheralReactionMul = 1.6f;
		Out.PartialExposureAcquireMul = 1.5f;
		Out.TrackLatencyMs = 150.0f;
		Out.HearingErrorBaseM = 3.0f;
		Out.HearingErrorPerM = 0.1f;
		Out.AimNoiseDeg = 1.4f;
		Out.AimNoiseRate = 1.6f;
		Out.AcquireErrorDeg = 6.0f;
		Out.AcquireMs = 650.0f;
		Out.TurnRateDegS = 450.0f;
		Out.AimStiffness = 8.0f;
		Out.LeadSkill = 0.6f;
		Out.LeadNoise = 0.35f;
		Out.MotionWindowMs = 0.0f;
		Out.RecoilPatternComp = 0.35f;
		Out.RecoilResidualGain = 0.3f;
		Out.FireTolerance = 2.0f;
		Out.HeadAimChance = 0.05f;
		Out.AdsRangeM = 12.0f;
		Out.BurstRangeM = 30.0f;
		Out.MaxBurstShots = 8;
		Out.DecisionMs = 320.0f;
		Out.UtilityNoise = 0.08f;
		Out.Aggression = 0.5f;
		Out.CoverUse = 0.4f;
		Out.FlankUse = 0.2f;
		Out.PreferredRangeM = 14.0f;
		Out.StrafeMs = FVector2f(700.0f, 1500.0f);
		Out.LeanUse = 0.2f;
		Out.CrouchPeekUse = 0.2f;
		Out.ProneUse = 0.05f;
		Out.SlideUse = 0.1f;
		Out.NavLinkCostMul = 2.0f;
		Out.SoundDiscipline = 0.1f;
		Out.PeekRepeatPenalty = 0.1f;
		Out.BulwarkUse = 0.2f;
		Out.BreachUse = 0.1f;
		Out.WallbangUse = 0.15f;
		Out.WallbangMinBelief = 0.55f;
		Out.WallbangMaxSourceAgeS = 1.5f;
		Out.WallbangMinDamageFrac = 0.3f;
		Out.PrefireChance = 0.1f;
		Out.StalkUse = 0.1f;
		Out.MaxStalkS = 4.0f;
		Out.FinisherCommitConfidence = 0.8f;
		Out.KnifeChoice = 0.2f;
		Out.TacticalReloadAtFrac = 0.25f;
		Out.ReloadOnlyWhenSafe = 0.3f;
		Out.PistolSwitchChance = 0.2f;
		Out.LearnWeightMax = 0.1f;
		Out.LearnSamplesHalf = 12.0f;
		Out.HabitHalfLifeS = 180.0f;
		Out.ExplorationRate = 0.25f;
	}
	else if (InTierId == TEXT("hard"))
	{
		Out.ReactionMs = FVector2f(270.0f, 50.0f);
		Out.PeripheralReactionMul = 1.5f;
		Out.PartialExposureAcquireMul = 1.35f;
		Out.TrackLatencyMs = 120.0f;
		Out.HearingErrorBaseM = 1.9f;
		Out.HearingErrorPerM = 0.065f;
		Out.AimNoiseDeg = 1.0f;
		Out.AimNoiseRate = 1.9f;
		Out.AcquireErrorDeg = 3.9f;
		Out.AcquireMs = 450.0f;
		Out.TurnRateDegS = 620.0f;
		Out.AimStiffness = 12.0f;
		Out.LeadSkill = 0.8f;
		Out.LeadNoise = 0.22f;
		Out.MotionWindowMs = 200.0f;
		Out.RecoilPatternComp = 0.7f;
		Out.RecoilResidualGain = 0.5f;
		Out.FireTolerance = 1.6f;
		Out.HeadAimChance = 0.2f;
		Out.AdsRangeM = 9.0f;
		Out.BurstRangeM = 22.0f;
		Out.MaxBurstShots = 5;
		Out.DecisionMs = 220.0f;
		Out.UtilityNoise = 0.06f;
		Out.Aggression = 0.6f;
		Out.CoverUse = 0.65f;
		Out.FlankUse = 0.45f;
		Out.PreferredRangeM = 12.0f;
		Out.StrafeMs = FVector2f(450.0f, 1050.0f);
		Out.LeanUse = 0.6f;
		Out.CrouchPeekUse = 0.5f;
		Out.ProneUse = 0.1f;
		Out.SlideUse = 0.3f;
		Out.NavLinkCostMul = 1.3f;
		Out.SoundDiscipline = 0.5f;
		Out.PeekRepeatPenalty = 0.4f;
		Out.BulwarkUse = 0.5f;
		Out.BreachUse = 0.4f;
		Out.WallbangUse = 0.5f;
		Out.WallbangMinBelief = 0.4f;
		Out.WallbangMaxSourceAgeS = 2.5f;
		Out.WallbangMinDamageFrac = 0.3f;
		Out.PrefireChance = 0.35f;
		Out.StalkUse = 0.35f;
		Out.MaxStalkS = 6.0f;
		Out.FinisherCommitConfidence = 0.7f;
		Out.KnifeChoice = 0.35f;
		Out.TacticalReloadAtFrac = 0.35f;
		Out.ReloadOnlyWhenSafe = 0.7f;
		Out.PistolSwitchChance = 0.6f;
		Out.LearnWeightMax = 0.22f;
		Out.LearnSamplesHalf = 8.0f;
		Out.HabitHalfLifeS = 300.0f;
		Out.ExplorationRate = 0.15f;
	}
	else if (InTierId == TEXT("elite"))
	{
		Out.ReactionMs = FVector2f(225.0f, 40.0f);
		Out.PeripheralReactionMul = 1.4f;
		Out.PartialExposureAcquireMul = 1.25f;
		Out.TrackLatencyMs = 95.0f;
		Out.HearingErrorBaseM = 1.1f;
		Out.HearingErrorPerM = 0.04f;
		Out.AimNoiseDeg = 0.8f;
		Out.AimNoiseRate = 2.2f;
		Out.AcquireErrorDeg = 3.1f;
		Out.AcquireMs = 340.0f;
		Out.TurnRateDegS = 850.0f;
		Out.AimStiffness = 17.0f;
		Out.LeadSkill = 0.9f;
		Out.LeadNoise = 0.14f;
		Out.MotionWindowMs = 300.0f;
		Out.RecoilPatternComp = 0.85f;
		Out.RecoilResidualGain = 0.65f;
		Out.FireTolerance = 1.3f;
		Out.HeadAimChance = 0.35f;
		Out.AdsRangeM = 7.0f;
		Out.BurstRangeM = 16.0f;
		Out.MaxBurstShots = 4;
		Out.DecisionMs = 160.0f;
		Out.UtilityNoise = 0.05f;
		Out.Aggression = 0.7f;
		Out.CoverUse = 0.85f;
		Out.FlankUse = 0.7f;
		Out.PreferredRangeM = 11.0f;
		Out.StrafeMs = FVector2f(300.0f, 820.0f);
		Out.LeanUse = 0.9f;
		Out.CrouchPeekUse = 0.7f;
		Out.ProneUse = 0.15f;
		Out.SlideUse = 0.45f;
		Out.NavLinkCostMul = 1.0f;
		Out.SoundDiscipline = 0.85f;
		Out.PeekRepeatPenalty = 0.7f;
		Out.BulwarkUse = 0.8f;
		Out.BreachUse = 0.7f;
		Out.WallbangUse = 0.8f;
		Out.WallbangMinBelief = 0.3f;
		Out.WallbangMaxSourceAgeS = 3.5f;
		Out.WallbangMinDamageFrac = 0.3f;
		Out.PrefireChance = 0.6f;
		Out.StalkUse = 0.6f;
		Out.MaxStalkS = 8.0f;
		Out.FinisherCommitConfidence = 0.6f;
		Out.KnifeChoice = 0.5f;
		Out.TacticalReloadAtFrac = 0.45f;
		Out.ReloadOnlyWhenSafe = 0.9f;
		Out.PistolSwitchChance = 0.85f;
		Out.LearnWeightMax = 0.35f;
		Out.LearnSamplesHalf = 6.0f;
		Out.HabitHalfLifeS = 420.0f;
		Out.ExplorationRate = 0.1f;
	}
	else
	{
		return false;
	}
	Out.TierId = InTierId;
	return true;
}

bool UVerseBotTier::SatisfiesContractBounds() const
{
	return WallbangMinBelief >= WallbangMinBeliefFloor
		&& WallbangMaxSourceAgeS <= WallbangMaxSourceAgeCapS
		&& LearnWeightMax <= LearnWeightMaxCap;
}

void UVerseBotTier::ClampToContract()
{
	WallbangMinBelief = FMath::Max(WallbangMinBelief, WallbangMinBeliefFloor);
	WallbangMaxSourceAgeS = FMath::Min(WallbangMaxSourceAgeS, WallbangMaxSourceAgeCapS);
	LearnWeightMax = FMath::Min(LearnWeightMax, LearnWeightMaxCap);
}

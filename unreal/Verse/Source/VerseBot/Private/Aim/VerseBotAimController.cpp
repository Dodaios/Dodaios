#include "Aim/VerseBotAimController.h"

#include "Aim/VerseBotReaction.h"
#include "Bot/VerseBotTier.h"

FVerseBotReactionParams FVerseBotReactionParams::FromTier(const UVerseBotTier& Tier)
{
	FVerseBotReactionParams Out;
	Out.MeanMs = Tier.ReactionMs.X;
	Out.SdMs = Tier.ReactionMs.Y;
	Out.PeripheralMul = Tier.PeripheralReactionMul;
	Out.PartialExposureMul = Tier.PartialExposureAcquireMul;
	return Out;
}

double FVerseBotReaction::SampleMs(FVerseRng& Rng, const FVerseBotReactionParams& Params, EVerseBotStimulus Stimulus,
	double VisibilityFactor)
{
	double Ms = FMath::Max(FloorOfMean * Params.MeanMs, Rng.Gaussian(Params.MeanMs, Params.SdMs));
	if (EnumHasAnyFlags(Stimulus, EVerseBotStimulus::Sound))
	{
		Ms *= SoundMul;
	}
	if (EnumHasAnyFlags(Stimulus, EVerseBotStimulus::Peripheral))
	{
		Ms *= Params.PeripheralMul;
	}
	if (EnumHasAnyFlags(Stimulus, EVerseBotStimulus::PartialExposure))
	{
		Ms *= Params.PartialExposureMul;
	}
	if (VisibilityFactor > 0.0 && VisibilityFactor < 1.0)
	{
		Ms /= VisibilityFactor;
	}
	return Ms;
}

FVerseBotAimParams FVerseBotAimParams::FromTier(const UVerseBotTier& Tier)
{
	FVerseBotAimParams Out;
	Out.AimNoiseDeg = Tier.AimNoiseDeg;
	Out.AimNoiseRate = Tier.AimNoiseRate;
	Out.AcquireErrorDeg = Tier.AcquireErrorDeg;
	Out.AcquireMs = Tier.AcquireMs;
	Out.TurnRateDegS = Tier.TurnRateDegS;
	Out.AimStiffness = Tier.AimStiffness;
	return Out;
}

void FVerseBotAimController::Reset(const FVerseBotAimParams& InParams, uint64 Seed, const FVector2D& HandPitchYaw)
{
	Params = InParams;
	Rng = FVerseRng(Seed, 0, EVerseRngSalt::Aim);
	Hand = HandPitchYaw;
	Noise = FVector2D::ZeroVector;
	AcquireError = FVector2D::ZeroVector;
	AcquireAtS = -1.0e9;
}

void FVerseBotAimController::Acquire(double NowS)
{
	const double Angle = Rng.Range(0.0, 2.0 * UE_DOUBLE_PI);
	const double Magnitude = FMath::Abs(Rng.Gaussian(1.0, 0.35)) * Params.AcquireErrorDeg;
	AcquireError = FVector2D(FMath::Sin(Angle) * Magnitude * AcquirePitchScale, FMath::Cos(Angle) * Magnitude);
	AcquireAtS = NowS;
}

FVector2D FVerseBotAimController::GetErrorDeg(double NowS) const
{
	const double TauS = FMath::Max(0.001, Params.AcquireMs / 3.0 / 1000.0);
	const double Fade = FMath::Exp(-FMath::Max(0.0, NowS - AcquireAtS) / TauS);
	return Noise + AcquireError * Fade;
}

void FVerseBotAimController::StepNoise(double Dt)
{
	const double K = Params.AimNoiseRate;
	const double Scale = Params.AimNoiseDeg * FMath::Sqrt(2.0 * K * Dt);
	// Yaw first, then pitch: the draw order is part of the determinism contract (B5).
	Noise.Y += -K * Noise.Y * Dt + Scale * Rng.Gaussian();
	Noise.X += -K * Noise.X * Dt + Scale * PitchNoiseScale * Rng.Gaussian();
}

double FVerseBotAimController::YawDelta(double From, double To)
{
	double D = FMath::Fmod(To - From, 360.0);
	if (D > 180.0)
	{
		D -= 360.0;
	}
	else if (D <= -180.0)
	{
		D += 360.0;
	}
	return D;
}

FVector2D FVerseBotAimController::Step(double NowS, double Dt, const FVector2D& WantPitchYaw, bool bNoisy)
{
	StepNoise(Dt);
	FVector2D Target = WantPitchYaw;
	if (bNoisy)
	{
		Target += GetErrorDeg(NowS);
	}
	const double DPitch = Target.X - Hand.X;
	const double DYaw = YawDelta(Hand.Y, Target.Y);
	const double Blend = 1.0 - FMath::Exp(-Params.AimStiffness * Dt);

	auto Floored = [](double Full, double Smoothed)
	{
		if (FMath::Abs(Full) < StepFloorDeg)
		{
			return Full;
		}
		if (FMath::Abs(Smoothed) < StepFloorDeg)
		{
			return FMath::Sign(Full) * StepFloorDeg;
		}
		return Smoothed;
	};
	FVector2D StepDeg(Floored(DPitch, DPitch * Blend), Floored(DYaw, DYaw * Blend));

	const double MaxStep = Params.TurnRateDegS * Dt;
	const double Magnitude = StepDeg.Size();
	if (Magnitude > MaxStep && Magnitude > 0.0)
	{
		StepDeg *= MaxStep / Magnitude;
	}

	const double NewPitch = FMath::Clamp(Hand.X + StepDeg.X, -PitchLimitDeg, PitchLimitDeg);
	StepDeg.X = NewPitch - Hand.X;
	Hand.X = NewPitch;
	Hand.Y = FRotator::NormalizeAxis(Hand.Y + StepDeg.Y);
	return StepDeg;
}

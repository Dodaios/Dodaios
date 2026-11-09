#include "Aim/VerseBotTargetTracker.h"

#include "Bot/VerseBotTier.h"

FVerseBotTrackParams FVerseBotTrackParams::FromTier(const UVerseBotTier& Tier)
{
	FVerseBotTrackParams Out;
	Out.TrackLatencyMs = Tier.TrackLatencyMs;
	Out.MotionWindowMs = Tier.MotionWindowMs;
	Out.LeadSkill = Tier.LeadSkill;
	Out.LeadNoise = Tier.LeadNoise;
	Out.HeadAimChance = Tier.HeadAimChance;
	return Out;
}

void FVerseBotTargetTracker::Reset(const FVerseBotTrackParams& InParams, uint64 Seed)
{
	Params = InParams;
	Rng = FVerseRng(Seed, 1, EVerseRngSalt::Aim);
	History.Reset();
	bAimHead = false;
	LeadError = 0.0;
}

void FVerseBotTargetTracker::BeginEngagement()
{
	bAimHead = Rng.Chance(Params.HeadAimChance);
	LeadError = Rng.Gaussian(0.0, Params.LeadNoise);
}

void FVerseBotTargetTracker::Push(double TimeS, const FVerseSightPercept& Sighting)
{
	History.Add({TimeS, Sighting});
	const double Oldest = TimeS - HistoryS;
	int32 Drop = 0;
	while (Drop < History.Num() - 1 && History[Drop].TimeS < Oldest)
	{
		++Drop;
	}
	if (Drop > 0)
	{
		History.RemoveAt(0, Drop, EAllowShrinking::No);
	}
}

void FVerseBotTargetTracker::Clear()
{
	History.Reset();
}

const FVerseBotTargetTracker::FEntry* FVerseBotTargetTracker::EntryAtOrBefore(double TimeS) const
{
	for (int32 I = History.Num() - 1; I >= 0; --I)
	{
		if (History[I].TimeS <= TimeS + 1.0e-9)
		{
			return &History[I];
		}
	}
	return nullptr;
}

int32 FVerseBotTargetTracker::CountReversals(double TimeS) const
{
	int32 Reversals = 0;
	FVector2D Previous = FVector2D::ZeroVector;
	bool bHavePrevious = false;
	for (double T = TimeS - ReversalLookbackS; T <= TimeS + 1.0e-9; T += ReversalStepS)
	{
		const FEntry* Entry = EntryAtOrBefore(T);
		if (!Entry)
		{
			continue;
		}
		const FVector2D V(Entry->Sighting.Velocity.X, Entry->Sighting.Velocity.Y);
		if (V.SizeSquared() < 25.0 * 25.0)
		{
			continue; // standing still is not a reversal
		}
		if (bHavePrevious && FVector2D::DotProduct(V, Previous) < 0.0)
		{
			++Reversals;
		}
		Previous = V;
		bHavePrevious = true;
	}
	return Reversals;
}

bool FVerseBotTargetTracker::Perceived(double NowS, FVerseBotTrackedTarget& Out) const
{
	if (History.Num() == 0)
	{
		return false;
	}
	const double LatencyS = Params.TrackLatencyMs / 1000.0;
	const FEntry* Entry = EntryAtOrBefore(NowS - LatencyS);
	if (!Entry)
	{
		Entry = &History[0];
	}
	if (NowS - Entry->TimeS > LatencyS + StaleAfterLatencyS)
	{
		return false;
	}
	const FVerseSightPercept& S = Entry->Sighting;
	FVector Velocity = S.Velocity;

	// The motion read over the window when the target keeps reversing.
	const double WindowS = Params.MotionWindowMs / 1000.0;
	if (WindowS > 0.0 && CountReversals(Entry->TimeS) >= 2)
	{
		if (const FEntry* Old = EntryAtOrBefore(Entry->TimeS - WindowS))
		{
			const double Span = Entry->TimeS - Old->TimeS;
			if (Span > 1.0e-3)
			{
				Velocity = (S.PelvisLocation - Old->Sighting.PelvisLocation) / Span;
				Velocity.Z = S.Velocity.Z;
			}
		}
	}

	const double ExtrapolateS = (NowS - Entry->TimeS) * Params.LeadSkill;
	Out.PelvisLocation = S.PelvisLocation + Velocity * ExtrapolateS;
	Out.Velocity = Velocity;
	Out.Stance = S.Stance;
	Out.FacingYawDeg = S.FacingYawDeg;
	Out.VisibleMask = S.VisibleMask;
	Out.bSpawnProtected = S.bSpawnProtected;
	Out.bReloading = S.bReloading;
	Out.SightingTimeS = Entry->TimeS;
	return true;
}

FVector FVerseBotTargetTracker::SampleOffset(EVerseSightSample Sample, EVerseStance Stance, float FacingYawDeg)
{
	// Body layout relative to the pelvis in the target's own frame: X forward, Y right, Z up (cm).
	FVector Local = FVector::ZeroVector;
	const bool bProne = Stance == EVerseStance::Prone;
	switch (Sample)
	{
	case EVerseSightSample::Head: Local = bProne ? FVector(72, 0, 18) : FVector(0, 0, 64); break;
	case EVerseSightSample::Neck: Local = bProne ? FVector(58, 0, 14) : FVector(0, 0, 52); break;
	case EVerseSightSample::UpperTorso: Local = bProne ? FVector(36, 0, 12) : FVector(0, 0, 34); break;
	case EVerseSightSample::Pelvis: Local = FVector::ZeroVector; break;
	case EVerseSightSample::ShoulderLeft: Local = bProne ? FVector(46, -18, 12) : FVector(0, -18, 46); break;
	case EVerseSightSample::ShoulderRight: Local = bProne ? FVector(46, 18, 12) : FVector(0, 18, 46); break;
	case EVerseSightSample::KneeLeft: Local = bProne ? FVector(-48, -10, 4) : FVector(0, -10, -46); break;
	case EVerseSightSample::KneeRight: Local = bProne ? FVector(-48, 10, 4) : FVector(0, 10, -46); break;
	}
	if (Stance == EVerseStance::Crouch || Stance == EVerseStance::Slide)
	{
		Local.Z *= 0.65;
	}
	return FRotator(0.0, FacingYawDeg, 0.0).RotateVector(Local);
}

double FVerseBotTargetTracker::SampleRadiusCm(EVerseSightSample Sample)
{
	switch (Sample)
	{
	case EVerseSightSample::Head: return 11.0;
	case EVerseSightSample::UpperTorso: return 20.0;
	case EVerseSightSample::Pelvis: return 17.0;
	default: return 9.0;
	}
}

FVerseBotAimPoint FVerseBotTargetTracker::AimPoint(const FVerseBotTrackedTarget& Target, const FVector& Eye, double BoltSpeedMps) const
{
	const EVerseSightSample Wanted = bAimHead ? EVerseSightSample::Head : EVerseSightSample::UpperTorso;
	EVerseSightSample Chosen = Wanted;
	const uint8 Mask = Target.VisibleMask;
	if (Mask != 0 && (Mask & (1u << uint8(Wanted))) == 0)
	{
		// Only some points are visible: the visible one closest to the chosen point (bot.md 8.1).
		const FVector WantedOffset = SampleOffset(Wanted, Target.Stance, Target.FacingYawDeg);
		double Best = TNumericLimits<double>::Max();
		for (uint8 Bit = 0; Bit < 8; ++Bit)
		{
			if ((Mask & (1u << Bit)) == 0)
			{
				continue;
			}
			const EVerseSightSample Candidate = EVerseSightSample(Bit);
			const double D = FVector::DistSquared(SampleOffset(Candidate, Target.Stance, Target.FacingYawDeg), WantedOffset);
			if (D < Best)
			{
				Best = D;
				Chosen = Candidate;
			}
		}
	}

	FVector Point = Target.PelvisLocation + SampleOffset(Chosen, Target.Stance, Target.FacingYawDeg);
	const double Speed = (BoltSpeedMps > 1.0 ? BoltSpeedMps : DefaultBoltSpeedMps) * 100.0;
	const double FlightS = FVector::Dist(Eye, Point) / Speed;
	Point += Target.Velocity * (FlightS * Params.LeadSkill * (1.0 + LeadError));

	FVerseBotAimPoint Out;
	Out.Location = Point;
	Out.Sample = Chosen;
	const double DistCm = FMath::Max(1.0, FVector::Dist(Eye, Point));
	Out.RangeM = DistCm / 100.0;
	Out.HalfWidthDeg = FMath::RadiansToDegrees(FMath::Atan(SampleRadiusCm(Chosen) / DistCm));
	return Out;
}

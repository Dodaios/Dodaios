#include "Aim/VerseBotAimSystem.h"

#include "Bot/VerseBotTier.h"
#include "Combat/VerseCombatTypes.h"
#include "Combat/VerseWeaponDefinition.h"

namespace VerseBotAimSystemImpl
{
	int32 PopCount8(uint8 V)
	{
		int32 N = 0;
		for (; V; V &= V - 1)
		{
			++N;
		}
		return N;
	}
}

using namespace VerseBotAimSystemImpl;

FVector2D FVerseBotAimSystem::AnglesTo(const FVector& Eye, const FVector& Point)
{
	const FRotator R = (Point - Eye).Rotation();
	return FVector2D(R.Pitch, R.Yaw);
}

double FVerseBotAimSystem::AngleBetween(const FVector2D& A, const FVector2D& B)
{
	const double DPitch = B.X - A.X;
	const double DYaw = FVerseBotAimController::YawDelta(A.Y, B.Y) * FMath::Cos(FMath::DegreesToRadians(0.5 * (A.X + B.X)));
	return FMath::Sqrt(DPitch * DPitch + DYaw * DYaw);
}

void FVerseBotAimSystem::Reset(const UVerseBotTier& Tier, uint64 Seed, float EffectiveSkill)
{
	ReactionRng = FVerseRng(Seed, 5, EVerseRngSalt::Aim);
	Aim.Reset(FVerseBotAimParams::FromTier(Tier), Seed, FVector2D::ZeroVector);
	Tracker.Reset(FVerseBotTrackParams::FromTier(Tier), Seed);
	Recoil.Reset(FVerseBotRecoilParams::FromTier(Tier));
	FireGate.Reset(FVerseBotFireParams::FromTier(Tier, EffectiveSkill));
	NoSight.Reset(FVerseBotNoSightParams::FromTier(Tier), Seed);
	ReactionParams = FVerseBotReactionParams::FromTier(Tier);
	TrackLatencyS = Tier.TrackLatencyMs / 1000.0;
	ViewHistory.Reset();
	OwnDeltaSum = FVector2D::ZeroVector;
	LastDelta = FVector2D::ZeroVector;
	LastView = FVector2D::ZeroVector;
	bHaveLastView = false;
	LastMagazine = -1;
	LastSlot = EVerseLoadoutSlot::Primary;
	ReactAtS = 0.0;
	LastSightS = -1.0e9;
	bEngaged = false;
}

void FVerseBotAimSystem::SetTier(const UVerseBotTier& Tier, float EffectiveSkill)
{
	Aim.SetParams(FVerseBotAimParams::FromTier(Tier));
	Tracker.SetParams(FVerseBotTrackParams::FromTier(Tier));
	Recoil.SetParams(FVerseBotRecoilParams::FromTier(Tier));
	FireGate.SetParams(FVerseBotFireParams::FromTier(Tier, EffectiveSkill));
	NoSight.SetParams(FVerseBotNoSightParams::FromTier(Tier));
	ReactionParams = FVerseBotReactionParams::FromTier(Tier);
	TrackLatencyS = Tier.TrackLatencyMs / 1000.0;
}

FVector2D FVerseBotAimSystem::PerceivedView(double NowS, const FVector2D& ViewNow) const
{
	const double At = NowS - TrackLatencyS;
	for (int32 I = ViewHistory.Num() - 1; I >= 0; --I)
	{
		if (ViewHistory[I].TimeS <= At + 1.0e-9)
		{
			const FViewSample& S = ViewHistory[I];
			return S.View + (OwnDeltaSum - S.OwnDeltaSum);
		}
	}
	return ViewHistory.Num() > 0 ? ViewHistory[0].View + (OwnDeltaSum - ViewHistory[0].OwnDeltaSum) : ViewNow;
}

FVerseBotAimOutput FVerseBotAimSystem::Tick(const FVerseBotAimInput& In)
{
	FVerseBotAimOutput Out;
	if (!In.Frame)
	{
		return Out;
	}
	const FVersePerceptFrame& Frame = *In.Frame;
	const FVerseSelfPercept& Self = Frame.Self;
	const double NowS = double(Frame.ServerTimeMs) / 1000.0;
	const double Dt = FMath::Max(1.0e-4, In.DtS);
	const FVector2D View(Self.ViewRotation.Pitch, FRotator::NormalizeAxis(Self.ViewRotation.Yaw));

	// ---- Own shots and view, from the own HUD. Shots first: the kick of a shot already shows in
	// the view of the frame whose magazine count reports it.
	Recoil.Tick(NowS); // ends a spray that is over before a new shot counts from index 0
	if (In.Weapon && Self.ActiveSlot == LastSlot && LastMagazine >= 0 && Self.Magazine < LastMagazine)
	{
		for (int32 Shot = 0; Shot < LastMagazine - Self.Magazine; ++Shot)
		{
			const FVector2D Kick = FVerseBotRecoilControl::PatternKick(*In.Weapon, Recoil.GetShotIndex(), Self.Stance, In.AdsBlend);
			Recoil.OnShot(NowS, Kick, In.Weapon->RecoilKickTime + Dt, In.Weapon->PatternResetTime);
			FireGate.NotifyShot(NowS);
		}
	}
	LastMagazine = Self.Magazine;
	LastSlot = Self.ActiveSlot;
	if (bHaveLastView)
	{
		const FVector2D Moved(View.X - LastView.X, FVerseBotAimController::YawDelta(LastView.Y, View.Y));
		Recoil.ObserveUnexplainedMotion(NowS, Moved - LastDelta);
	}
	else
	{
		Aim.SyncHand(View);
	}
	Recoil.Tick(NowS);

	ViewHistory.Add({NowS, View, OwnDeltaSum});
	while (ViewHistory.Num() > 2 && ViewHistory[1].TimeS < NowS - TrackLatencyS - 0.25)
	{
		ViewHistory.RemoveAt(0, 1, EAllowShrinking::No);
	}
	if (!Recoil.IsSpraying())
	{
		// No spray running: the hand is where the bot perceives its view (leftover climb gets corrected).
		Aim.SyncHand(PerceivedView(NowS, View));
	}

	// ---- Target: sighting, reaction, tracking.
	const FVerseSightPercept* Sighting = Frame.Sightings.Num() > 0 ? &Frame.Sightings[0] : nullptr;
	if (Sighting)
	{
		if (!bEngaged || NowS - LastSightS > ReengageGapS)
		{
			EVerseBotStimulus Stimulus = EVerseBotStimulus::Sight;
			if (Sighting->bPeripheral)
			{
				Stimulus |= EVerseBotStimulus::Peripheral;
			}
			if (Sighting->VisibleMask != 0 && PopCount8(Sighting->VisibleMask) <= 2)
			{
				Stimulus |= EVerseBotStimulus::PartialExposure;
			}
			ReactAtS = NowS + FVerseBotReaction::SampleMs(ReactionRng, ReactionParams, Stimulus) / 1000.0;
			Aim.Acquire(ReactAtS);
			Tracker.Clear();
			Tracker.BeginEngagement();
			bEngaged = true;
		}
		Tracker.Push(NowS, *Sighting);
		LastSightS = NowS;
	}
	else if (bEngaged && NowS - LastSightS > ReengageGapS + TrackLatencyS)
	{
		bEngaged = false;
		Tracker.Clear();
	}

	FVector2D Want = Aim.GetHand();
	bool bNoisy = false;
	bool bHasPoint = false;
	FVector2D PointAngles = FVector2D::ZeroVector;
	EVerseBotFireAuthority Authority = EVerseBotFireAuthority::None;
	FVerseBotFireGateInput Gate;
	Gate.NowS = NowS;

	FVerseBotTrackedTarget Target;
	const bool bReacted = bEngaged && NowS + 1.0e-9 >= ReactAtS;
	Out.bReacting = bEngaged && !bReacted;
	if (bReacted && Tracker.Perceived(NowS, Target))
	{
		const double BoltSpeed = In.Weapon ? In.Weapon->ProjectileSpeed : FVerseBotTargetTracker::DefaultBoltSpeedMps;
		Out.AimPoint = Tracker.AimPoint(Target, Self.EyeLocation, BoltSpeed);
		Out.bTracking = true;
		PointAngles = AnglesTo(Self.EyeLocation, Out.AimPoint.Location);
		Want = PointAngles;
		bNoisy = true;
		bHasPoint = true;
		Gate.TargetHalfWidthDeg = Out.AimPoint.HalfWidthDeg;
		Gate.RangeM = Out.AimPoint.RangeM;
		Gate.bTargetSpawnProtected = Target.bSpawnProtected;
		if (Sighting)
		{
			// Visible only while the sighting is current.
			Authority = EVerseBotFireAuthority::Visible;
			Gate.bHasTarget = In.Intent.bEngage;
		}
		else if (In.Intent.bWantNoSightFire)
		{
			// Sight just lost, still following the latency-old picture: only a no-sight mode may fire.
			FVerseBotNoSightInput NoSightIn = In.Intent.NoSight;
			NoSightIn.NowS = NowS;
			NoSightIn.AimPoint = Out.AimPoint.Location;
			Authority = NoSight.Classify(NoSightIn);
			Gate.bHasTarget = Authority != EVerseBotFireAuthority::None;
		}
	}
	else if (In.Intent.bHasLookTarget)
	{
		PointAngles = AnglesTo(Self.EyeLocation, In.Intent.LookTarget);
		Want = PointAngles;
		bHasPoint = true;
		const double RangeCm = FMath::Max(1.0, FVector::Dist(Self.EyeLocation, In.Intent.LookTarget));
		if (In.Intent.bWantNoSightFire)
		{
			FVerseBotNoSightInput NoSightIn = In.Intent.NoSight;
			NoSightIn.NowS = NowS;
			NoSightIn.AimPoint = In.Intent.LookTarget;
			Authority = NoSight.Classify(NoSightIn);
			bNoisy = true;
			Gate.bHasTarget = Authority != EVerseBotFireAuthority::None;
			Gate.TargetHalfWidthDeg =
				FMath::RadiansToDegrees(FMath::Atan(FVerseBotNoSightFire::SuppressionRadiusCm * 0.5 / RangeCm));
			Gate.RangeM = RangeCm / 100.0;
		}
	}

	// ---- Hand step with the recoil offset, through the normal controller.
	const FVector2D RecoilOffset = Recoil.IsSpraying() ? Recoil.GetHandOffsetDeg() : FVector2D::ZeroVector;
	const FVector2D Delta = Aim.Step(NowS, Dt, Want + RecoilOffset, bNoisy);
	OwnDeltaSum += Delta;
	LastDelta = Delta;
	LastView = View;
	bHaveLastView = true;
	Out.LookDeltaDeg = FVector2f(float(Delta.X), float(Delta.Y));

	// ---- Fire gate on where the bolts go next (the view after this delta).
	if (bHasPoint)
	{
		const FVector2D ViewNext(View.X + Delta.X, View.Y + Delta.Y);
		Out.AimErrorDeg = AngleBetween(ViewNext, PointAngles);
		Gate.AimErrorDeg = Out.AimErrorDeg;
	}
	Gate.bSprinting = In.bSprinting;
	Gate.bSliding = In.bSliding;
	Gate.bCanFire = !In.bReloading && (Self.Magazine > 0 || Self.bChambered) && Self.Phase == EVerseCombatPhase::Alive;
	Gate.bRecoilSettled = !Recoil.IsSpraying();
	if (In.Weapon)
	{
		Gate.bAutomatic = In.Weapon->FireMode == EVerseFireMode::Auto;
		Gate.FireIntervalS = In.Weapon->FireInterval();
		Gate.FirstShotRestS = In.Weapon->FirstShotRestTime;
		Gate.PatternResetS = In.Weapon->PatternResetTime;
	}
	const FVerseBotFireGateOutput Fire = FireGate.Evaluate(Gate);
	Out.Block = Fire.Block;
	if (Fire.bAds)
	{
		Out.Buttons |= uint32(EVerseInputButton::Ads);
	}
	if (Fire.bHoldFire && Authority != EVerseBotFireAuthority::None)
	{
		Out.Buttons |= uint32(EVerseInputButton::Fire);
		if (Fire.bPressFire)
		{
			Out.Pressed |= uint32(EVerseInputButton::Fire);
		}
		Out.Authority = Authority;
	}
	return Out;
}

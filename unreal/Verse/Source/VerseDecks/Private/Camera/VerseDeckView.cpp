#include "Camera/VerseDeckView.h"

#include "VerseCoords.h"

namespace
{
	using Verse::Coords::MetresToCm;

	double Smooth(double Dt, double TimeConstant)
	{
		return 1.0 - FMath::Exp(-Dt / TimeConstant);
	}
}

namespace Verse::DeckView
{
	TConstArrayView<EVerseDeckView> Order()
	{
		static const EVerseDeckView Views[] = { EVerseDeckView::Overview, EVerseDeckView::Third, EVerseDeckView::First };
		return Views;
	}

	const TCHAR* Name(EVerseDeckView View)
	{
		switch (View)
		{
		case EVerseDeckView::Overview: return TEXT("overview");
		case EVerseDeckView::Third: return TEXT("third");
		case EVerseDeckView::First: return TEXT("first");
		}
		return TEXT("third");
	}

	TOptional<EVerseDeckView> FromName(const FString& InName)
	{
		for (const EVerseDeckView View : Order())
		{
			if (InName.Equals(Name(View), ESearchCase::IgnoreCase))
			{
				return View;
			}
		}
		return {};
	}

	TOptional<EVerseDeckView> ForKey(FName KeyName)
	{
		static const TMap<FName, EVerseDeckView> Keys = {
			{ FName(TEXT("One")), EVerseDeckView::Overview },
			{ FName(TEXT("NumPadOne")), EVerseDeckView::Overview },
			{ FName(TEXT("Two")), EVerseDeckView::Third },
			{ FName(TEXT("NumPadTwo")), EVerseDeckView::Third },
			{ FName(TEXT("Three")), EVerseDeckView::First },
			{ FName(TEXT("NumPadThree")), EVerseDeckView::First },
		};
		if (const EVerseDeckView* View = Keys.Find(KeyName))
		{
			return *View;
		}
		return {};
	}

	EVerseDeckView Resolve(EVerseDeckView Wanted, bool bEyeCapable)
	{
		return Wanted == EVerseDeckView::First && !bEyeCapable ? EVerseDeckView::Third : Wanted;
	}

	EVerseDeckView Cycle(EVerseDeckView Current, bool bEyeCapable)
	{
		const TConstArrayView<EVerseDeckView> Views = Order();
		const int32 From = Views.IndexOfByKey(Resolve(Current, bEyeCapable));
		for (int32 Step = 1; Step <= Views.Num(); ++Step)
		{
			const EVerseDeckView Next = Views[(From + Step) % Views.Num()];
			if (Resolve(Next, bEyeCapable) == Next)
			{
				return Next;
			}
		}
		return Current;
	}

	EVerseDeckView Normalize(const FString& Stored)
	{
		const TOptional<EVerseDeckView> View = FromName(Stored);
		return View.IsSet() ? View.GetValue() : EVerseDeckView::Third;
	}
}

FVerseZoomState VerseZoomStep(const FVerseZoomState& S, double Factor, double MinCm, double MaxCm, double Handover)
{
	if (!(Factor > 0.0) || !FMath::IsFinite(Factor) || Factor == 1.0)
	{
		return S;
	}
	const double Log = FMath::Loge(Factor);
	if (S.Person == EVerseDeckPerson::First)
	{
		if (Log < 0.0)
		{
			return { EVerseDeckPerson::First, MinCm, 0.0 };
		}
		const double Push = FMath::Max(0.0, S.Push) + Log;
		return Push >= Handover ? FVerseZoomState{ EVerseDeckPerson::Third, MinCm, 0.0 } : FVerseZoomState{ EVerseDeckPerson::First, MinCm, Push };
	}
	const double Wanted = S.DistanceCm * Factor;
	if (Wanted >= MinCm)
	{
		return { EVerseDeckPerson::Third, FMath::Min(MaxCm, Wanted), 0.0 };
	}
	const double Over = FMath::Loge(Wanted / MinCm);
	const double Push = FMath::Min(0.0, S.Push) + Over;
	return Push <= -Handover ? FVerseZoomState{ EVerseDeckPerson::First, MinCm, 0.0 } : FVerseZoomState{ EVerseDeckPerson::Third, MinCm, Push };
}

FVerseShoulderTuning::FVerseShoulderTuning()
	: DistanceCm(MetresToCm(2.4))
	, MinDistanceCm(MetresToCm(1.2))
	, MaxDistanceCm(MetresToCm(5.0))
	, PivotHeightCm(MetresToCm(1.74))
	, EyeHeightCm(MetresToCm(1.65))
	, EyeForwardCm(MetresToCm(0.1))
	, SideCm(MetresToCm(-0.47))
	, DragDegPerPx(FMath::RadiansToDegrees(0.0042))
	, LockDegPerPx(FMath::RadiansToDegrees(0.0022))
	, ClearanceCm(MetresToCm(0.24))
	, EyeClearanceCm(MetresToCm(0.12))
	, RegainCmPerS(MetresToCm(3.2))
{
}

FVerseShoulderRig::FVerseShoulderRig()
{
	PitchDeg = Tuning.PitchDeg;
	DistanceCm = Tuning.DistanceCm;
	ActualCm = Tuning.DistanceCm;
	Zoomed = Tuning.DistanceCm;
	FovThirdDeg = Tuning.HfovThirdDeg;
	FovFirstDeg = Tuning.HfovFirstDeg;
}

void FVerseShoulderRig::PitchLimits(double& OutMin, double& OutMax) const
{
	OutMin = Person == EVerseDeckPerson::First ? Tuning.FirstMinPitchDeg : Tuning.ThirdMinPitchDeg;
	OutMax = Person == EVerseDeckPerson::First ? Tuning.FirstMaxPitchDeg : Tuning.ThirdMaxPitchDeg;
}

void FVerseShoulderRig::Look(double Dx, double Dy, bool bCaptured)
{
	const double Sens = FMath::Clamp(FMath::IsFinite(Sensitivity) ? Sensitivity : 1.0, Tuning.MinSensitivity, Tuning.MaxSensitivity);
	const double Rate = (bCaptured ? Tuning.LockDegPerPx : Tuning.DragDegPerPx) * Sens;
	double Min = 0.0;
	double Max = 0.0;
	PitchLimits(Min, Max);
	// Mouse right turns right (Unreal yaw grows clockwise); mouse down looks down unless inverted.
	YawDeg = Verse::Coords::NormalizeDeg(YawDeg + Dx * Rate);
	PitchDeg = FMath::Clamp(PitchDeg - (bInvertY ? -Dy : Dy) * Rate, Min, Max);
}

TOptional<EVerseDeckPerson> FVerseShoulderRig::Zoom(double Factor)
{
	const FVerseZoomState Next = VerseZoomStep({ Person, DistanceCm, Push }, Factor, Tuning.MinDistanceCm, Tuning.MaxDistanceCm, Tuning.Handover);
	TOptional<EVerseDeckPerson> Changed;
	if (Next.Person != Person)
	{
		Changed = Next.Person;
	}
	Person = Next.Person;
	DistanceCm = Next.DistanceCm;
	Push = Next.Push;
	return Changed;
}

void FVerseShoulderRig::SetPerson(EVerseDeckPerson NewPerson)
{
	if (NewPerson != Person)
	{
		Person = NewPerson;
		Push = 0.0;
	}
}

double FVerseShoulderRig::Hfov() const
{
	auto ClampFov = [this](double Deg, double Fallback)
	{
		return FMath::IsFinite(Deg) ? FMath::Clamp(Deg, Tuning.MinHfovDeg, Tuning.MaxHfovDeg) : Fallback;
	};
	const double Third = ClampFov(FovThirdDeg, Tuning.HfovThirdDeg);
	const double First = ClampFov(FovFirstDeg, Tuning.HfovFirstDeg);
	return Third + (First - Third) * FirstShare;
}

void FVerseShoulderRig::SnapBehind(double HeadingDeg)
{
	YawDeg = Verse::Coords::NormalizeDeg(HeadingDeg);
	PitchDeg = Person == EVerseDeckPerson::First ? 0.0 : Tuning.PitchDeg;
	bPrimed = false;
}

void FVerseShoulderRig::FaceToward(const FVector& FromCm, const FVector& ToCm)
{
	const FVector2D Delta(ToCm.X - FromCm.X, ToCm.Y - FromCm.Y);
	if (Delta.Size() < 1e-4)
	{
		return;
	}
	YawDeg = Verse::Coords::NormalizeDeg(FMath::RadiansToDegrees(FMath::Atan2(Delta.Y, Delta.X)));
}

void FVerseShoulderRig::Update(double DtS, const FVerseRigBody& Body, const FVerseSegmentTest& Test)
{
	const FVerseShoulderTuning& T = Tuning;
	const double Dt = FMath::Clamp(DtS, 0.0, 0.1);
	const FVector Goal(Body.FeetCm.X, Body.FeetCm.Y, Body.FeetCm.Z + T.PivotHeightCm);
	const double WantFirst = Person == EVerseDeckPerson::First ? 1.0 : 0.0;
	double ZoomOut = 0.0;
	if (!bPrimed)
	{
		Pivot = Goal;
		Zoomed = DistanceCm;
		ActualCm = DistanceCm;
		Blend = WantFirst;
		bPrimed = true;
	}
	else
	{
		const double K = Smooth(Dt, T.FollowS);
		const double Kz = Smooth(Dt, T.FollowZS);
		Pivot.X += (Goal.X - Pivot.X) * K;
		Pivot.Y += (Goal.Y - Pivot.Y) * K;
		Pivot.Z += (Goal.Z - Pivot.Z) * Kz;
		const double Before = Zoomed;
		Zoomed += (DistanceCm - Zoomed) * Smooth(Dt, T.ZoomS);
		ZoomOut = FMath::Max(0.0, Zoomed - Before);
		Blend += (WantFirst - Blend) * Smooth(Dt, T.PersonS);
		if (FMath::Abs(WantFirst - Blend) < 1e-3)
		{
			Blend = WantFirst;
		}
	}
	double Min = 0.0;
	double Max = 0.0;
	PitchLimits(Min, Max);
	PitchDeg = FMath::Clamp(PitchDeg, Min, Max);
	const double S = Blend * Blend * (3.0 - 2.0 * Blend);
	FirstShare = S;

	const FRotator View(PitchDeg, YawDeg, 0.0);
	const FVector Dir = View.Vector();
	const FVector Right = FRotationMatrix(FRotator(0.0, YawDeg, 0.0)).GetUnitAxis(EAxis::Y);

	// Third person: the shoulder point sideways from the head, pulled in when a wall is that close.
	FVector Shoulder = Pivot + Right * T.SideCm;
	if (Test && S < 1.0)
	{
		const TOptional<double> Hit = Test(Pivot, Shoulder);
		if (Hit.IsSet())
		{
			const double Keep = FMath::Max(0.0, Hit.GetValue() - T.ClearanceCm / FMath::Abs(T.SideCm));
			Shoulder = Pivot + (Shoulder - Pivot) * Keep;
		}
	}
	double Reach = Zoomed;
	if (Test && S < 1.0)
	{
		const TOptional<double> Hit = Test(Shoulder, Shoulder - Dir * Zoomed);
		if (Hit.IsSet())
		{
			Reach = FMath::Max(MetresToCm(0.15), Hit.GetValue() * Zoomed - T.ClearanceCm);
		}
	}
	// In at once (never through a wall), back out smoothly.
	ActualCm = Reach < ActualCm ? Reach : FMath::Min(Reach, ActualCm + T.RegainCmPerS * Dt + ZoomOut);
	const FVector ThirdLocation = Shoulder - Dir * ActualCm;

	// First person: the eyes on the body's axis (no sideways lag), the pivot's eased height.
	const FVector Flat(FMath::Cos(FMath::DegreesToRadians(YawDeg)), FMath::Sin(FMath::DegreesToRadians(YawDeg)), 0.0);
	const FVector Head(Body.FeetCm.X, Body.FeetCm.Y, Pivot.Z - (T.PivotHeightCm - T.EyeHeightCm));
	FVector Eye = Head + Flat * T.EyeForwardCm;
	if (Test && S > 0.0)
	{
		const double Probe = T.EyeForwardCm + T.EyeClearanceCm;
		const TOptional<double> Hit = Test(Head, Head + Flat * Probe);
		if (Hit.IsSet())
		{
			Eye = Head + Flat * FMath::Max(0.0, Hit.GetValue() * Probe - T.EyeClearanceCm);
		}
	}
	Location = ThirdLocation + (Eye - ThirdLocation) * S;
	Rotation = View;
}

FVerseOverviewCamera::FVerseOverviewCamera()
	: DistanceCm(MetresToCm(40.0))
	, MinDistanceCm(MetresToCm(8.0))
	, MaxDistanceCm(MetresToCm(120.0))
{
}

void FVerseOverviewCamera::Pan(const FVector2D& Input, double DtS)
{
	if (Input.IsNearlyZero())
	{
		return;
	}
	const FVector2D Clamped = Input.GetSafeNormal() * FMath::Min(1.0, Input.Size());
	const double Yaw = FMath::DegreesToRadians(YawDeg);
	const FVector Forward(FMath::Cos(Yaw), FMath::Sin(Yaw), 0.0);
	const FVector Right(-FMath::Sin(Yaw), FMath::Cos(Yaw), 0.0);
	CentreCm += (Right * Clamped.X + Forward * Clamped.Y) * DistanceCm * PanShare * FMath::Clamp(DtS, 0.0, 0.1);
}

void FVerseOverviewCamera::Zoom(double Factor)
{
	if (Factor > 0.0 && FMath::IsFinite(Factor))
	{
		DistanceCm = FMath::Clamp(DistanceCm * Factor, MinDistanceCm, MaxDistanceCm);
	}
}

void FVerseOverviewCamera::Look(double DxDeg)
{
	YawDeg = Verse::Coords::NormalizeDeg(YawDeg + DxDeg);
}

void FVerseOverviewCamera::Focus(const FVector& PointCm)
{
	SavedCentre = CentreCm;
	SavedDistance = DistanceCm;
	SavedYaw = YawDeg;
	bHasSaved = true;
	CentreCm = PointCm;
}

bool FVerseOverviewCamera::Return()
{
	if (!bHasSaved)
	{
		return false;
	}
	CentreCm = SavedCentre;
	DistanceCm = SavedDistance;
	YawDeg = SavedYaw;
	bHasSaved = false;
	return true;
}

void FVerseOverviewCamera::Update()
{
	Rotation = FRotator(PitchDeg, YawDeg, 0.0);
	Location = CentreCm - Rotation.Vector() * DistanceCm;
}

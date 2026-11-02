#include "VerseCoords.h"

// The only file where the metre/centimetre factor appears (coordinates.md 4, test 14).

namespace Verse::Coords
{
	namespace
	{
		constexpr double Pi = UE_DOUBLE_PI;
		constexpr double DegPerRad = 180.0 / UE_DOUBLE_PI;
		constexpr double RadPerDeg = UE_DOUBLE_PI / 180.0;
	}

	double MetresToCm(double Metres)
	{
		return Metres * CmPerMetre;
	}

	double CmToMetres(double Cm)
	{
		return Cm / CmPerMetre;
	}

	FVector ToUnrealPosition(const FVerseThreeVector& P, const FVerseDeckFrame& Deck)
	{
		return FVector(P.X * CmPerMetre, P.Z * CmPerMetre, P.Y * CmPerMetre) + Deck.OriginCm;
	}

	FVerseThreeVector ToThreePosition(const FVector& PCm, const FVerseDeckFrame& Deck)
	{
		const FVector Local = PCm - Deck.OriginCm;
		return FVerseThreeVector(Local.X / CmPerMetre, Local.Z / CmPerMetre, Local.Y / CmPerMetre);
	}

	FVector ToUnrealDirection(const FVerseThreeVector& D)
	{
		return FVector(D.X, D.Z, D.Y);
	}

	FVerseThreeVector ToThreeDirection(const FVector& D)
	{
		return FVerseThreeVector(D.X, D.Z, D.Y);
	}

	FBox ToUnrealBox(double X0, double X1, double Y0, double Y1, double Z0, double Z1, const FVerseDeckFrame& Deck)
	{
		const FVector Min = FVector(X0, Z0, Y0) * CmPerMetre + Deck.OriginCm;
		const FVector Max = FVector(X1, Z1, Y1) * CmPerMetre + Deck.OriginCm;
		return FBox(Min, Max);
	}

	double NormalizeDeg(double Deg)
	{
		return FRotator::NormalizeAxis(Deg);
	}

	double WrapPi(double Rad)
	{
		double A = FMath::Fmod(Rad, 2.0 * Pi);
		if (A <= -Pi)
		{
			A += 2.0 * Pi;
		}
		else if (A > Pi)
		{
			A -= 2.0 * Pi;
		}
		return A;
	}

	double ToUnrealHeadingDegFromDeg(double ThreeYawDeg)
	{
		return NormalizeDeg(90.0 - ThreeYawDeg);
	}

	double ToUnrealHeadingDeg(double ThreeYawRad)
	{
		return ToUnrealHeadingDegFromDeg(ThreeYawRad * DegPerRad);
	}

	double ToThreeYawRad(double UnrealYawDeg)
	{
		return WrapPi((90.0 - UnrealYawDeg) * RadPerDeg);
	}

	double ToUnrealYawRateDeg(double ThreeYawRateRad)
	{
		return -ThreeYawRateRad * DegPerRad;
	}

	FRotator ToUnrealViewRotation(double ThreeYawRad, double ThreePitchRad)
	{
		return FRotator(ThreePitchRad * DegPerRad, ToUnrealHeadingDeg(ThreeYawRad), 0.0);
	}

	double ToUnrealMeshYawDeg(double ThreeYawRad)
	{
		return NormalizeDeg(-ThreeYawRad * DegPerRad);
	}

	FQuat ToUnrealQuat(const FQuat& ThreeQuat)
	{
		return FQuat(-ThreeQuat.X, -ThreeQuat.Z, -ThreeQuat.Y, ThreeQuat.W);
	}

	FQuat ToThreeQuat(const FQuat& UnrealQuat)
	{
		return FQuat(-UnrealQuat.X, -UnrealQuat.Z, -UnrealQuat.Y, UnrealQuat.W);
	}

	FTransform ToUnrealSocketTransform(const FVerseThreeVector& P, double ThreeYawDeg, ESocketUse Use, const FVerseDeckFrame& Deck)
	{
		const double Yaw = Use == ESocketUse::Heading ? ToUnrealHeadingDegFromDeg(ThreeYawDeg) : NormalizeDeg(-ThreeYawDeg);
		return FTransform(FRotator(0.0, Yaw, 0.0), ToUnrealPosition(P, Deck), FVector::OneVector);
	}
}

FVector UVerseCoordsLibrary::ThreeToUnrealPosition(const FVerseThreeVector& P, const FVerseDeckFrame& Deck)
{
	return Verse::Coords::ToUnrealPosition(P, Deck);
}

FVerseThreeVector UVerseCoordsLibrary::UnrealToThreePosition(const FVector& PCm, const FVerseDeckFrame& Deck)
{
	return Verse::Coords::ToThreePosition(PCm, Deck);
}

double UVerseCoordsLibrary::ThreeYawDegToUnrealHeading(double ThreeYawDeg)
{
	return Verse::Coords::ToUnrealHeadingDegFromDeg(ThreeYawDeg);
}

double UVerseCoordsLibrary::ThreeYawDegToUnrealMeshYaw(double ThreeYawDeg)
{
	return Verse::Coords::NormalizeDeg(-ThreeYawDeg);
}

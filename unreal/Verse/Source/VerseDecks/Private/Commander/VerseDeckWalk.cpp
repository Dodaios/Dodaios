#include "Commander/VerseDeckWalk.h"

#include "Decks/VerseDeckManifest.h"

namespace Verse::DeckWalk
{
	double WrapDeg(double Deg)
	{
		return FMath::RadiansToDegrees(FMath::Atan2(FMath::Sin(FMath::DegreesToRadians(Deg)), FMath::Cos(FMath::DegreesToRadians(Deg))));
	}

	FFacing BodyFacing(double ViewYawDeg, const FVector2D& MoveDir)
	{
		FFacing Out;
		const double MoveYaw = FMath::RadiansToDegrees(FMath::Atan2(MoveDir.Y, MoveDir.X));
		const double Off = WrapDeg(MoveYaw - ViewYawDeg);
		Out.bReverse = FMath::Abs(Off) > BackpedalBeyondDeg;
		const double Lean = Out.bReverse ? WrapDeg(Off - 180.0) : Off;
		Out.YawDeg = WrapDeg(ViewYawDeg + FMath::Clamp(Lean, -StrafeLeanDeg, StrafeLeanDeg));
		return Out;
	}

	TOptional<FVector2D> WalkDirection(double ViewYawDeg, const FVector2D& Axes)
	{
		if (FMath::IsNearlyZero(Axes.X) && FMath::IsNearlyZero(Axes.Y))
		{
			return {};
		}
		const double Rad = FMath::DegreesToRadians(ViewYawDeg);
		const FVector2D Forward(FMath::Cos(Rad), FMath::Sin(Rad));
		// Yaw grows toward +Y (clockwise seen from above): the view's right is yaw + 90.
		const FVector2D Right(-Forward.Y, Forward.X);
		const FVector2D Dir = Forward * Axes.Y + Right * Axes.X;
		if (Dir.IsNearlyZero())
		{
			return {};
		}
		return Dir.GetSafeNormal();
	}

	double TurnToward(double YawDeg, double TargetDeg, double RateDegPerS, double DtS)
	{
		const double Delta = WrapDeg(TargetDeg - YawDeg);
		const double Step = FMath::Sign(Delta) * FMath::Min3(FMath::Abs(Delta), RateDegPerS * DtS, FMath::Abs(Delta) * FMath::Min(1.0, DtS * 10.0));
		return WrapDeg(YawDeg + Step);
	}

	double TurnPace(double YawDeg, double HeadingDeg)
	{
		const double Off = FMath::Min(90.0, FMath::Abs(WrapDeg(HeadingDeg - YawDeg)));
		return 0.35 + 0.65 * FMath::Cos(FMath::DegreesToRadians(Off));
	}

	const FVerseDeckStation* StationWithin(TConstArrayView<FVerseDeckStation> Stations, const FVector& FeetCm, const FVector2D& Facing, double ReachCm)
	{
		const FVerseDeckStation* Best = nullptr;
		double BestScore = TNumericLimits<double>::Max();
		const bool bFacing = !Facing.IsNearlyZero();
		for (const FVerseDeckStation& Station : Stations)
		{
			const FVector At = Station.Transform.GetLocation();
			const FVector2D Delta(At.X - FeetCm.X, At.Y - FeetCm.Y);
			const double Distance = Delta.Size();
			if (Distance > ReachCm)
			{
				continue;
			}
			// One under the commander's feet counts as in front.
			const double Cos = bFacing && Distance > 30.0 ? FVector2D::DotProduct(Delta, Facing.GetSafeNormal()) / Distance : 1.0;
			const double Score = Distance * (1.5 - 0.5 * Cos);
			if (Score < BestScore)
			{
				BestScore = Score;
				Best = &Station;
			}
		}
		return Best;
	}
}

void FVerseWalkOrders::Give(FName InDeck, const FVector& TargetCm)
{
	Deck = InDeck;
	Target = TargetCm;
	bHasTarget = true;
	++Order;
}

void FVerseWalkOrders::Clear()
{
	bHasTarget = false;
}

void FVerseWalkOrders::Arrive(FName InDeck)
{
	Deck = InDeck;
	bHasTarget = false;
}

TOptional<FVector> FVerseWalkOrders::TargetOn(FName InDeck) const
{
	if (bHasTarget && InDeck == Deck)
	{
		return Target;
	}
	return {};
}

#include "Abilities/VerseHoverboard.h"

namespace VerseBoard
{
	float BoardSpeed(bool bBoost)
	{
		return bBoost ? BoostCm : SpeedCm;
	}

	FVector2D Glide(FVector2D V, const FVector2D* Direction, bool bBoost, float Dt)
	{
		const FVector2D Target = Direction ? *Direction * BoardSpeed(bBoost) : FVector2D::ZeroVector;
		const double K = 1.0 - FMath::Exp(-(Direction ? Accel : Coast) * FMath::Max(0.f, Dt));
		V += (Target - V) * K;
		if (!Direction && V.Size() < StoppedCm)
		{
			V = FVector2D::ZeroVector;
		}
		return V;
	}

	FVector2D Absorb(FVector2D V, FVector2D Wanted, FVector2D Moved, float Dt)
	{
		if (Dt <= 0.f)
		{
			return V;
		}
		const double Want = Wanted.Size();
		if (Want < 1e-4 || Moved.Size() >= Want * 0.98)
		{
			return V;
		}
		return Moved / Dt;
	}

	float DeployStep(float Share, bool bOn, float Dt, bool bReduced)
	{
		if (bReduced)
		{
			return bOn ? 1.f : 0.f;
		}
		const float Step = Dt / DeployS;
		return bOn ? FMath::Min(1.f, Share + Step) : FMath::Max(0.f, Share - Step);
	}

	float DeployScale(float Share)
	{
		const float T = FMath::Clamp(Share, 0.f, 1.f) - 1.f;
		constexpr float C = 1.4f;
		return 1.f + (C + 1.f) * T * T * T + C * T * T;
	}

	float HoverHeight(float Share, float TimeS, float Speed, bool bReduced)
	{
		const float S = FMath::Clamp(Share, 0.f, 1.f);
		if (bReduced)
		{
			return LiftCm * S;
		}
		// A slow float at rest, almost none at speed (the board planes).
		const float Calm = 1.f - FMath::Min(1.f, Speed / SpeedCm) * 0.7f;
		return (LiftCm + FMath::Sin(TimeS * 2.4f) * 1.8f * Calm) * S;
	}

	FVector2D Lean(float Speed, float TurnRate, bool bReduced)
	{
		if (bReduced)
		{
			return FVector2D::ZeroVector;
		}
		const float Pitch = FMath::Min(1.f, Speed / BoostCm) * 0.12f;
		const float Roll = FMath::Clamp(TurnRate * FMath::Min(1.f, Speed / SpeedCm) * 0.06f, -0.2f, 0.2f);
		return FVector2D(Pitch, Roll);
	}
}

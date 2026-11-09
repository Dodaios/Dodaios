#include "Abilities/VerseCloak.h"

namespace VerseCloak
{
	FName BoneName(int32 Column, int32 Segment)
	{
		static const TCHAR* Names[Columns] = {TEXT("R"), TEXT("C"), TEXT("L")};
		return FName(*FString::Printf(TEXT("Cloak_%s%d"), Names[FMath::Clamp(Column, 0, Columns - 1)], Segment == 0 ? 1 : 2));
	}

	FAngles Target(float Forward, float Right, float YawRate, int32 Side)
	{
		// The reference works in its own frame: lateral positive toward the body's left, yaw
		// rate positive turning left, roll negative = hem to the body's right.
		const float Lateral = -Right;
		const float TurnLeft = -YawRate;
		const float Speed = FMath::Sqrt(Forward * Forward + Lateral * Lateral);
		FAngles A;
		A.Lift = FMath::Clamp(0.3f * Forward, -0.08f, 0.62f) * (Side == 0 ? 1.f : 0.88f) + 0.04f * FMath::Abs(Lateral);
		const float Roll = FMath::Clamp(-0.09f * Lateral - 0.05f * TurnLeft, -0.3f, 0.3f) + Side * 0.05f * FMath::Min(Speed, 2.5f);
		A.Swing = -Roll;
		return A;
	}

	FSim::FSim()
	{
		for (int32 I = 0; I < Columns; ++I)
		{
			Cols[I].Side = I - 1;
			Cols[I].Phase = I * 2.1f;
		}
	}

	void FSim::Reset()
	{
		bPrimed = false;
		Forward = Right = Turn = 0.f;
		for (FColumn& C : Cols)
		{
			C.Upper = C.Lower = C.UpperRate = C.LowerRate = FAngles();
		}
	}

	void FSim::Update(float InDt, const FVector& Location, float YawDeg, bool bStill)
	{
		const float Dt = FMath::Clamp(InDt, 1e-4f, 0.1f);
		if (!bPrimed)
		{
			Last = Location;
			LastYaw = YawDeg;
			bPrimed = true;
		}
		const FVector V = (Location - Last) / 100.0 / Dt;
		const FVector F = FRotator(0.0, YawDeg, 0.0).Vector();
		const FVector R(-F.Y, F.X, 0.0);
		// A teleport (a lift ride, a respawn) is not a sprint.
		const bool bJump = FVector(V.X, V.Y, 0.0).Size() > 12.0;
		const float K = FMath::Min(1.f, Dt * 10.f);
		Forward += ((bJump ? 0.f : float(FVector::DotProduct(V, F))) - Forward) * K;
		Right += ((bJump ? 0.f : float(FVector::DotProduct(V, R))) - Right) * K;
		const float Rate = FMath::DegreesToRadians(FMath::FindDeltaAngleDegrees(LastYaw, YawDeg)) / Dt;
		Turn += ((bJump ? 0.f : Rate) - Turn) * K;
		Last = Location;
		LastYaw = YawDeg;
		Time += Dt;
		const float Speed = FMath::Sqrt(Forward * Forward + Right * Right);
		const float Flutter = bStill ? 0.f : 0.035f * FMath::Min(Speed, 2.f);

		// Small steps: a long frame must not blow the springs up.
		const int32 Steps = FMath::Max(1, FMath::CeilToInt32(Dt / (1.f / 120.f)));
		const float H = Dt / Steps;
		for (FColumn& C : Cols)
		{
			const FAngles Want = Target(Forward, Right, Turn, C.Side);
			const float TLift = Want.Lift + Flutter * FMath::Sin(Time * 6.3f + C.Phase);
			const float TSwing = Want.Swing + Flutter * 0.6f * FMath::Sin(Time * 4.7f + C.Phase * 1.7f);
			for (int32 I = 0; I < Steps; ++I)
			{
				C.UpperRate.Lift += (K1 * (TLift - C.Upper.Lift) - C1 * C.UpperRate.Lift) * H;
				C.UpperRate.Swing += (K1 * (TSwing - C.Upper.Swing) - C1 * C.UpperRate.Swing) * H;
				C.Upper.Lift += C.UpperRate.Lift * H;
				C.Upper.Swing += C.UpperRate.Swing * H;
				// The lower half bends a little further the same way, later.
				C.LowerRate.Lift += (K2 * (0.45f * C.Upper.Lift - C.Lower.Lift) - C2 * C.LowerRate.Lift) * H;
				C.LowerRate.Swing += (K2 * (0.45f * C.Upper.Swing - C.Lower.Swing) - C2 * C.LowerRate.Swing) * H;
				C.Lower.Lift += C.LowerRate.Lift * H;
				C.Lower.Swing += C.LowerRate.Swing * H;
			}
			C.Upper.Lift = FMath::Clamp(C.Upper.Lift, -0.2f, 0.9f);
			C.Lower.Lift = FMath::Clamp(C.Lower.Lift, -0.3f, 0.6f);
		}
	}
}

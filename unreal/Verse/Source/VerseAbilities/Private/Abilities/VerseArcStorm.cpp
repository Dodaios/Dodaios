#include "Abilities/VerseArcStorm.h"

namespace VerseArc
{
	FLinearColor CoreColor()
	{
		return FLinearColor(0.86f, 0.92f, 1.f, 1.f);
	}

	FLinearColor GlowColor()
	{
		return FLinearColor(1.f, 0.42f, 0.08f, 1.f);
	}

	bool IsBannedHue(const FLinearColor& Linear)
	{
		const FColor Srgb = Linear.ToFColorSRGB();
		const FLinearColor Hsv = FLinearColor(Srgb.R / 255.f, Srgb.G / 255.f, Srgb.B / 255.f).LinearRGBToHSV();
		const float Hue = Hsv.R;
		const float Saturation = Hsv.G;
		if (Saturation <= 0.7f)
		{
			return false;
		}
		return (Hue >= 170.f && Hue <= 200.f) || (Hue >= 270.f && Hue <= 330.f);
	}

	float FRand::operator()()
	{
		State += 0x6d2b79f5u;
		uint32 T = State;
		T = (T ^ (T >> 15)) * (T | 1u);
		T ^= T + (T ^ (T >> 7)) * (T | 61u);
		return float(double(T ^ (T >> 14)) / 4294967296.0);
	}

	TArray<FVector> BoltPoints(const FVector& A, const FVector& B, int32 InSegments, float InJitter, FRand& Rand)
	{
		FVector Dir = B - A;
		const double Len = Dir.Size();
		if (Len < 1e-4)
		{
			return {A, B};
		}
		Dir /= Len;
		// Two directions across the bolt.
		const FVector Helper = FMath::Abs(Dir.Z) < 0.9 ? FVector::UpVector : FVector::ForwardVector;
		const FVector U = FVector::CrossProduct(Dir, Helper).GetSafeNormal();
		const FVector V = FVector::CrossProduct(Dir, U).GetSafeNormal();
		double Span = Len * InJitter;
		TArray<FVector> Out = {A, B};
		while (Out.Num() - 1 < InSegments)
		{
			TArray<FVector> Next;
			Next.Reserve(Out.Num() * 2 - 1);
			for (int32 I = 0; I < Out.Num() - 1; ++I)
			{
				Next.Add(Out[I]);
				FVector Mid = (Out[I] + Out[I + 1]) * 0.5;
				Mid += U * ((Rand() - 0.5) * Span);
				Mid += V * ((Rand() - 0.5) * Span);
				Next.Add(Mid);
			}
			Next.Add(Out.Last());
			Out = MoveTemp(Next);
			Span *= 0.5;
		}
		return Out;
	}

	float Rise(float Level, float Dt, bool bHeld)
	{
		const float Step = FMath::Clamp(Dt, 0.f, 0.1f);
		return FMath::Clamp(Level + (bHeld ? Step / RaiseS : -Step / FallS), 0.f, 1.f);
	}

	FStrike PlanStrike(TConstArrayView<FVector> Hands, const FVector& Aim, float FloorZ, uint32 Seed)
	{
		FStrike Strike;
		if (Hands.Num() == 0)
		{
			return Strike;
		}
		FRand Rand(Seed);
		const FVector Dir = Aim.GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
		FVector HitSum = FVector::ZeroVector;
		for (const FVector& Hand : Hands)
		{
			Strike.HandsMid += Hand / Hands.Num();
			for (int32 K = 0; K < BoltsPerHand; ++K)
			{
				// Each bolt lands somewhere in a cone ahead, the first one straightest.
				const double Spread = K == 0 ? 25.0 : 90.0;
				const double Reach = ReachCm * (0.65 + Rand() * 0.45);
				FVector End = Hand + Dir * Reach;
				End.X += (Rand() - 0.5) * Spread * 2.0;
				End.Y += (Rand() - 0.5) * Spread * 2.0;
				End.Z += (Rand() - 0.6) * Spread;
				End.Z = FMath::Max(double(FloorZ) + 5.0, End.Z);
				HitSum += End;
				FBolt& Main = Strike.Bolts.AddDefaulted_GetRef();
				Main.Points = BoltPoints(Hand, End, Segments, Jitter, Rand);
				const TArray<FVector> Spine = Main.Points;
				// Forks: short side bolts off the main one.
				for (int32 F = 0; F < ForksPerBolt; ++F)
				{
					const int32 I = 2 + FMath::FloorToInt32(Rand() * (Spine.Num() - 4));
					const FVector From = Spine[I];
					FVector Off = (End - From) * (0.25 + Rand() * 0.3);
					Off.X += (Rand() - 0.5) * 90.0;
					Off.Z += (Rand() - 0.5) * 70.0;
					Off.Y += (Rand() - 0.5) * 90.0;
					FBolt& Fork = Strike.Bolts.AddDefaulted_GetRef();
					Fork.Kind = FBolt::EKind::Fork;
					Fork.Points = BoltPoints(From, From + Off, ForkSegments, ForkJitter, Rand);
				}
				// Sparks where it lands: short bursts back toward the caster and up.
				for (int32 S = 0; S < SparksPerBolt; ++S)
				{
					FVector Out(-Dir.X + (Rand() - 0.5) * 1.6, -Dir.Y + (Rand() - 0.5) * 1.6, 0.4 + Rand() * 0.8);
					Out = Out.GetSafeNormal() * (SparkCm * (0.5 + Rand()));
					FBolt& Spark = Strike.Bolts.AddDefaulted_GetRef();
					Spark.Kind = FBolt::EKind::Spark;
					Spark.Points = BoltPoints(End, End + Out, 2, 0.5f, Rand);
				}
			}
		}
		Strike.Impact = HitSum / double(Hands.Num() * BoltsPerHand);
		return Strike;
	}
}

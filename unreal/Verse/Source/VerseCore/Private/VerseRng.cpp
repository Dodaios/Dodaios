#include "VerseRng.h"

namespace
{
	constexpr uint64 GoldenGamma = 0x9E3779B97F4A7C15ull;
	constexpr uint64 IndexKey = 0xD1B54A32D192ED03ull;
	constexpr uint64 SaltKey = 0x8CB92BA72F3D8DD7ull;
}

FVerseRng::FVerseRng(uint64 Seed)
	: State(Mix(Seed))
{
}

FVerseRng::FVerseRng(uint64 Seed, uint64 Index, EVerseRngSalt Salt)
	: State(Mix(Mix(Seed) ^ Mix(Index * IndexKey + (uint64(Salt) + 1) * SaltKey)))
{
}

uint64 FVerseRng::Mix(uint64 Z)
{
	Z = (Z ^ (Z >> 30)) * 0xBF58476D1CE4E5B9ull;
	Z = (Z ^ (Z >> 27)) * 0x94D049BB133111EBull;
	return Z ^ (Z >> 31);
}

uint32 FVerseRng::Hash(uint32 A, uint32 B, uint32 C)
{
	uint64 H = Mix(uint64(A) + GoldenGamma);
	H = Mix(H ^ (uint64(B) + 2 * GoldenGamma));
	H = Mix(H ^ (uint64(C) + 3 * GoldenGamma));
	return uint32(H ^ (H >> 32));
}

uint64 FVerseRng::NextU64()
{
	State += GoldenGamma;
	return Mix(State);
}

uint32 FVerseRng::NextU32()
{
	return uint32(NextU64() >> 32);
}

double FVerseRng::NextUnit()
{
	return double(NextU64() >> 11) * (1.0 / 9007199254740992.0);
}

double FVerseRng::Range(double Min, double Max)
{
	return Min + (Max - Min) * NextUnit();
}

int32 FVerseRng::RangeInt(int32 Min, int32 MaxInclusive)
{
	if (MaxInclusive <= Min)
	{
		return Min;
	}
	const uint64 Span = uint64(int64(MaxInclusive) - int64(Min)) + 1;
	// Lemire's multiply-shift, 32-bit draw; the span of int32 values fits.
	const uint64 Draw = (uint64(NextU32()) * Span) >> 32;
	return int32(int64(Min) + int64(Draw));
}

bool FVerseRng::Chance(double P)
{
	return NextUnit() < P;
}

double FVerseRng::Gaussian(double Mean, double Sd)
{
	const double U1 = 1.0 - NextUnit(); // (0, 1]
	const double U2 = NextUnit();
	return Mean + Sd * FMath::Sqrt(-2.0 * FMath::Loge(U1)) * FMath::Cos(2.0 * UE_DOUBLE_PI * U2);
}

FVector2D FVerseRng::UnitDisk()
{
	for (;;)
	{
		const double X = 2.0 * NextUnit() - 1.0;
		const double Y = 2.0 * NextUnit() - 1.0;
		if (X * X + Y * Y <= 1.0)
		{
			return FVector2D(X, Y);
		}
	}
}

FVector FVerseRng::UnitVector()
{
	const double Z = 2.0 * NextUnit() - 1.0;
	const double Phi = 2.0 * UE_DOUBLE_PI * NextUnit();
	const double R = FMath::Sqrt(FMath::Max(0.0, 1.0 - Z * Z));
	return FVector(R * FMath::Cos(Phi), R * FMath::Sin(Phi), Z);
}

FVector FVerseRng::ConeDirection(const FVector& Axis, double HalfAngleDeg)
{
	const FVector A = Axis.GetSafeNormal(UE_DOUBLE_SMALL_NUMBER, FVector::ForwardVector);
	const double CosMax = FMath::Cos(FMath::DegreesToRadians(FMath::Clamp(HalfAngleDeg, 0.0, 180.0)));
	const double CosT = 1.0 - NextUnit() * (1.0 - CosMax);
	const double SinT = FMath::Sqrt(FMath::Max(0.0, 1.0 - CosT * CosT));
	const double Phi = 2.0 * UE_DOUBLE_PI * NextUnit();
	FVector U, V;
	A.FindBestAxisVectors(U, V);
	return (A * CosT + U * (SinT * FMath::Cos(Phi)) + V * (SinT * FMath::Sin(Phi))).GetSafeNormal();
}

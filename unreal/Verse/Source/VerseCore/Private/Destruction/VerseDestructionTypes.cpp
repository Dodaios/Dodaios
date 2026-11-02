#include "Destruction/VerseDestructionTypes.h"

namespace Verse::Destruction
{
	float FractureLoudness(EVerseFractureNoise Kind)
	{
		switch (Kind)
		{
		case EVerseFractureNoise::Breach:
			return 1.0f;
		case EVerseFractureNoise::WallBreak:
			return 0.7f;
		case EVerseFractureNoise::Glass:
			return 0.6f;
		case EVerseFractureNoise::Tile:
			return 0.5f;
		case EVerseFractureNoise::BoltHole:
			return 0.2f;
		}
		return 1.0f;
	}

	uint8 QuantizeHealth(float Hp, float MaxHp)
	{
		if (MaxHp <= 0.f)
		{
			return 0;
		}
		return uint8(FMath::Clamp(FMath::RoundToInt(255.f * Hp / MaxHp), 0, 255));
	}

	void EncodeOctahedral(const FVector& Direction, int8& OutX, int8& OutY)
	{
		const FVector N = Direction.GetSafeNormal(UE_DOUBLE_SMALL_NUMBER, FVector::ForwardVector);
		const double L1 = FMath::Abs(N.X) + FMath::Abs(N.Y) + FMath::Abs(N.Z);
		double X = N.X / L1;
		double Y = N.Y / L1;
		if (N.Z < 0.0)
		{
			const double OX = (1.0 - FMath::Abs(Y)) * (X >= 0.0 ? 1.0 : -1.0);
			const double OY = (1.0 - FMath::Abs(X)) * (Y >= 0.0 ? 1.0 : -1.0);
			X = OX;
			Y = OY;
		}
		OutX = int8(FMath::Clamp(FMath::RoundToInt(X * 127.0), -127, 127));
		OutY = int8(FMath::Clamp(FMath::RoundToInt(Y * 127.0), -127, 127));
	}

	FVector DecodeOctahedral(int8 QX, int8 QY)
	{
		double X = double(QX) / 127.0;
		double Y = double(QY) / 127.0;
		const double Z = 1.0 - FMath::Abs(X) - FMath::Abs(Y);
		if (Z < 0.0)
		{
			const double OX = (1.0 - FMath::Abs(Y)) * (X >= 0.0 ? 1.0 : -1.0);
			const double OY = (1.0 - FMath::Abs(X)) * (Y >= 0.0 ? 1.0 : -1.0);
			X = OX;
			Y = OY;
		}
		return FVector(X, Y, Z).GetSafeNormal(UE_DOUBLE_SMALL_NUMBER, FVector::ForwardVector);
	}
}

FVector FVerseBoltHole::GetAxisPointCm() const
{
	return FVector(AxisPositionMm[0], AxisPositionMm[1], AxisPositionMm[2]) / 10.0;
}

FVector FVerseBoltHole::GetAxisDirection() const
{
	return Verse::Destruction::DecodeOctahedral(AxisDirectionOct[0], AxisDirectionOct[1]);
}

bool FVerseBoltHole::ContainsPoint(const FVector& PieceLocalCm) const
{
	const FVector Dir = GetAxisDirection();
	const FVector Rel = PieceLocalCm - GetAxisPointCm();
	const double DistSq = (Rel - Dir * FVector::DotProduct(Rel, Dir)).SizeSquared();
	const double RadiusCm = double(RadiusMm) / 10.0;
	return DistSq <= RadiusCm * RadiusCm;
}

FVerseBoltHole FVerseBoltHole::Make(uint16 InPieceIndex, const FVector& AxisPointCm, const FVector& AxisDirection,
	uint8 InRadiusMm, uint32 InServerTimeMs, uint16 InEpoch)
{
	FVerseBoltHole Hole;
	Hole.PieceIndex = InPieceIndex;
	for (int32 Axis = 0; Axis < 3; ++Axis)
	{
		Hole.AxisPositionMm[Axis] = int16(FMath::Clamp(FMath::RoundToInt(AxisPointCm[Axis] * 10.0), -32768, 32767));
	}
	Verse::Destruction::EncodeOctahedral(AxisDirection, Hole.AxisDirectionOct[0], Hole.AxisDirectionOct[1]);
	Hole.RadiusMm = InRadiusMm;
	Hole.ServerTimeMs = InServerTimeMs;
	Hole.Epoch = InEpoch;
	return Hole;
}

bool FVerseBoltHole::RayPassesHoles(TConstArrayView<FVerseBoltHole> Holes, const FVector& EntryLocalCm, const FVector& ExitLocalCm)
{
	for (const FVerseBoltHole& Hole : Holes)
	{
		if (Hole.ContainsPoint(EntryLocalCm) && Hole.ContainsPoint(ExitLocalCm))
		{
			return true;
		}
	}
	return false;
}

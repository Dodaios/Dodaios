#include "Anim/VerseAnimMath.h"

namespace VerseAnim
{
void LocalToComponent(TConstArrayView<int32> Parents, TConstArrayView<FTransform> Local, TArray<FTransform>& OutCS)
{
	const int32 Num = Local.Num();
	OutCS.SetNum(Num, EAllowShrinking::No);
	for (int32 i = 0; i < Num; ++i)
	{
		const int32 P = Parents[i];
		OutCS[i] = P >= 0 ? Local[i] * OutCS[P] : Local[i];
	}
}

void ComponentToLocal(TConstArrayView<int32> Parents, TConstArrayView<FTransform> CS, TArray<FTransform>& OutLocal)
{
	const int32 Num = CS.Num();
	OutLocal.SetNum(Num, EAllowShrinking::No);
	for (int32 i = 0; i < Num; ++i)
	{
		const int32 P = Parents[i];
		OutLocal[i] = P >= 0 ? CS[i].GetRelativeTransform(CS[P]) : CS[i];
	}
}

float SolveTwoBone(FTransform& Upper, FTransform& Lower, FTransform& End, const FVector& Target, bool bKeepEndRotation)
{
	const FVector A = Upper.GetLocation();
	const FVector B = Lower.GetLocation();
	const FVector C = End.GetLocation();
	const double LenA = FVector::Dist(A, B);
	const double LenB = FVector::Dist(B, C);
	if (LenA < KINDA_SMALL_NUMBER || LenB < KINDA_SMALL_NUMBER)
	{
		return FVector::Dist(C, Target);
	}
	FVector ToTarget = Target - A;
	double Dist = ToTarget.Size();
	const FVector Dir = Dist > KINDA_SMALL_NUMBER ? ToTarget / Dist : (C - A).GetSafeNormal();
	Dist = FMath::Clamp(Dist, FMath::Abs(LenA - LenB) + 0.01, LenA + LenB - 0.001);

	// Keep the current bend plane: the joint's offset from the A-C line.
	FVector Bend = (B - A) - Dir * FVector::DotProduct(B - A, Dir);
	if (Bend.SizeSquared() < KINDA_SMALL_NUMBER)
	{
		Bend = FVector::CrossProduct(Dir, FVector::UpVector);
		if (Bend.SizeSquared() < KINDA_SMALL_NUMBER)
		{
			Bend = FVector::CrossProduct(Dir, FVector::ForwardVector);
		}
	}
	Bend.Normalize();
	const double CosA = FMath::Clamp((LenA * LenA + Dist * Dist - LenB * LenB) / (2.0 * LenA * Dist), -1.0, 1.0);
	const double SinA = FMath::Sqrt(FMath::Max(0.0, 1.0 - CosA * CosA));
	const FVector NewB = A + (Dir * CosA + Bend * SinA) * LenA;
	const FVector NewC = A + Dir * Dist;

	const FQuat EndRot = End.GetRotation();
	const FQuat Q1 = FQuat::FindBetweenNormals((B - A).GetSafeNormal(), (NewB - A).GetSafeNormal());
	Upper.SetRotation((Q1 * Upper.GetRotation()).GetNormalized());
	const FVector RotatedC = NewB + Q1.RotateVector(C - B);
	const FQuat Q2 = FQuat::FindBetweenNormals((RotatedC - NewB).GetSafeNormal(), (NewC - NewB).GetSafeNormal());
	Lower.SetLocation(NewB);
	Lower.SetRotation((Q2 * Q1 * Lower.GetRotation()).GetNormalized());
	End.SetLocation(NewC);
	End.SetRotation(bKeepEndRotation ? EndRot : (Q2 * Q1 * EndRot).GetNormalized());
	return FVector::Dist(NewC, Target);
}

void RotateInComponent(TConstArrayView<int32> Parents, TArray<FTransform>& Local, TArray<FTransform>& CS, int32 Bone, const FQuat& Delta)
{
	if (!CS.IsValidIndex(Bone))
	{
		return;
	}
	CS[Bone].SetRotation((Delta * CS[Bone].GetRotation()).GetNormalized());
	const int32 P = Parents[Bone];
	Local[Bone] = P >= 0 ? CS[Bone].GetRelativeTransform(CS[P]) : CS[Bone];
}

void SpreadRotation(TConstArrayView<int32> Parents, TArray<FTransform>& Local, TArray<FTransform>& CS,
	TConstArrayView<int32> SpineBones, TConstArrayView<float> Shares, const FVector& Axis, float AngleDeg)
{
	if (FMath::IsNearlyZero(AngleDeg) || SpineBones.Num() != Shares.Num())
	{
		return;
	}
	const FVector UnitAxis = Axis.GetSafeNormal();
	for (int32 k = 0; k < SpineBones.Num(); ++k)
	{
		const int32 Bone = SpineBones[k];
		if (Bone == INDEX_NONE)
		{
			continue;
		}
		// Each bone turns by its own share; the parent's turn already moved it.
		const FQuat Delta(UnitAxis, FMath::DegreesToRadians(AngleDeg * Shares[k]));
		LocalToComponent(Parents, Local, CS);
		RotateInComponent(Parents, Local, CS, Bone, Delta);
	}
	LocalToComponent(Parents, Local, CS);
}

float SolveFeet(TConstArrayView<int32> Parents, TArray<FTransform>& Local, TArray<FTransform>& CS, int32 Pelvis,
	TArrayView<FFootInput> Feet, float MaxDrop)
{
	if (!CS.IsValidIndex(Pelvis))
	{
		return 0.f;
	}
	float Drop = 0.f;
	for (const FFootInput& Foot : Feet)
	{
		Drop = FMath::Min(Drop, Foot.FloorOffset);
	}
	Drop = FMath::Max(Drop, -MaxDrop);
	LocalToComponent(Parents, Local, CS);
	TArray<FVector, TInlineAllocator<2>> Targets;
	for (const FFootInput& Foot : Feet)
	{
		Targets.Add(CS.IsValidIndex(Foot.Foot) ? CS[Foot.Foot].GetLocation() + FVector(0, 0, Foot.FloorOffset) : FVector::ZeroVector);
	}
	FTransform PelvisCS = CS[Pelvis];
	PelvisCS.AddToTranslation(FVector(0, 0, Drop));
	const int32 PP = Parents[Pelvis];
	Local[Pelvis] = PP >= 0 ? PelvisCS.GetRelativeTransform(CS[PP]) : PelvisCS;
	LocalToComponent(Parents, Local, CS);
	for (int32 i = 0; i < Feet.Num(); ++i)
	{
		const FFootInput& Foot = Feet[i];
		if (!CS.IsValidIndex(Foot.Thigh) || !CS.IsValidIndex(Foot.Calf) || !CS.IsValidIndex(Foot.Foot))
		{
			continue;
		}
		FTransform Thigh = CS[Foot.Thigh];
		FTransform Calf = CS[Foot.Calf];
		FTransform FootCS = CS[Foot.Foot];
		SolveTwoBone(Thigh, Calf, FootCS, Targets[i], true);
		const FQuat Tilt = FQuat::FindBetweenNormals(FVector::UpVector, Foot.FloorNormal.GetSafeNormal());
		FootCS.SetRotation((Tilt * FootCS.GetRotation()).GetNormalized());
		CS[Foot.Thigh] = Thigh;
		CS[Foot.Calf] = Calf;
		CS[Foot.Foot] = FootCS;
		Local[Foot.Thigh] = Thigh.GetRelativeTransform(CS[Parents[Foot.Thigh]]);
		Local[Foot.Calf] = Calf.GetRelativeTransform(Thigh);
		Local[Foot.Foot] = FootCS.GetRelativeTransform(Calf);
		LocalToComponent(Parents, Local, CS);
	}
	return Drop;
}
} // namespace VerseAnim

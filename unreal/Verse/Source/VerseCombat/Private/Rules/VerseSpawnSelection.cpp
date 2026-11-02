#include "Rules/VerseSpawnSelection.h"

#include "VerseRng.h"

FVerseSpawnChoice VerseSpawnSelection::Choose(
	const TArray<FVerseSpawnCandidate>& Candidates,
	const TOptional<FVector>& OpponentEye,
	TFunctionRef<bool(const FVector& From, const FVector& To)> LineClear,
	TFunctionRef<float(const FVector& From, const FVector& To)> PathLength,
	uint64 MatchSeed,
	uint64 DeathCount)
{
	FVerseSpawnChoice Out;
	const int32 Count = Candidates.Num();
	Out.Visible.Init(false, Count);
	Out.Distances.Init(0.f, Count);
	if (Count == 0)
	{
		return Out;
	}

	TArray<int32> Open;
	for (int32 i = 0; i < Count; ++i)
	{
		if (!Candidates[i].bBlocked)
		{
			Open.Add(i);
		}
	}
	if (Open.IsEmpty())
	{
		for (int32 i = 0; i < Count; ++i)
		{
			Open.Add(i);
		}
	}

	if (OpponentEye.IsSet())
	{
		const FVector Eye = OpponentEye.GetValue();
		// The opponent's feet are below the eye; path lengths start from the floor under it.
		for (const int32 i : Open)
		{
			const FVerseSpawnCandidate& C = Candidates[i];
			bool bSeen = false;
			for (const float HeightM : C.ProbeHeightsM)
			{
				if (LineClear(Eye, C.Floor + FVector(0.0, 0.0, HeightM * 100.0)))
				{
					bSeen = true;
					break;
				}
			}
			Out.Visible[i] = bSeen;
			const float Path = PathLength(Eye, C.Floor);
			Out.Distances[i] = Path >= 0.f ? Path : float(FVector::Dist(Eye, C.Floor));
		}
	}

	for (const int32 i : Open)
	{
		if (!Out.Visible[i])
		{
			Out.Pool.Add(i);
		}
	}
	if (Out.Pool.IsEmpty())
	{
		Out.Pool = Open;
	}

	float Best = -1.f;
	for (const int32 i : Out.Pool)
	{
		Best = FMath::Max(Best, Out.Distances[i]);
	}
	TArray<int32> Ties;
	for (const int32 i : Out.Pool)
	{
		if (Out.Distances[i] >= Best - TieCm)
		{
			Ties.Add(i);
		}
	}
	FVerseRng Rng(MatchSeed, DeathCount, EVerseRngSalt::Spawn);
	Out.Index = Ties[Rng.RangeInt(0, Ties.Num() - 1)];
	Out.bVisible = Out.Visible[Out.Index];
	Out.DistanceCm = Out.Distances[Out.Index];
	return Out;
}
